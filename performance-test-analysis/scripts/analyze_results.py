#!/usr/bin/env python3
"""Deterministically summarize performance-test CSV data."""

from __future__ import annotations

import argparse
import csv
import json
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
    def error_rate_percent(self) -> float:
        return (self.failures / self.requests * 100) if self.requests else 0.0


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
    if warmup_seconds < 0:
        raise ValueError("warmup_seconds must be zero or greater")

    if warmup_seconds == 0:
        return rows, 0

    started_at = parse_timestamp(rows[0].timestamp)
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
        current.requests < previous.requests
        for previous, current in zip(rows, rows[1:])
    )


def summarize(rows: list[MetricRow]) -> dict[str, Any]:
    latest = rows[-1]
    return {
        "samples": len(rows),
        "latest": {**asdict(latest), "error_rate_percent": round(latest.error_rate_percent, 3)},
        "peak": {
            "users": max(row.users for row in rows),
            "avg_ms": max(row.avg_ms for row in rows),
            "p95_ms": max(row.p95_ms for row in rows),
            "p99_ms": max(row.p99_ms for row in rows),
            "error_rate_percent": round(max(row.error_rate_percent for row in rows), 3),
            "rps": max(row.rps for row in rows),
            "cpu_percent": max((row.cpu_percent for row in rows if row.cpu_percent is not None), default=None),
            "memory_percent": max((row.memory_percent for row in rows if row.memory_percent is not None), default=None),
        },
        "median": {
            "p95_ms": statistics.median(row.p95_ms for row in rows),
            "p99_ms": statistics.median(row.p99_ms for row in rows),
            "rps": statistics.median(row.rps for row in rows),
        },
    }


# PoC verdict policy:
# - Absolute service thresholds use peak p95, peak p99,
#   and final cumulative error rate.
# - Resource metrics are WARN only.
# - Regression thresholds use peak p95/p99 degradation
#   and median RPS decrease versus baseline.
# - Any FAIL => FAIL.
# - WARN without FAIL => PASS_WITH_WARNINGS.
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
    findings = []
    for category, metric, actual, limit, breach_status in checks:
        if actual is None or limit is None:
            continue
        findings.append(
            {
                "kind": "threshold",
                "category": category,
                "metric": metric,
                "actual": actual,
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

        change = calculate_change_percent(before, after)

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

    if baseline_rps == 0:
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


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Performance Test Analysis",
        "",
        f"- Report schema version: {report['report_schema_version']}",
        f"- Service verdict: **{report['verdict']}**",
        "",
        "## Evaluation window",
        "",
        f"- Warm-up seconds: {report['evaluation']['warmup_seconds']}",
        f"- Current rows excluded: {report['evaluation']['excluded_rows']}",
        f"- Baseline rows excluded: "
        f"{report['evaluation'].get('baseline_excluded_rows')}",
        f"- Current stats reset detected: "
        f"{report['evaluation']['stats_reset_detected']}",
        f"- Baseline stats reset detected: "
        f"{report['evaluation'].get('baseline_stats_reset_detected')}",
        f"- Note: {report['evaluation']['note']}",
        "",
        "## Deterministic evidence",
        "",
        f"- Samples: {report['summary']['samples']}",
        f"- Peak users: {report['summary']['peak']['users']:.0f}",
        f"- Peak p95: {report['summary']['peak']['p95_ms']:.2f} ms",
        f"- Peak p99: {report['summary']['peak']['p99_ms']:.2f} ms",
        f"- Final cumulative error rate: "
        f"{report['summary']['latest']['error_rate_percent']:.3f}%",
        f"- Peak observed error rate: "
        f"{report['summary']['peak']['error_rate_percent']:.3f}%",
        f"- Peak throughput: "
        f"{report['summary']['peak']['rps']:.2f} requests/s",
        f"- Median throughput: "
        f"{report['summary']['median']['rps']:.2f} requests/s",
    ]

    cpu = report["summary"]["peak"]["cpu_percent"]
    memory = report["summary"]["peak"]["memory_percent"]

    lines.append(
        f"- CPU: {cpu:.2f}%"
        if cpu is not None
        else "- CPU: not supplied"
    )
    lines.append(
        f"- Memory: {memory:.2f}%"
        if memory is not None
        else "- Memory: not supplied"
    )

    lines.extend(
        [
            "",
            "## Checks",
            "",
        ]
    )

    for item in report["findings"]:
        if item["kind"] == "threshold":
            lines.append(
                f"- {item['status']}: "
                f"{item['metric']}={item['actual']} "
                f"(limit {item['limit']})"
            )

        elif item["status"] == "NOT_EVALUATED":
            lines.append(
                f"- NOT_EVALUATED: {item['metric']} "
                f"({item.get('reason', 'Comparison unavailable')})"
            )

        elif item["metric"] == "median_rps":
            lines.append(
                f"- {item['status']}: median_rps decreased "
                f"{item['decrease_percent']}% "
                f"({item['baseline']} -> {item['current']}; "
                f"limit {item['limit_percent']}%)"
            )

        else:
            lines.append(
                f"- {item['status']}: {item['metric']} changed "
                f"{item['change_percent']}% "
                f"({item['baseline']} -> {item['current']}; "
                f"limit {item['limit_percent']}%)"
            )

    if report["comparability"]:
        lines.extend(
            [
                "",
                "## Baseline comparability",
                "",
            ]
        )

        lines.append(
            f"- {report['comparability']['status']}: "
            f"{report['comparability']['message']}"
        )

        mismatches = report["comparability"].get("mismatches", [])
        for mismatch in mismatches:
            lines.append(f"- Mismatch: {mismatch}")

    lines.extend(
        [
            "",
            "## Limitations",
            "",
        ]
    )

    for limitation in report["limitations"]:
        lines.append(f"- {limitation}")

    lines.extend(
        [
            "",
            "## AI review instructions",
            "",
            (
                "Using only the evidence above, explain observed trends "
                "and risks. Treat causes as hypotheses, state what "
                "additional application/DB/infrastructure evidence would "
                "confirm them, and require human review before a release "
                "decision."
            ),
        ]
    )

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


    if bool(manifest_path) != bool(baseline_manifest_path):
        raise ValueError("Both --manifest and --baseline-manifest are required together")
    if manifest_path and baseline_manifest_path:
        comparability = compare_manifests(manifest_path, baseline_manifest_path)
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

        if comparability is None or comparability["status"] == "COMPARABLE":
            findings.extend(compare_baseline(summary, baseline_summary, policy["regression_fail"]))
    has_failures = any(item["status"] == "FAIL" for item in findings)
    has_warnings = any(item["status"] == "WARN" for item in findings)
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
    return {
        "report_schema_version": "1.0",
        "source": str(result_path),
        "baseline_source": str(baseline_path) if baseline_path else None,
        "verdict": "FAIL" if has_failures else ("PASS_WITH_WARNINGS" if has_warnings else "PASS"),
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
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--thresholds", required=True, type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--baseline-manifest", type=Path)
    parser.add_argument("--output-json", type=Path, default=Path("analysis.json"))
    parser.add_argument("--output-md", type=Path, default=Path("analysis.md"))
    args = parser.parse_args()

    report = build_report(
        args.result,
        args.thresholds,
        args.baseline,
        args.manifest,
        args.baseline_manifest,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"{report['verdict']}: wrote {args.output_json} and {args.output_md}")


if __name__ == "__main__":
    main()
