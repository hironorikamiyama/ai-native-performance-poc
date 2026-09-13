import importlib.util
import json
import sys
from pathlib import Path

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "performance-test-analysis" / "scripts" / "analyze_results.py"
SPEC = importlib.util.spec_from_file_location("analyze_results", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_degraded_run_fails_and_detects_regression() -> None:
    report = MODULE.build_report(
        ROOT / "data" / "degraded.csv",
        ROOT / "config" / "thresholds.json",
        ROOT / "data" / "baseline.csv",
    )
    assert report["verdict"] == "FAIL"
    failed_metrics = {x["metric"] for x in report["findings"] if x["status"] == "FAIL"}
    warned_metrics = {x["metric"] for x in report["findings"] if x["status"] == "WARN"}
    assert {"p95_ms", "p99_ms", "error_rate_percent"} <= failed_metrics
    assert "cpu_percent" in warned_metrics


def test_baseline_passes() -> None:
    report = MODULE.build_report(
        ROOT / "data" / "baseline.csv",
        ROOT / "config" / "thresholds.json",
    )
    assert report["verdict"] == "PASS"


def test_locust_history_skips_initial_na_row() -> None:
    rows = MODULE.load_rows(
        ROOT / "data" / "locust_history_sample.csv"
    )

    assert len(rows) == 1
    assert rows[0].p95_ms == 30


def test_exclude_warmup_rows() -> None:
    rows = MODULE.load_rows(ROOT / "data" / "baseline.csv")

    evaluated_rows, excluded_count = MODULE.exclude_warmup(
        rows,
        warmup_seconds=10,
    )

    assert excluded_count == 1
    assert len(evaluated_rows) == 2
    assert evaluated_rows[0].timestamp == "2026-09-11T10:01:00Z"


def test_resource_limit_is_warning_not_service_failure(
    tmp_path: Path,
) -> None:
    policy = json.loads(
        (ROOT / "config" / "thresholds.json").read_text(
            encoding="utf-8"
        )
    )
    policy["evaluation"]["warmup_seconds"] = 0

    policy_path = tmp_path / "thresholds.json"
    policy_path.write_text(
        json.dumps(policy),
        encoding="utf-8",
    )

    report = MODULE.build_report(
        ROOT / "data" / "resource_warning.csv",
        policy_path,
    )

    assert report["verdict"] == "PASS_WITH_WARNINGS"
    assert any(
        finding["metric"] == "cpu_percent"
        and finding["status"] == "WARN"
        for finding in report["findings"]
    )


def test_manifest_mismatch_suppresses_regression_judgement(tmp_path: Path) -> None:
    current = {
        "tool": {"name": "Locust", "version": "2.40.4"},
        "target": {"environment": "test", "dataset_id": "v1"},
        "workload_signature": {"users": 50},
    }
    baseline = {**current, "workload_signature": {"users": 20}}
    current_path = tmp_path / "current.json"
    baseline_path = tmp_path / "baseline.json"
    current_path.write_text(json.dumps(current), encoding="utf-8")
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    report = MODULE.build_report(
        ROOT / "data" / "degraded.csv",
        ROOT / "config" / "thresholds.json",
        ROOT / "data" / "baseline.csv",
        current_path,
        baseline_path,
    )
    assert report["comparability"]["status"] == "NOT_COMPARABLE"
    assert not any(x["kind"] == "regression" for x in report["findings"])
