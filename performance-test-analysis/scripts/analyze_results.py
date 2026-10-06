#!/usr/bin/env python3
"""Deterministically summarize performance-test CSV data."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MetricRow:
    timestamp: str
    users: float
    requests: float
    failures: float
    avg_ms: float
    p95_ms: float
    p99_ms: float
    rps: float
    cpu_percent: float | None = None
    memory_percent: float | None = None

    @property
    def error_rate_percent(self) -> float | None:
        return error_rate(self.requests, self.failures)


@dataclass(frozen=True)
class EndpointMetric:
    request_type: str
    name: str
    requests: float
    failures: float
    p95_ms: float
    p99_ms: float
    rps: float

    @property
    def key(self) -> str:
        return f"{self.request_type} {self.name}"

    @property
    def error_rate_percent(self) -> float | None:
        return error_rate(self.requests, self.failures)

ALIASES = {
    "timestamp": ("timestamp", "Timestamp"),
    "users": ("users", "User Count"),
    "requests": ("requests", "Total Request Count"),
    "failures": ("failures", "Total Failure Count"),
    "avg_ms": ("avg_ms", "Total Average Response Time"),
    "p95_ms": ("p95_ms", "95%"),
    "p99_ms": ("p99_ms", "99%"),
    "rps": ("rps", "Requests/s", "Total Requests/s"),
    "cpu_percent": ("cpu_percent",),
    "memory_percent": ("memory_percent",),
}


def _value(row: dict[str, str], key: str, required: bool = True) -> str | None:
    for alias in ALIASES[key]:
        value = row.get(alias)
        if value not in (None, ""):
            return value
    if required:
        raise ValueError(f"Missing required column for {key}: one of {ALIASES[key]}")
    return None


def load_rows(path: Path) -> list[MetricRow]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        source = list(csv.DictReader(handle))
    if not source:
        raise ValueError(f"No data rows found in {path}")

    rows: list[MetricRow] = []
    for raw in source:
        try:
            cpu = _value(raw, "cpu_percent", required=False)
            memory = _value(raw, "memory_percent", required=False)
            rows.append(
                MetricRow(
                    timestamp=str(_value(raw, "timestamp")),
                    users=float(_value(raw, "users")),
                    requests=float(_value(raw, "requests")),
                    failures=float(_value(raw, "failures")),
                    avg_ms=float(_value(raw, "avg_ms")),
                    p95_ms=float(_value(raw, "p95_ms")),
                    p99_ms=float(_value(raw, "p99_ms")),
                    rps=float(_value(raw, "rps")),
                    cpu_percent=float(cpu) if cpu is not None else None,
                    memory_percent=float(memory) if memory is not None else None,
                )
            )
        except ValueError as exc:
            # Locust writes an initial N/A row before response percentiles exist.
            if "N/A" not in str(exc):
                raise
    if not rows:
        raise ValueError(f"No complete numeric metric rows found in {path}")
    return rows


def compare_endpoint_baseline(
    current: EndpointMetric, baseline: EndpointMetric,
    regression_policy: dict[str, float],
) -> list[dict[str, Any]]:
    findings = compare_baseline(
        endpoint_summary(current), endpoint_summary(baseline), regression_policy,
    )
    for item in findings:
        item["endpoint"] = current.key
        if item["metric"] == "median_rps":
            item["metric"] = "rps"
            item["kind"] = "endpoint_observation"
            item["reference_limit_percent"] = item.pop("limit_percent", regression_policy["rps_decrease_percent_max"])
            if item["status"] != "INVALID_DATA":
                item["reference_exceeded"] = item["status"] == "FAIL"
                item["status"] = "INFO"
                item.setdefault("reason", "Endpoint throughput is informational only.")
        else:
            item["kind"] = "endpoint_regression"
    return findings


def load_endpoint_rows(path: Path) -> list[EndpointMetric]:
    """Load endpoint-level metrics from Locust *_stats.csv."""

    with path.open(encoding="utf-8-sig", newline="") as handle:
        source = list(csv.DictReader(handle))

    if not source:
        raise ValueError(f"No endpoint data rows found in {path}")

    rows: list[EndpointMetric] = []

    for raw in source:
        request_type = (raw.get("Type") or "").strip()
        name = (raw.get("Name") or "").strip()

        # Ignore Locust's aggregated row.
        if not request_type or name == "Aggregated":
            continue

        rows.append(
            EndpointMetric(
                request_type=request_type,
                name=name,
                requests=float(raw["Request Count"]),
                failures=float(raw["Failure Count"]),
                p95_ms=float(raw["95%"]),
                p99_ms=float(raw["99%"]),
                rps=float(raw["Requests/s"]),
            )
        )

    if not rows:
        raise ValueError(
            f"No endpoint metric rows found in {path}"
        )

    return rows


def parse_timestamp(value: str) -> float:
    """Convert epoch or ISO 8601 timestamp text to seconds."""
    try:
        return float(value)
    except ValueError:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def exclude_warmup(
    rows: list[MetricRow],
    warmup_seconds: float,
) -> tuple[list[MetricRow], int]:
    """Exclude measurement rows within the warm-up period."""
    if not math.isfinite(warmup_seconds) or warmup_seconds < 0:
        raise ValueError("warmup_seconds must be zero or greater")

    if warmup_seconds == 0:
        return rows, 0

    timestamps = [parse_timestamp(row.timestamp) for row in rows]
    if any(not math.isfinite(value) for value in timestamps):
        # The evaluation window cannot be established safely; preserve evidence.
        return rows, 0
    started_at = timestamps[0]
    cutoff = started_at + warmup_seconds
    evaluated_rows = [
        row for row in rows
        if parse_timestamp(row.timestamp) >= cutoff
    ]

    if not evaluated_rows:
        raise ValueError(
            f"No rows remain after excluding {warmup_seconds} warm-up seconds"
        )

    excluded_count = len(rows) - len(evaluated_rows)
    return evaluated_rows, excluded_count


def detect_stats_reset(rows: list[MetricRow]) -> bool:
    """Detect a decrease in cumulative request counts."""
    return any(
        math.isfinite(current.requests) and math.isfinite(previous.requests)
        and current.requests >= 0 and previous.requests >= 0
        and current.requests < previous.requests
        for previous, current in zip(rows, rows[1:])
    )


def value_reason(metric, value):
    if value is None:
        return f"{metric} measurement is unavailable."
    if not math.isfinite(value):
        return f"{metric} is {value}; a finite measurement is required."
    if metric in ("requests", "failures", "p95_ms", "p99_ms", "rps", "median_rps") and value < 0:
        return f"{metric} is negative ({value})."
    if metric == "requests" and value == 0:
        return "requests is zero; no measured requests are available."
    return None


def count_reason(requests, failures):
    return (value_reason("requests", requests)
            or value_reason("failures", failures)
            or ("failures exceeds requests." if failures > requests else None))


def error_rate(requests, failures):
    if count_reason(requests, failures):
        return None
    result = failures / requests * 100
    return result if math.isfinite(result) else None


def invalid_finding(metric, reason, **context):
    category = "resource" if metric in ("cpu_percent", "memory_percent") else "service"
    return {"kind": "data_quality", "category": category, "metric": metric,
            "status": "INVALID_DATA", "reason": reason, **context}


def row_quality(row, source="current", sample=None):
    findings = []
    context = {"source": source}
    if sample is not None:
        context.update(sample=sample, timestamp=row.timestamp)
    counts = count_reason(row.requests, row.failures)
    if isinstance(row, MetricRow):
        timestamp = parse_timestamp(row.timestamp)
        if not math.isfinite(timestamp):
            findings.append(invalid_finding("timestamp", f"timestamp is {timestamp}; evaluation window is invalid.", **context))
    for metric in asdict(row):
        if metric in ("timestamp", "request_type", "name"):
            continue
        value = getattr(row, metric)
        if value is None and metric in ("cpu_percent", "memory_percent"):
            continue
        reason = value_reason(metric, value)
        if metric == "failures" and not reason and counts == "failures exceeds requests.":
            reason = counts
        if reason:
            findings.append(invalid_finding(metric, reason, **context))
    for metric in ("p95_ms", "p99_ms", "error_rate_percent"):
        if counts:
            findings.append(invalid_finding(metric, counts, **context))
    return findings


def summarize(rows: list[MetricRow]) -> dict[str, Any]:
    quality = [item for index, row in enumerate(rows, 1)
               for item in row_quality(row, sample=index)]

    def values(metric):
        result = []
        for row in rows:
            value = getattr(row, metric)
            if value is None or value_reason(metric, value):
                continue
            if metric in ("p95_ms", "p99_ms") and count_reason(row.requests, row.failures):
                continue
            result.append(value)
        return result

    peaks = {metric: max(values(metric), default=None) for metric in (
        "users", "avg_ms", "p95_ms", "p99_ms", "error_rate_percent",
        "rps", "cpu_percent", "memory_percent")}
    if peaks["error_rate_percent"] is not None:
        peaks["error_rate_percent"] = round(peaks["error_rate_percent"], 3)
    medians = {}
    for metric in ("p95_ms", "p99_ms", "rps"):
        measured = values(metric)
        # A partial median is not a valid baseline comparison input.
        medians[metric] = statistics.median(measured) if len(measured) == len(rows) else None
        if medians[metric] is not None and not math.isfinite(medians[metric]):
            quality.append(invalid_finding(metric, "Calculated median is non-finite."))
            medians[metric] = None
    return {"samples": len(rows),
            "latest": {**asdict(rows[-1]), "error_rate_percent": rows[-1].error_rate_percent},
            "peak": peaks, "median": medians, "data_quality": quality}


def endpoint_summary(endpoint):
    counts = count_reason(endpoint.requests, endpoint.failures)
    return {"latest": {"error_rate_percent": endpoint.error_rate_percent},
            "peak": {"p95_ms": None if counts else endpoint.p95_ms,
                     "p99_ms": None if counts else endpoint.p99_ms,
                     "cpu_percent": None, "memory_percent": None},
            "median": {"rps": endpoint.rps},
            "data_quality": row_quality(endpoint)}


def finite_output(value):
    """Normalize non-finite measurements; strict serialization remains a final guard."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: finite_output(item) for key, item in value.items()}
    if isinstance(value, list):
        return [finite_output(item) for item in value]
    return value


