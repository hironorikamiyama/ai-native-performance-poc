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


def compare_baseline(
    current: dict[str, Any], baseline: dict[str, Any], regression_policy: dict[str, float]
) -> list[dict[str, Any]]:
    findings = []
    for metric in ("p95_ms", "p99_ms"):
        before = baseline["peak"][metric]
        after = current["peak"][metric]
        change = ((after - before) / before * 100) if before else 0.0
        limit = regression_policy[f"{metric}_percent_max"]
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
    return findings


def render_markdown(report: dict[str, Any]) -> str:
    peak = report["summary"]["peak"]
    evaluation = report["evaluation"]
    lines = [
        "# Performance Test Analysis",
        "",
        f"**Service verdict: {report['verdict']}**",
        "",
        "## Evaluation window",
        "",
        f"- Warm-up seconds: {evaluation['warmup_seconds']:.0f}",
        f"- Current rows excluded: {evaluation['excluded_rows']}",
    ]

    if evaluation["baseline_excluded_rows"] is not None:
        lines.append(
            "- Baseline rows excluded: "
            f"{evaluation['baseline_excluded_rows']}"
        )

    lines.extend(
        [
            "- Limitation: Locust percentile and request counters "
            "remain cumulative.",
            "",
            "## Deterministic evidence",
            "",
            f"- Samples: {report['summary']['samples']}",
            f"- Peak users: {peak['users']:.0f}",
            f"- Peak p95: {peak['p95_ms']:.2f} ms",
            f"- Peak p99: {peak['p99_ms']:.2f} ms",
            "- Final cumulative error rate: "
            f"{report['summary']['latest']['error_rate_percent']:.3f}%",
            f"- Peak observed error rate: {peak['error_rate_percent']:.3f}%",
            f"- Peak throughput: {peak['rps']:.2f} requests/s",
        ]
    )
    lines.append("- CPU: not supplied" if peak["cpu_percent"] is None else f"- Peak CPU: {peak['cpu_percent']:.2f}%")
    lines.append("- Memory: not supplied" if peak["memory_percent"] is None else f"- Peak memory: {peak['memory_percent']:.2f}%")
    lines.extend(["", "## Checks", ""])
    for item in report["findings"]:
        if item["kind"] == "threshold":
            lines.append(f"- {item['status']}: {item['metric']}={item['actual']} (limit {item['limit']})")
        else:
            lines.append(
                f"- {item['status']}: {item['metric']} changed {item['change_percent']}% "
                f"({item['baseline']} -> {item['current']}; limit {item['limit_percent']}%)"
            )
    if report["comparability"]:
        lines.extend(["", "## Baseline comparability", ""])
        lines.append(f"- {report['comparability']['status']}: {report['comparability']['message']}")
    lines.extend(
        [
            "",
            "## AI review instructions",
            "",
            "Using only the evidence above, explain observed trends and risks. Treat causes as hypotheses, "
            "state what additional application/DB/infrastructure evidence would confirm them, and require "
            "human review before a release decision.",
            "",
        ]
    )
    return "\n".join(lines)


def compare_manifests(current_path: Path, baseline_path: Path) -> dict[str, Any]:
    current = json.loads(current_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    fields = ("tool", "target", "workload_signature")
    mismatches = [field for field in fields if current.get(field) != baseline.get(field)]
    if mismatches:
        return {
            "status": "NOT_COMPARABLE",
            "message": f"Manifest mismatch: {', '.join(mismatches)}",
            "mismatches": mismatches,
        }
    return {"status": "COMPARABLE", "message": "Tool, target, and workload signature match.", "mismatches": []}


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
    evaluated_rows, excluded_rows = exclude_warmup(
        result_rows,
        warmup_seconds,
    )
    summary = summarize(evaluated_rows)
    findings = evaluate(summary, policy)

    baseline_summary = None
    baseline_excluded_rows = None
    comparability = None


    if bool(manifest_path) != bool(baseline_manifest_path):
        raise ValueError("Both --manifest and --baseline-manifest are required together")
    if manifest_path and baseline_manifest_path:
        comparability = compare_manifests(manifest_path, baseline_manifest_path)
    if baseline_path:
        baseline_rows = load_rows(baseline_path)
        evaluated_baseline_rows, baseline_excluded_rows = exclude_warmup(
            baseline_rows,
            warmup_seconds,
        )
        baseline_summary = summarize(evaluated_baseline_rows)

        if comparability is None or comparability["status"] == "COMPARABLE":
            findings.extend(compare_baseline(summary, baseline_summary, policy["regression_fail"]))
    has_failures = any(item["status"] == "FAIL" for item in findings)
    has_warnings = any(item["status"] == "WARN" for item in findings)
    return {
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
            "note": (
                "Rows within the warm-up period are excluded. "
                "Locust percentile and request counters remain cumulative."
            ),
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
