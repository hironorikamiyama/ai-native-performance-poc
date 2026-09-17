from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]

ANALYZER_PATH = (
    ROOT
    / "performance-test-analysis"
    / "scripts"
    / "analyze_results.py"
)

THRESHOLDS_PATH = ROOT / "config" / "thresholds.json"


def load_analyzer() -> ModuleType:
    """Load analyze_results.py even though its parent directory has a hyphen."""
    spec = importlib.util.spec_from_file_location(
        "analyze_results",
        ANALYZER_PATH,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Could not load analyzer from {ANALYZER_PATH}"
        )

    module = importlib.util.module_from_spec(spec)

    # dataclassなどが __module__ を解決できるように登録する
    import sys
    sys.modules[spec.name] = module

    spec.loader.exec_module(module)

    return module


analyzer = load_analyzer()

POLICY = json.loads(
    THRESHOLDS_PATH.read_text(encoding="utf-8")
)


def make_summary(
    *,
    p95_ms: float = 100.0,
    p99_ms: float = 150.0,
    error_rate_percent: float = 0.0,
    median_rps: float = 100.0,
) -> dict:
    """Create the minimum summary structure required by the evaluator."""
    return {
        "latest": {
            "error_rate_percent": error_rate_percent,
        },
        "peak": {
            "p95_ms": p95_ms,
            "p99_ms": p99_ms,
            "cpu_percent": None,
            "memory_percent": None,
        },
        "median": {
            "rps": median_rps,
        },
    }


def make_verdict(findings: list[dict]) -> str:
    if any(item["status"] == "FAIL" for item in findings):
        return "FAIL"

    if any(item["status"] == "WARN" for item in findings):
        return "PASS_WITH_WARNINGS"

    return "PASS"


def test_normal_scenario_is_pass() -> None:
    """正常系: threshold / regression ともに正常ならPASS."""

    baseline = make_summary(
        p95_ms=100.0,
        p99_ms=150.0,
        error_rate_percent=0.0,
        median_rps=100.0,
    )

    current = make_summary(
        p95_ms=105.0,
        p99_ms=155.0,
        error_rate_percent=0.0,
        median_rps=98.0,
    )

    findings = analyzer.evaluate(
        current,
        POLICY,
    )

    findings.extend(
        analyzer.compare_baseline(
            current,
            baseline,
            POLICY["regression_fail"],
        )
    )

    assert make_verdict(findings) == "PASS"

    assert not any(
        item["status"] == "FAIL"
        for item in findings
    )


def test_latency_regression_is_fail() -> None:
    """
    性能劣化:
    絶対閾値は満たしていても、
    baseline比でp95が20%以上悪化したらFAIL.
    """

    baseline = make_summary(
        p95_ms=100.0,
        p99_ms=150.0,
        error_rate_percent=0.0,
        median_rps=100.0,
    )

    current = make_summary(
        p95_ms=200.0,
        p99_ms=160.0,
        error_rate_percent=0.0,
        median_rps=100.0,
    )

    findings = analyzer.evaluate(
        current,
        POLICY,
    )

    findings.extend(
        analyzer.compare_baseline(
            current,
            baseline,
            POLICY["regression_fail"],
        )
    )

    assert make_verdict(findings) == "FAIL"

    p95_regression = next(
        item
        for item in findings
        if (
            item["kind"] == "regression"
            and item["metric"] == "p95_ms"
        )
    )

    assert p95_regression["status"] == "FAIL"
    assert p95_regression["change_percent"] == 100.0


def test_error_increase_is_fail() -> None:
    """
    エラー増加:
    latencyが正常でも最終累積error rateが閾値超過ならFAIL.
    """

    baseline = make_summary(
        p95_ms=100.0,
        p99_ms=150.0,
        error_rate_percent=0.0,
        median_rps=100.0,
    )

    current = make_summary(
        p95_ms=105.0,
        p99_ms=155.0,
        error_rate_percent=2.0,
        median_rps=100.0,
    )

    findings = analyzer.evaluate(
        current,
        POLICY,
    )

    findings.extend(
        analyzer.compare_baseline(
            current,
            baseline,
            POLICY["regression_fail"],
        )
    )

    assert make_verdict(findings) == "FAIL"

    error_check = next(
        item
        for item in findings
        if (
            item["kind"] == "threshold"
            and item["metric"] == "error_rate_percent"
        )
    )

    assert error_check["status"] == "FAIL"
    assert error_check["actual"] == 2.0