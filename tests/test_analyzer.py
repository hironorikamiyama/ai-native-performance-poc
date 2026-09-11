import importlib.util
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
    assert {"p95_ms", "p99_ms", "error_rate_percent", "cpu_percent"} <= failed_metrics


def test_baseline_passes() -> None:
    report = MODULE.build_report(
        ROOT / "data" / "baseline.csv",
        ROOT / "config" / "thresholds.json",
    )
    assert report["verdict"] == "PASS"


def test_locust_history_skips_initial_na_row() -> None:
    report = MODULE.build_report(
        ROOT / "data" / "locust_history_sample.csv",
        ROOT / "config" / "thresholds.json",
    )
    assert report["verdict"] == "PASS"
    assert report["summary"]["samples"] == 1
    assert report["summary"]["peak"]["p95_ms"] == 30