def serialize_report(report):
    return json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)


def determine_verdict(findings: list[dict[str, Any]]) -> str:
    statuses = {item["status"] for item in findings}
    for status, verdict in (("FAIL", "FAIL"), ("INVALID_DATA", "INVALID_DATA"),
                            ("WARN", "PASS_WITH_WARNINGS")):
        if status in statuses:
            return verdict
    return "PASS"


# PoC verdict policy:
# - Absolute service thresholds use peak p95, peak p99,
#   and final cumulative error rate.
# - Resource metrics are WARN only.
# - Regression thresholds use peak p95/p99 degradation
#   and median RPS decrease versus baseline.
# - Any FAIL => FAIL.
# - INVALID_DATA without FAIL => INVALID_DATA.
# - WARN without FAIL or INVALID_DATA => PASS_WITH_WARNINGS.
# - Otherwise => PASS.
# - AI does not participate in deterministic PASS/FAIL judgement.
def evaluate(summary: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    checks = [
        ("service", "p95_ms", summary["peak"]["p95_ms"], policy["service_fail"].get("p95_ms_max"), "FAIL"),
        ("service", "p99_ms", summary["peak"]["p99_ms"], policy["service_fail"].get("p99_ms_max"), "FAIL"),
        (
            "service",
            "error_rate_percent",
            summary["latest"]["error_rate_percent"],
            policy["service_fail"].get("error_rate_percent_max"),
            "FAIL",
        ),
        (
            "resource",
            "cpu_percent",
            summary["peak"]["cpu_percent"],
            policy["resource_warning"].get("cpu_percent_max"),
            "WARN",
        ),
        (
            "resource",
            "memory_percent",
            summary["peak"]["memory_percent"],
            policy["resource_warning"].get("memory_percent_max"),
            "WARN",
        ),
    ]
    findings = list(summary.get("data_quality", []))
    invalid_metrics = {item["metric"] for item in findings}
    for category, metric, actual, limit, breach_status in checks:
        if limit is None:
            continue
        if actual is None and category == "resource":
            continue
        reason = value_reason(metric, actual)
        if reason:
            if metric not in invalid_metrics:
                findings.append(invalid_finding(metric, reason))
            continue
        if metric in invalid_metrics and actual <= limit:
            continue
        findings.append(
            {
                "kind": "threshold",
                "category": category,
                "metric": metric,
                "actual": round(actual, 3) if metric == "error_rate_percent" else actual,
                "limit": limit,
                "status": breach_status if actual > limit else "PASS",
            }
        )


    return findings


def calculate_change_percent(
    before: float,
    after: float,
) -> float | None:
    """Calculate percentage change.

    A zero baseline cannot produce a meaningful relative change,
    so return None instead of treating it as 0%.
    """
    reason = value_reason("baseline", before) or value_reason("current", after)
    if reason:
        raise ValueError(reason)
    if before == 0:
        return None

    return (after - before) / before * 100


def compare_baseline(
    current: dict[str, Any],
    baseline: dict[str, Any],
    regression_policy: dict[str, float],
) -> list[dict[str, Any]]:
    """Compare current performance against baseline deterministically."""

    findings: list[dict[str, Any]] = []

    # Latency regression
    for metric in ("p95_ms", "p99_ms"):
        before = baseline["peak"][metric]
        after = current["peak"][metric]
        limit = regression_policy[f"{metric}_percent_max"]

        reason = comparison_reason(current, baseline, metric, before, after)
        if reason:
            findings.append(invalid_finding(metric, reason, baseline=before, current=after))
            continue
        change = calculate_change_percent(before, after)
        if change is not None and not math.isfinite(change):
            findings.append(invalid_finding(metric, "Calculated change is non-finite.", baseline=before, current=after))
            continue

        if change is None:
            findings.append(
                {
                    "kind": "regression",
                    "category": "service",
                    "metric": metric,
                    "baseline": before,
                    "current": after,
                    "change_percent": None,
                    "limit_percent": limit,
                    "status": "NOT_EVALUATED",
                    "reason": (
                        "Baseline value is zero, so relative "
                        "percentage change cannot be calculated."
                    ),
                }
            )
            continue

        findings.append(
            {
                "kind": "regression",
                "category": "service",
                "metric": metric,
                "baseline": before,
                "current": after,
                "change_percent": round(change, 2),
                "limit_percent": limit,
                "status": "FAIL" if change > limit else "PASS",
            }
        )

    # Throughput regression
    baseline_rps = baseline["median"]["rps"]
    current_rps = current["median"]["rps"]
    rps_limit = regression_policy["rps_decrease_percent_max"]

    reason = comparison_reason(current, baseline, "rps", baseline_rps, current_rps)
    if reason:
        findings.append(invalid_finding("median_rps", reason, baseline=baseline_rps, current=current_rps))
    elif baseline_rps == 0:
        findings.append(
            {
                "kind": "regression",
                "category": "service",
                "metric": "median_rps",
                "baseline": baseline_rps,
                "current": current_rps,
                "decrease_percent": None,
                "limit_percent": rps_limit,
                "status": "NOT_EVALUATED",
                "reason": (
                    "Baseline median RPS is zero, so relative "
                    "throughput decrease cannot be calculated."
                ),
            }
        )
    else:
        decrease_percent = (
            (baseline_rps - current_rps)
            / baseline_rps
            * 100
        )

        if not math.isfinite(decrease_percent):
            findings.append(invalid_finding("median_rps", "Calculated decrease is non-finite.", baseline=baseline_rps, current=current_rps))
            return findings
        findings.append(
            {
                "kind": "regression",
                "category": "service",
                "metric": "median_rps",
                "baseline": baseline_rps,
                "current": current_rps,
                "decrease_percent": round(decrease_percent, 2),
                "limit_percent": rps_limit,
                "status": (
                    "FAIL"
                    if decrease_percent > rps_limit
                    else "PASS"
                ),
            }
        )

    return findings


def comparison_reason(current, baseline, metric, before, after):
    for source, summary, value in (("baseline", baseline, before), ("current", current, after)):
        issues = [item["reason"] for item in summary.get("data_quality", []) if item["metric"] == metric]
        reason = "; ".join(issues) or value_reason(metric, value)
        if reason:
            return f"{source}: {reason}"
    return None


def evaluate_endpoint(endpoint: EndpointMetric, policy: dict[str, Any]) -> list[dict[str, Any]]:
    overrides = policy.get("endpoint_service_fail", {}).get(endpoint.key, {})
    endpoint_policy = {**policy, "service_fail": {**policy["service_fail"], **overrides}}
    findings = evaluate(endpoint_summary(endpoint), endpoint_policy)
    for item in findings:
        item["endpoint"] = endpoint.key
        if item["kind"] == "threshold":
            item["kind"] = "endpoint_threshold"
    return findings


def format_measurement(value, spec):
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "無効／算出不可"
    return format(value, spec)


def render_markdown(report: dict[str, Any]) -> str:
    """Summarize existing evidence for human review without changing the report."""
    def cell(value):
        return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")

    def table(headers, rows):
        if not rows:
            return
        def table_row(values):
            return "| " + " | ".join(map(cell, values)) + " |"

        lines.append(table_row(headers))
        lines.append(table_row(["---" for _ in headers]))
        lines.extend(table_row(row) for row in rows)
        lines.append("")

    def section(title):
        lines.extend(["", f"## {title}", ""])

    def comparison_row(item):
        decrease = "decrease_percent" in item
        change = item.get("decrease_percent" if decrease else "change_percent")
        return [item["metric"],
                f"{item.get('baseline')} → {item.get('current')}",
                "算出不可" if change is None else f"{change}%（{'低下率' if decrease else '変化率'}）",
                f"{item['limit_percent']}%" if "limit_percent" in item else "参考情報",
                item["status"], item.get("reason", "")]

    endpoints = report.get("endpoints", {})
    findings = [("全体", item) for item in report["findings"]]
    findings.extend((name, item) for name, endpoint in endpoints.items() for item in endpoint["findings"])
    problems = {"FAIL", "INVALID_DATA", "WARN", "NOT_EVALUATED"}
    invalid = [(scope, item) for scope, item in findings if item["status"] == "INVALID_DATA"]
    unevaluated = [(scope, item) for scope, item in findings if item["status"] == "NOT_EVALUATED"]
    comparison = report.get("comparability")
    has_baseline = report.get("baseline_summary") is not None or report.get("baseline_source") is not None
    has_endpoint_comparison = any(item["kind"] in ("endpoint_regression", "endpoint_observation") or item.get("source") == "baseline"
                                  for _, item in findings)
    policy = report["policy"]
    lines = ["# Performance Test Analysis", "", "## 1. 総合判定", "",
             f"**総合verdict: {report['verdict']}**", "",
             f"- INVALID_DATA: {'あり' if invalid else 'なし'}",
             f"- 評価基準: {'暫定基準' if policy.get('assumption_status') == 'provisional' else policy.get('assumption_status', '未指定')}"]
    major = [(scope, item) for scope, item in findings if item["status"] in ("FAIL", "WARN")]
    lines.append("- 主要なFAIL / WARN: " + ("; ".join(dict.fromkeys(
        f"{cell(scope)} / {item['metric']} / {item['status']}（{'回帰' if 'regression' in item['kind'] else '閾値'}）"
        for scope, item in major)) if major else "なし"))
    problem_endpoints = [name for name, endpoint in endpoints.items() if any(item["status"] in problems for item in endpoint["findings"])]
    lines.append("- 問題のあるendpoint: " + (", ".join(map(cell, problem_endpoints)) or "なし"))
    if unevaluated or (comparison and comparison["status"] == "NOT_COMPARABLE") or any(
        item["kind"] == "endpoint_observation" and item.get("decrease_percent") is None for _, item in findings
    ):
        lines.append("- 注意: 未評価・比較不能の項目があります。総合判定だけで全項目を評価済みと判断しないでください。")
    if (has_baseline or has_endpoint_comparison) and comparison is None:
        lines.append("- 注意: manifestなしで比較条件未検証です。")

    section("2. データ品質・評価条件")
    table(["対象", "metric", "source", "sample", "status", "reason"], [
        [scope, item["metric"], item.get("source", "未記録"), item.get("sample", "—"), "INVALID_DATA", "無効／算出不可: " + item["reason"]]
        for scope, item in invalid])
    if not invalid:
        lines.append("INVALID_DATAはありません。")
    evaluation = report["evaluation"]
    lines.append(f"- Warm-up seconds: {evaluation['warmup_seconds']}")
    for label, excluded_key, reset_key in (
        ("current", "excluded_rows", "stats_reset_detected"),
        ("baseline", "baseline_excluded_rows", "baseline_stats_reset_detected"),
    ):
        excluded, reset = evaluation.get(excluded_key), evaluation.get(reset_key)
        lines.append(f"- {label} 除外行数: {excluded if excluded is not None else '未指定'}")
        message = "未指定" if reset is None else (
            "検出あり（累積requestsの減少を確認）" if reset else
            "未検出（累積percentile・件数にwarm-upが残っている可能性）")
        lines.append(f"- {label} statistics reset: {message}")
    if evaluation.get("baseline_stats_reset_detected") is not None and evaluation["stats_reset_detected"] != evaluation["baseline_stats_reset_detected"]:
        lines.append("- 注意: current / baselineでreset検出状況が異なります。回帰評価にはデータ品質上の留保があります。")

    section("3. 閾値違反・リソース警告")
    lines.extend(["最終累積エラー率がエラー率の判定値です。peak observed error rateは診断用です。",
                  "判定は丸め前のraw値を使用し、表示値は丸めています。", ""])
    threshold_problems = [item for item in report["findings"] if item["kind"] == "threshold" and item["status"] in ("FAIL", "WARN")]
    table(["metric", "actual", "threshold", "status"], [[item["metric"], item["actual"], item["limit"], item["status"]] for item in threshold_problems])
    if not threshold_problems:
        lines.append("確認された全体の閾値FAIL / リソースWARNはありません（未評価・不正データは別記）。")
    lines.append(f"- Final cumulative error rate: {format_measurement(report['summary']['latest']['error_rate_percent'], '.3f')}%")

    section("4. baseline回帰")
    if comparison:
        lines.append(f"- 比較状態: {comparison['status']} — {cell(comparison['message'])}")
    elif has_baseline or has_endpoint_comparison:
        lines.append("- 比較状態: manifestなしで比較条件未検証")
    else:
        lines.append("- 比較状態: baseline未指定")
    if not has_baseline and has_endpoint_comparison:
        lines.append("- 全体baselineは未指定。endpointの比較情報のみあります。")
    if comparison and comparison["status"] == "NOT_COMPARABLE":
        lines.append("- 全体・endpointの回帰判定は抑止されています。")
    regressions = [item for item in report["findings"] if item["kind"] == "regression"]
    lines.append("")
    table(["metric", "baseline → current", "変化率", "上限", "status", "reason"], [comparison_row(item) for item in sorted(regressions, key=lambda item: item["status"] == "PASS")])
    if unevaluated:
        lines.append("- NOT_EVALUATED: baseline値0等により相対比較できない項目があります（理由は各比較表）。")

    section("5. endpoint別問題")
    if not problem_endpoints:
        lines.append("問題findingのあるendpointはありません。正常endpointは参考情報に要約します。")
    for name in sorted(problem_endpoints, key=lambda name: min(
        {"FAIL": 0, "INVALID_DATA": 1, "WARN": 2, "NOT_EVALUATED": 3}.get(item["status"], 4)
        for item in endpoints[name]["findings"]
    )):
        lines.extend([f"### {cell(name)}", ""])
        items = endpoints[name]["findings"]
        table(["metric", "actual", "threshold", "status"], [[item["metric"], item["actual"], item["limit"], item["status"]]
              for item in items if item["kind"] == "endpoint_threshold" and item["status"] in problems])
        table(["metric", "source", "status", "reason"], [[item["metric"], item.get("source", "未記録"), item["status"], "無効／算出不可: " + item["reason"]]
              for item in items if item["status"] == "INVALID_DATA"])
        table(["metric", "baseline → current", "変化率", "上限", "status", "reason"], [comparison_row(item)
              for item in items if item["kind"] == "endpoint_regression" and item["status"] in problems])

    section("6. 参考情報")
    summary = report["summary"]
    lines.extend([f"- Peak RPS: {format_measurement(summary['peak']['rps'], '.2f')} requests/s",
                  f"- Median throughput: {format_measurement(summary['median']['rps'], '.2f')} requests/s",
                  f"- Peak observed error rate: {format_measurement(summary['peak']['error_rate_percent'], '.3f')}%",
                  f"- Samples: {summary['samples']}",
                  f"- Peak users: {format_measurement(summary['peak']['users'], '.0f')}",
                  f"- policy_id: {cell(policy.get('policy_id', '未指定'))}",
                  f"- assumption_status: {cell(policy.get('assumption_status', '未指定'))}",
                  f"- report_schema_version: {report['report_schema_version']}"])
    for metric in ("cpu_percent", "memory_percent"):
        if summary["peak"][metric] is None:
            state = "無効／算出不可" if any(scope == "全体" and item["metric"] == metric and item.get("source", "current") == "current" for scope, item in invalid) else "未提供（評価省略）"
            lines.append(f"- {metric}: {state}")
    lines.append("")
    table(["正常な全体指標", "actual", "threshold", "status"], [[item["metric"], item["actual"], item["limit"], item["status"]]
          for item in report["findings"] if item["kind"] == "threshold" and item["status"] == "PASS"])
    table(["正常endpoint", "要約"], [[name, "問題findingなし（比較未実施は評価済みを意味しません）"] for name in endpoints if name not in problem_endpoints])
    table(["endpoint RPS INFO", "baseline → current", "低下率", "備考"], [
        [scope, f"{item.get('baseline')} → {item.get('current')}",
         "比較不能" if item.get("decrease_percent") is None else f"{item['decrease_percent']}%",
         item.get("reason", "参考情報のみ")]
        for scope, item in findings if item["kind"] == "endpoint_observation" and item["status"] == "INFO"])
    for limitation in report.get("limitations", []):
        lines.append(f"- {cell(limitation)}")

    section("7. 追加確認事項")
    if invalid:
        lines.append("- INVALID_DATAの対象metric・source・reasonに沿って、元CSVや収集処理を確認してください。")
    if comparison and comparison["status"] == "NOT_COMPARABLE":
        lines.append("- manifest、対象環境、負荷条件の不一致を確認してください。")
    elif (has_baseline or has_endpoint_comparison) and comparison is None:
        lines.append("- manifestが未提供のため、baselineとの比較条件を確認してください。")
    for label, key in (("current", "stats_reset_detected"), ("baseline", "baseline_stats_reset_detected")):
        if evaluation.get(key) is False:
            lines.append(f"- {label}: Locustの統計リセット実施状況を確認してください。")
    if unevaluated or any(item["kind"] == "endpoint_observation" and item.get("decrease_percent") is None for _, item in findings):
        lines.append("- 未評価・比較不能の項目について、baseline値や比較条件を確認してください。")
    lines.append("- 原因仮説の整理はCodex / AIレビュー側で行い、性能評価の承認・リリース可否は人間が判断してください。")
    return "\n".join(lines)


def compare_manifests(
    current_path: Path,
    baseline_path: Path,
) -> dict[str, Any]:
    current = json.loads(
        current_path.read_text(encoding="utf-8")
    )
    baseline = json.loads(
        baseline_path.read_text(encoding="utf-8")
    )

    comparisons = {
        "tool": (
            current.get("tool"),
            baseline.get("tool"),
        ),
        "target": (
            current.get("target"),
            baseline.get("target"),
        ),
        "workload_signature": (
            current.get("workload_signature"),
            baseline.get("workload_signature"),
        ),
        "evaluation.warmup_seconds": (
            current.get("evaluation", {}).get(
                "warmup_seconds"
            ),
            baseline.get("evaluation", {}).get(
                "warmup_seconds"
            ),
        ),
        "evaluation.stats_reset_mode": (
            current.get("evaluation", {}).get(
                "stats_reset_mode"
            ),
            baseline.get("evaluation", {}).get(
                "stats_reset_mode"
            ),
        ),
    }

    mismatches = [
        field
        for field, values in comparisons.items()
        if values[0] != values[1]
    ]

    if mismatches:
        return {
            "status": "NOT_COMPARABLE",
            "message": (
                "Manifest mismatch: "
                + ", ".join(mismatches)
            ),
            "mismatches": mismatches,
        }

    return {
        "status": "COMPARABLE",
        "message": (
            "Tool, target, workload signature, warm-up "
            "duration, and statistics reset mode match."
        ),
        "mismatches": [],
    }

def build_report(
    result_path: Path,
    thresholds_path: Path,
    baseline_path: Path | None = None,
    manifest_path: Path | None = None,
    baseline_manifest_path: Path | None = None,
    endpoint_path: Path | None = None,
    baseline_endpoint_path: Path | None = None,
) -> dict[str, Any]:
    policy = json.loads(thresholds_path.read_text(encoding="utf-8"))
    warmup_seconds = float(
        policy.get("evaluation", {}).get("warmup_seconds", 0)
    )

    result_rows = load_rows(result_path)
    stats_reset_detected = detect_stats_reset(result_rows)
    evaluated_rows, excluded_rows = exclude_warmup(
        result_rows,
        warmup_seconds,
    )
    summary = summarize(evaluated_rows)
    findings = evaluate(summary, policy)

    baseline_summary = None
    baseline_excluded_rows = None
    baseline_stats_reset_detected = None
    comparability = None

    endpoint_results: dict[str, Any] = {}
    endpoint_findings: list[dict[str, Any]] = []

    if baseline_endpoint_path and not endpoint_path:
        raise ValueError(
            "--baseline-endpoint requires --endpoint"
        )

    if bool(manifest_path) != bool(baseline_manifest_path):
        raise ValueError("Both --manifest and --baseline-manifest are required together")
    if manifest_path and baseline_manifest_path:
        comparability = compare_manifests(manifest_path, baseline_manifest_path)

    if endpoint_path:
        current_endpoints = load_endpoint_rows(
            endpoint_path
        )

        baseline_endpoint_map: dict[str, EndpointMetric] = {}

        if baseline_endpoint_path:
            baseline_endpoint_map = {
                row.key: row
                for row in load_endpoint_rows(
                    baseline_endpoint_path
                )
            }

        for endpoint in current_endpoints:
            findings_for_endpoint = evaluate_endpoint(
                endpoint,
                policy,
            )

            baseline_endpoint = baseline_endpoint_map.get(endpoint.key)
            if baseline_endpoint is not None:
                baseline_quality = row_quality(baseline_endpoint, source="baseline")
                for item in baseline_quality:
                    item["endpoint"] = endpoint.key
                findings_for_endpoint.extend(baseline_quality)

            if (
                baseline_endpoint is not None
                and (
                    comparability is None
                    or comparability["status"] == "COMPARABLE"
                )
            ):
                findings_for_endpoint.extend(
                    compare_endpoint_baseline(
                        endpoint,
                        baseline_endpoint,
                        policy["regression_fail"],
                    )
                )

            endpoint_findings.extend(
                findings_for_endpoint
            )

            endpoint_results[endpoint.key] = {
                "request_type": endpoint.request_type,
                "name": endpoint.name,
                "requests": endpoint.requests,
                "failures": endpoint.failures,
                "error_rate_percent": round(endpoint.error_rate_percent, 3) if endpoint.error_rate_percent is not None else None,
                "p95_ms": endpoint.p95_ms,
                "p99_ms": endpoint.p99_ms,
                "rps": endpoint.rps,
                "findings": findings_for_endpoint,
            }

    if baseline_path:
        baseline_rows = load_rows(baseline_path)
        baseline_stats_reset_detected = detect_stats_reset(
            baseline_rows
        )
        evaluated_baseline_rows, baseline_excluded_rows = exclude_warmup(
            baseline_rows,
            warmup_seconds,
        )
        baseline_summary = summarize(evaluated_baseline_rows)
        for item in baseline_summary["data_quality"]:
            item["source"] = "baseline"
        findings.extend(baseline_summary["data_quality"])

        if comparability is None or comparability["status"] == "COMPARABLE":
            findings.extend(compare_baseline(summary, baseline_summary, policy["regression_fail"]))

    all_findings = findings + endpoint_findings
    resets_confirmed = (
        stats_reset_detected
        and (
            baseline_path is None
            or baseline_stats_reset_detected is True
        )
    )

    if resets_confirmed:
        evaluation_note = (
            "A decrease in cumulative request counts confirms "
            "that Locust statistics were reset after warm-up."
        )
    else:
        evaluation_note = (
            "No statistics reset was detected. Locust "
            "percentile and request counters may include "
            "warm-up requests."
        )
    # Round only for output, after all verdict checks have used raw values.
    for output_summary in (summary, baseline_summary):
        if output_summary is not None and output_summary["latest"]["error_rate_percent"] is not None:
            output_summary["latest"]["error_rate_percent"] = round(
                output_summary["latest"]["error_rate_percent"], 3
            )

    return finite_output({
        "report_schema_version": "1.2",
        "source": str(result_path),
        "baseline_source": str(baseline_path) if baseline_path else None,
        "verdict": determine_verdict(all_findings),
        "summary": summary,
        "baseline_summary": baseline_summary,
        "policy": policy,
        "evaluation": {
            "warmup_seconds": warmup_seconds,
            "excluded_rows": excluded_rows,
            "baseline_excluded_rows": baseline_excluded_rows,
            "stats_reset_detected": stats_reset_detected,
            "baseline_stats_reset_detected": (
                baseline_stats_reset_detected
            ),
            "note": evaluation_note,
        },
        "findings": findings,
        "comparability": comparability,
        "limitations": [
            "Metrics alone do not establish root cause.",
            "Capacity conclusions apply only to the tested workload, duration, environment, and data volume.",
        ],
        "endpoints": endpoint_results,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--thresholds", required=True, type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--baseline-manifest", type=Path)
    parser.add_argument("--output-json", type=Path, default=Path("analysis.json"))
    parser.add_argument("--output-md", type=Path, default=Path("analysis.md"))
    parser.add_argument("--endpoint", type=Path)
    parser.add_argument("--baseline-endpoint", type=Path)
    args = parser.parse_args()

    report = build_report(
        result_path=args.result,
        thresholds_path=args.thresholds,
        baseline_path=args.baseline,
        manifest_path=args.manifest,
        baseline_manifest_path=args.baseline_manifest,
        endpoint_path=args.endpoint,
        baseline_endpoint_path=args.baseline_endpoint,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(serialize_report(report), encoding="utf-8")
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"{report['verdict']}: wrote {args.output_json} and {args.output_md}")


if __name__ == "__main__":
    main()
