import importlib.util
import json
import sys
from pathlib import Path
from dataclasses import replace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "performance-test-analysis" / "scripts" / "analyze_results.py"
SPEC = importlib.util.spec_from_file_location("analyze_results", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("failures", "expected_status"),
    [(9996, "PASS"), (10000, "PASS"), (10004, "FAIL")],
)
def test_error_rate_boundary_uses_raw_value_in_report(
    tmp_path: Path, failures: int, expected_status: str,
) -> None:
    policy = json.loads((ROOT / "config" / "thresholds.json").read_text())
    policy["evaluation"]["warmup_seconds"] = 0
    policy_path = tmp_path / "thresholds.json"
    policy_path.write_text(json.dumps(policy))
    history_path = tmp_path / "history.csv"
    history_path.write_text(
        "timestamp,users,requests,failures,avg_ms,p95_ms,p99_ms,rps\n"
        f"0,50,1000000,{failures},20,100,150,100\n"
    )
    endpoint_path = tmp_path / "stats.csv"
    endpoint_path.write_text(
        "Type,Name,Request Count,Failure Count,95%,99%,Requests/s\n"
        f"GET,/items,1000000,{failures},100,150,100\n"
    )
    report = MODULE.build_report(
        history_path, policy_path, endpoint_path=endpoint_path,
    )
    assert report["verdict"] == expected_status
    assert report["summary"]["latest"]["error_rate_percent"] == 1.0
    endpoint = report["endpoints"]["GET /items"]
    assert endpoint["error_rate_percent"] == 1.0
    for findings in (report["findings"], endpoint["findings"]):
        error_finding = next(
            item for item in findings if item["metric"] == "error_rate_percent"
        )
        assert error_finding["status"] == expected_status
        assert error_finding["actual"] == 1.0
    serialized = json.loads(json.dumps(report))
    assert serialized["verdict"] == expected_status
    markdown = MODULE.render_markdown(report)
    assert "Final cumulative error rate: 1.000%" in markdown
    assert f"| error_rate_percent | 1.0 | 1.0 | {expected_status} |" in markdown


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


def test_error_rate_uses_final_cumulative_value() -> None:
    policy = json.loads(
        (ROOT / "config" / "thresholds.json").read_text(
            encoding="utf-8"
        )
    )
    summary = {
        "latest": {
            "error_rate_percent": 0.5,
        },
        "peak": {
            "p95_ms": 100.0,
            "p99_ms": 200.0,
            "error_rate_percent": 5.0,
            "cpu_percent": None,
            "memory_percent": None,
        },
    }

    findings = MODULE.evaluate(summary, policy)
    error_finding = next(
        finding
        for finding in findings
        if finding["metric"] == "error_rate_percent"
    )

    assert error_finding["actual"] == 0.5
    assert error_finding["status"] == "PASS"


def test_rps_decrease_detects_regression() -> None:
    policy = json.loads(
        (ROOT / "config" / "thresholds.json").read_text(
            encoding="utf-8"
        )
    )
    baseline = {
        "peak": {
            "p95_ms": 100.0,
            "p99_ms": 200.0,
        },
        "median": {
            "rps": 100.0,
        },
    }
    current = {
        "peak": {
            "p95_ms": 100.0,
            "p99_ms": 200.0,
        },
        "median": {
            "rps": 75.0,
        },
    }

    findings = MODULE.compare_baseline(
        current,
        baseline,
        policy["regression_fail"],
    )
    rps_finding = next(
        finding
        for finding in findings
        if finding["metric"] == "median_rps"
    )

    assert rps_finding["baseline"] == 100.0
    assert rps_finding["current"] == 75.0
    assert rps_finding["decrease_percent"] == 25.0
    assert rps_finding["status"] == "FAIL"


def test_detect_stats_reset_from_request_count_drop() -> None:
    rows = MODULE.load_rows(ROOT / "data" / "baseline.csv")

    reset_rows = [
        rows[0],
        replace(rows[1], requests=10.0),
        rows[2],
    ]

    assert MODULE.detect_stats_reset(reset_rows) is True
    assert MODULE.detect_stats_reset(rows) is False


def test_manifest_warmup_mismatch_is_not_comparable(
    tmp_path: Path,
) -> None:
    current = {
        "tool": {
            "name": "Locust",
            "version": "2.40.4",
        },
        "target": {
            "environment": "test",
            "dataset_id": "v1",
        },
        "workload_signature": {
            "users": 50,
        },
        "evaluation": {
            "warmup_seconds": 10.0,
            "stats_reset_mode": "locust_reset_all",
        },
    }
    baseline = {
        **current,
        "evaluation": {
            "warmup_seconds": 20.0,
            "stats_reset_mode": "locust_reset_all",
        },
    }

    current_path = tmp_path / "current-manifest.json"
    baseline_path = tmp_path / "baseline-manifest.json"

    current_path.write_text(
        json.dumps(current),
        encoding="utf-8",
    )
    baseline_path.write_text(
        json.dumps(baseline),
        encoding="utf-8",
    )

    result = MODULE.compare_manifests(
        current_path,
        baseline_path,
    )

    assert result["status"] == "NOT_COMPARABLE"
    assert (
        "evaluation.warmup_seconds"
        in result["mismatches"]
    )

def test_load_endpoint_rows() -> None:
    rows = MODULE.load_endpoint_rows(
        ROOT
        / "results"
        / "runs"
        / "regression-reset-v2"
        / "locust_stats.csv"
    )

    assert len(rows) == 2

    items = next(
        row
        for row in rows
        if row.key == "GET /items"
    )

    assert items.requests == 3543
    assert items.failures == 95
    assert items.p95_ms == 360
    assert items.p99_ms == 360


def test_endpoint_threshold_detects_items_failure() -> None:
    policy = json.loads(
        (
            ROOT
            / "config"
            / "thresholds.json"
        ).read_text(encoding="utf-8")
    )

    rows = MODULE.load_endpoint_rows(
        ROOT
        / "results"
        / "runs"
        / "regression-reset-v2"
        / "locust_stats.csv"
    )

    items = next(
        row
        for row in rows
        if row.key == "GET /items"
    )

    findings = MODULE.evaluate_endpoint(
        items,
        policy,
    )

    failed = {
        finding["metric"]
        for finding in findings
        if finding["status"] == "FAIL"
    }

    assert "p95_ms" in failed
    assert "error_rate_percent" in failed
    assert "p99_ms" not in failed


def test_endpoint_baseline_detects_items_regression() -> None:
    policy = json.loads(
        (
            ROOT
            / "config"
            / "thresholds.json"
        ).read_text(encoding="utf-8")
    )

    current_rows = MODULE.load_endpoint_rows(
        ROOT
        / "results"
        / "runs"
        / "regression-reset-v2"
        / "locust_stats.csv"
    )

    baseline_rows = MODULE.load_endpoint_rows(
        ROOT
        / "results"
        / "runs"
        / "baseline-reset-v1"
        / "locust_stats.csv"
    )

    current = next(
        row
        for row in current_rows
        if row.key == "GET /items"
    )

    baseline = next(
        row
        for row in baseline_rows
        if row.key == "GET /items"
    )

    findings = MODULE.compare_endpoint_baseline(
        current,
        baseline,
        policy["regression_fail"],
    )

    failed = {
        finding["metric"]
        for finding in findings
        if finding["status"] == "FAIL"
    }

    assert {
        "p95_ms",
        "p99_ms",
    } <= failed

    rps_finding = next(
        finding
        for finding in findings
        if finding["metric"] == "rps"
    )

    assert rps_finding["status"] == "INFO"
    assert rps_finding["decrease_percent"] == 48.21
    assert rps_finding["reference_exceeded"] is True


def test_build_report_includes_endpoint_analysis() -> None:
    report = MODULE.build_report(
        ROOT
        / "results"
        / "runs"
        / "regression-reset-v2"
        / "locust_stats_history.csv",
        ROOT
        / "config"
        / "thresholds.json",
        ROOT
        / "results"
        / "runs"
        / "baseline-reset-v1"
        / "locust_stats_history.csv",
        endpoint_path=(
            ROOT
            / "results"
            / "runs"
            / "regression-reset-v2"
            / "locust_stats.csv"
        ),
        baseline_endpoint_path=(
            ROOT
            / "results"
            / "runs"
            / "baseline-reset-v1"
            / "locust_stats.csv"
        ),
    )

    assert report["report_schema_version"] == "1.2"
    assert "GET /health" in report["endpoints"]
    assert "GET /items" in report["endpoints"]

    items = report["endpoints"]["GET /items"]

    assert items["p95_ms"] == 360
    assert items["p99_ms"] == 360
    assert report["verdict"] == "FAIL"


def test_manifest_mismatch_suppresses_endpoint_regression(
    tmp_path: Path,
) -> None:
    current_manifest = {
        "tool": {
            "name": "Locust",
            "version": "2.40.4",
        },
        "target": {
            "environment": "test",
            "dataset_id": "v1",
        },
        "workload_signature": {
            "users": 50,
        },
    }

    baseline_manifest = {
        **current_manifest,
        "workload_signature": {
            "users": 20,
        },
    }

    current_manifest_path = tmp_path / "current.json"
    baseline_manifest_path = tmp_path / "baseline.json"

    current_manifest_path.write_text(
        json.dumps(current_manifest),
        encoding="utf-8",
    )

    baseline_manifest_path.write_text(
        json.dumps(baseline_manifest),
        encoding="utf-8",
    )

    report = MODULE.build_report(
        ROOT
        / "results"
        / "runs"
        / "regression-reset-v2"
        / "locust_stats_history.csv",
        ROOT
        / "config"
        / "thresholds.json",
        baseline_path=(
            ROOT
            / "results"
            / "runs"
            / "baseline-reset-v1"
            / "locust_stats_history.csv"
        ),
        manifest_path=current_manifest_path,
        baseline_manifest_path=baseline_manifest_path,
        endpoint_path=(
            ROOT
            / "results"
            / "runs"
            / "regression-reset-v2"
            / "locust_stats.csv"
        ),
        baseline_endpoint_path=(
            ROOT
            / "results"
            / "runs"
            / "baseline-reset-v1"
            / "locust_stats.csv"
        ),
    )

    assert report["comparability"]["status"] == "NOT_COMPARABLE"

    endpoint_findings = [
        finding
        for endpoint in report["endpoints"].values()
        for finding in endpoint["findings"]
    ]

    assert not any(
        finding["kind"] == "endpoint_regression"
        for finding in endpoint_findings
    )

def test_endpoint_rps_does_not_cause_failure() -> None:
    policy = json.loads(
        (
            ROOT
            / "config"
            / "thresholds.json"
        ).read_text(encoding="utf-8")
    )

    current_rows = MODULE.load_endpoint_rows(
        ROOT
        / "results"
        / "runs"
        / "regression-reset-v2"
        / "locust_stats.csv"
    )

    baseline_rows = MODULE.load_endpoint_rows(
        ROOT
        / "results"
        / "runs"
        / "baseline-reset-v1"
        / "locust_stats.csv"
    )

    current = next(
        row
        for row in current_rows
        if row.key == "GET /health"
    )

    baseline = next(
        row
        for row in baseline_rows
        if row.key == "GET /health"
    )

    findings = MODULE.compare_endpoint_baseline(
        current,
        baseline,
        policy["regression_fail"],
    )

    rps_finding = next(
        finding
        for finding in findings
        if finding["metric"] == "rps"
    )

    assert rps_finding["decrease_percent"] == 42.6
    assert rps_finding["status"] == "INFO"

    assert not any(
        finding["status"] == "FAIL"
        for finding in findings
    )


@pytest.fixture
def quality_inputs(tmp_path: Path):
    policy = json.loads((ROOT / "config" / "thresholds.json").read_text())
    policy["evaluation"]["warmup_seconds"] = 0
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy))

    def write_rows(rows, filename="history.csv"):
        path = tmp_path / filename
        columns = "timestamp,users,requests,failures,avg_ms,p95_ms,p99_ms,rps,cpu_percent,memory_percent".split(",")
        defaults = dict(timestamp=0, users=10, requests=100, failures=0,
                        avg_ms=20, p95_ms=100, p99_ms=150, rps=100,
                        cpu_percent=20, memory_percent=30)
        path.write_text(",".join(columns) + "\n" + "".join(
            ",".join(str({**defaults, "timestamp": index, **row}[key]) for key in columns) + "\n"
            for index, row in enumerate(rows)
        ))
        return path

    def write_endpoint(row, filename="endpoint.csv"):
        path = tmp_path / filename
        defaults = dict(requests=100, failures=0, p95_ms=100, p99_ms=150, rps=100)
        values = {**defaults, **row}
        path.write_text("Type,Name,Request Count,Failure Count,95%,99%,Requests/s\n"
                        + "GET,/items," + ",".join(str(values[key]) for key in defaults) + "\n")
        return path

    return policy_path, write_rows, write_endpoint


@pytest.mark.parametrize("metric", ["requests", "failures", "p95_ms", "p99_ms", "rps", "users", "avg_ms", "cpu_percent", "memory_percent"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_nonfinite_history_cannot_pass(quality_inputs, metric, value, position):
    policy, history, _ = quality_inputs
    rows = [{}, {}, {}]
    rows[position] = {metric: value}
    report = MODULE.build_report(history(rows), policy)
    assert report["verdict"] == "INVALID_DATA"
    invalid = [item for item in report["findings"] if item["status"] == "INVALID_DATA"]
    assert any(item["metric"] == metric and item["reason"] and item["sample"] == position + 1 for item in invalid)
    assert not any(item["metric"] == metric and item["status"] == "PASS" for item in report["findings"])
    serialized = MODULE.serialize_report(report)
    if position == 2:
        assert json.loads(serialized)["summary"]["latest"][metric] is None
    assert "INVALID_DATA" in MODULE.render_markdown(report)
    assert "無効／算出不可" in MODULE.render_markdown(report)


@pytest.mark.parametrize("row,metric", [
    ({"requests": 0}, "requests"),
    ({"requests": 0, "failures": 1}, "requests"),
    ({"requests": -1}, "requests"),
    ({"failures": -1}, "failures"),
    ({"failures": 101}, "failures"),
    ({"p95_ms": -1}, "p95_ms"),
    ({"p99_ms": -1}, "p99_ms"),
    ({"rps": -1}, "rps"),
])
def test_invalid_counts_and_negative_measurements(quality_inputs, row, metric):
    policy, history, endpoint = quality_inputs
    report = MODULE.build_report(history([row]), policy, endpoint_path=endpoint(row))
    assert report["verdict"] == "INVALID_DATA"
    for findings in (report["findings"], report["endpoints"]["GET /items"]["findings"]):
        assert any(item["metric"] == metric and item["status"] == "INVALID_DATA" and item["reason"] for item in findings)
        if "requests" in row or "failures" in row:
            assert not any(item["metric"] in ("p95_ms", "p99_ms", "error_rate_percent") and item["status"] == "PASS" for item in findings)
    if "requests" in row or "failures" in row:
        assert report["summary"]["latest"]["error_rate_percent"] is None
        assert report["endpoints"]["GET /items"]["error_rate_percent"] is None
    MODULE.serialize_report(report)
    MODULE.render_markdown(report)


@pytest.mark.parametrize("metric", ["requests", "failures", "p95_ms", "p99_ms", "rps"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1])
@pytest.mark.parametrize("source", ["current", "baseline"])
def test_endpoint_quality_and_comparison(quality_inputs, metric, value, source):
    policy, history, endpoint = quality_inputs
    current = endpoint({metric: value} if source == "current" else {})
    baseline = endpoint({metric: value} if source == "baseline" else {}, "baseline-endpoint.csv")
    report = MODULE.build_report(history([{}]), policy, endpoint_path=current, baseline_endpoint_path=baseline)
    assert report["verdict"] == "INVALID_DATA"
    findings = report["endpoints"]["GET /items"]["findings"]
    assert any(item["metric"] == metric and item["status"] == "INVALID_DATA" and item.get("source") == source for item in findings)
    MODULE.serialize_report(report)
    assert "INVALID_DATA" in MODULE.render_markdown(report)


@pytest.mark.parametrize("metric", ["p95_ms", "p99_ms", "rps"])
@pytest.mark.parametrize("source", ["current", "baseline"])
def test_invalid_history_baseline_comparison(quality_inputs, metric, source):
    policy, history, _ = quality_inputs
    current = history([{metric: float("nan")} if source == "current" else {}])
    baseline = history([{metric: float("nan")} if source == "baseline" else {}], "baseline.csv")
    report = MODULE.build_report(current, policy, baseline_path=baseline)
    assert report["verdict"] == "INVALID_DATA"
    comparison_metric = "median_rps" if metric == "rps" else metric
    assert any(item["metric"] == comparison_metric and item["status"] == "INVALID_DATA" and source in item["reason"] for item in report["findings"])


@pytest.mark.parametrize("breach,expected", [({}, "INVALID_DATA"), ({"cpu_percent": 90}, "INVALID_DATA"), ({"p99_ms": 600}, "FAIL")])
def test_verdict_priority_retains_invalid_findings(quality_inputs, breach, expected):
    policy, history, endpoint = quality_inputs
    report = MODULE.build_report(history([breach]), policy, endpoint_path=endpoint({"p95_ms": float("nan")}))
    assert report["verdict"] == expected
    assert any(item["status"] == "INVALID_DATA" for item in report["endpoints"]["GET /items"]["findings"])
    assert "INVALID_DATA" in MODULE.render_markdown(report)


def test_valid_peak_failure_survives_invalid_sample(quality_inputs):
    policy, history, _ = quality_inputs
    report = MODULE.build_report(history([{"p95_ms": float("nan")}, {"p95_ms": 300}]), policy)
    assert report["verdict"] == "FAIL"
    assert {item["status"] for item in report["findings"] if item["metric"] == "p95_ms"} == {"FAIL", "INVALID_DATA"}


@pytest.mark.parametrize("metric,limit", [("p95_ms", 250), ("p99_ms", 500)])
@pytest.mark.parametrize("offset,status", [(-0.001, "PASS"), (0, "PASS"), (0.001, "FAIL")])
def test_latency_threshold_boundaries(quality_inputs, metric, limit, offset, status):
    policy, history, endpoint = quality_inputs
    report = MODULE.build_report(history([{metric: limit + offset}]), policy, endpoint_path=endpoint({metric: limit + offset}))
    assert report["verdict"] == status


def test_zero_latency_and_rps_baselines_keep_existing_statuses(quality_inputs):
    policy, history, endpoint = quality_inputs
    zeros = {"p95_ms": 0, "p99_ms": 0, "rps": 0}
    report = MODULE.build_report(history([{}]), policy, baseline_path=history([zeros], "baseline.csv"),
                                 endpoint_path=endpoint({}), baseline_endpoint_path=endpoint(zeros, "baseline-endpoint.csv"))
    assert report["verdict"] == "PASS"
    assert len([item for item in report["findings"] if item["status"] == "NOT_EVALUATED"]) == 3
    findings = report["endpoints"]["GET /items"]["findings"]
    assert len([item for item in findings if item["status"] == "NOT_EVALUATED"]) == 2
    assert next(item for item in findings if item["metric"] == "rps")["status"] == "INFO"


def test_calculated_change_overflow_is_invalid(quality_inputs):
    policy, history, endpoint = quality_inputs
    report = MODULE.build_report(history([{}]), policy, baseline_path=history([{"p95_ms": 1e-308}], "baseline.csv"),
                                 endpoint_path=endpoint({}), baseline_endpoint_path=endpoint({"p95_ms": 1e-308}, "baseline-endpoint.csv"))
    assert report["verdict"] == "INVALID_DATA"
    for findings in (report["findings"], report["endpoints"]["GET /items"]["findings"]):
        assert any(item["metric"] == "p95_ms" and item["status"] == "INVALID_DATA" and "non-finite" in item["reason"] for item in findings)
    MODULE.serialize_report(report)


def test_strict_json_serialization_rejects_accidental_nonfinite_values():
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            MODULE.serialize_report({"nested": {"accidental": value}})


def test_excluded_warmup_invalid_measurement_does_not_affect_verdict(quality_inputs):
    policy, history, _ = quality_inputs
    config = json.loads(policy.read_text())
    config["evaluation"]["warmup_seconds"] = 1
    policy.write_text(json.dumps(config))
    report = MODULE.build_report(history([{"p95_ms": float("nan")}, {}]), policy)
    assert report["verdict"] == "PASS"
    assert report["evaluation"]["excluded_rows"] == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_invalid_timestamp_is_not_silently_excluded(quality_inputs, value):
    policy, history, _ = quality_inputs
    config = json.loads(policy.read_text())
    config["evaluation"]["warmup_seconds"] = 1
    policy.write_text(json.dumps(config))
    report = MODULE.build_report(history([{}, {"timestamp": value}, {}]), policy)
    assert report["verdict"] == "INVALID_DATA"
    assert any(item["metric"] == "timestamp" and item["status"] == "INVALID_DATA" for item in report["findings"])
    MODULE.serialize_report(report)


def test_median_overflow_cannot_pass_without_baseline(quality_inputs):
    policy, history, _ = quality_inputs
    report = MODULE.build_report(history([{"rps": 1e308}, {"rps": 1e308}]), policy)
    assert report["verdict"] == "INVALID_DATA"
    assert report["summary"]["median"]["rps"] is None
    MODULE.serialize_report(report)


def test_cli_writes_strict_json_and_invalid_markdown(quality_inputs, tmp_path):
    import subprocess
    policy, history, endpoint = quality_inputs
    output_json = tmp_path / "analysis.json"
    output_md = tmp_path / "analysis.md"
    subprocess.run([
        sys.executable, str(SCRIPT), str(history([{"p95_ms": float("nan")}])),
        "--thresholds", str(policy), "--endpoint", str(endpoint({"requests": 0})),
        "--output-json", str(output_json), "--output-md", str(output_md),
    ], check=True, capture_output=True, text=True)

    def reject_constant(value):
        raise AssertionError(f"Non-standard JSON constant: {value}")

    report = json.loads(output_json.read_text(), parse_constant=reject_constant)
    assert report["report_schema_version"] == "1.2"
    assert report["verdict"] == "INVALID_DATA"
    assert report["summary"]["latest"]["p95_ms"] is None
    assert report["endpoints"]["GET /items"]["error_rate_percent"] is None
    markdown = output_md.read_text()
    assert "INVALID_DATA" in markdown and "無効／算出不可" in markdown
    assert "requests is zero" in markdown


def markdown_section(markdown, number):
    return markdown.split(f"## {number}. ", 1)[1].split("\n## ", 1)[0]


def test_markdown_summary_exposes_failure_and_invalid_data(quality_inputs):
    policy, history, endpoint = quality_inputs
    report = MODULE.build_report(history([{"p99_ms": 600}]), policy,
                                 endpoint_path=endpoint({"rps": -1}))
    markdown = MODULE.render_markdown(report)
    summary = markdown_section(markdown, 1)
    assert "総合verdict: FAIL" in summary
    assert "INVALID_DATA: あり" in summary
    assert "p99_ms / FAIL" in summary
    assert "GET /items" in summary
    assert "暫定基準" in summary
    assert "report_schema_version" not in summary
    assert "report_schema_version: 1.2" in markdown_section(markdown, 6)
    assert "判定は丸め前のraw値を使用し、表示値は丸めています" in markdown
    assert "rps | current | INVALID_DATA" in markdown_section(markdown, 5)


def test_markdown_invalid_sources_and_escaping(quality_inputs):
    import copy
    policy, history, endpoint = quality_inputs
    report = MODULE.build_report(history([{"p95_ms": float("nan")}]), policy,
                                 baseline_path=history([{"p99_ms": float("nan")}], "baseline.csv"),
                                 endpoint_path=endpoint({"rps": -1}),
                                 baseline_endpoint_path=endpoint({"rps": float("inf")}, "baseline-endpoint.csv"))
    report["endpoints"]["GET /items|detail"] = report["endpoints"].pop("GET /items")
    report["endpoints"]["GET /items|detail"]["findings"][0]["reason"] = "bad|value\nsecond line"
    before = copy.deepcopy(report)
    markdown = MODULE.render_markdown(report)
    quality = markdown_section(markdown, 2)
    assert "| p95_ms | current |" in quality
    assert "| p99_ms | baseline |" in quality
    assert "| rps | current |" in quality
    assert "| rps | baseline |" in quality
    assert "GET /items\\|detail" in markdown
    assert "bad\\|value<br>second line" in quality
    assert report == before
    # Unknown source is not silently relabeled as current.
    assert "未記録" in quality


def test_markdown_no_baseline_and_unverified_baseline(quality_inputs):
    policy, history, _ = quality_inputs
    current = history([{}])
    markdown = MODULE.render_markdown(MODULE.build_report(current, policy))
    assert "比較状態: baseline未指定" in markdown_section(markdown, 4)
    assert "baseline 除外行数: 未指定" in markdown
    assert "baseline statistics reset: 未指定" in markdown
    assert "None" not in markdown
    report = MODULE.build_report(current, policy, baseline_path=history([{}], "baseline.csv"))
    markdown = MODULE.render_markdown(report)
    assert "manifestなしで比較条件未検証" in markdown_section(markdown, 1)
    assert "manifestなしで比較条件未検証" in markdown_section(markdown, 4)
    assert "baseline → current" in markdown_section(markdown, 4)


def test_markdown_not_comparable(quality_inputs, tmp_path):
    policy, history, endpoint = quality_inputs
    current_manifest = tmp_path / "current.json"
    baseline_manifest = tmp_path / "baseline.json"
    current_manifest.write_text(json.dumps({"target": "current"}))
    baseline_manifest.write_text(json.dumps({"target": "baseline"}))
    report = MODULE.build_report(history([{}]), policy,
        baseline_path=history([{}], "baseline.csv"),
        manifest_path=current_manifest, baseline_manifest_path=baseline_manifest,
        endpoint_path=endpoint({}), baseline_endpoint_path=endpoint({}, "baseline-endpoint.csv"))
    markdown = MODULE.render_markdown(report)
    assert "未評価・比較不能" in markdown_section(markdown, 1)
    assert "比較状態: NOT_COMPARABLE" in markdown_section(markdown, 4)
    assert "回帰判定は抑止" in markdown_section(markdown, 4)
    assert "manifest、対象環境、負荷条件" in markdown_section(markdown, 7)


def test_markdown_comparable_and_reset_difference(quality_inputs, tmp_path):
    policy, history, _ = quality_inputs
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"target": "same"}))
    report = MODULE.build_report(history([{}, {"requests": 10}]), policy,
        baseline_path=history([{}, {}], "baseline.csv"),
        manifest_path=manifest, baseline_manifest_path=manifest)
    markdown = MODULE.render_markdown(report)
    assert "比較状態: COMPARABLE" in markdown_section(markdown, 4)
    quality = markdown_section(markdown, 2)
    assert "current statistics reset: 検出あり" in quality
    assert "baseline statistics reset: 未検出" in quality
    assert "reset検出状況が異なります" in quality
    checks = markdown_section(markdown, 7)
    assert "baseline: Locust" in checks
    assert "current: Locust" not in checks
    report["evaluation"]["stats_reset_detected"] = False
    report["evaluation"]["baseline_stats_reset_detected"] = True
    quality = markdown_section(MODULE.render_markdown(report), 2)
    assert "current statistics reset: 未検出" in quality
    assert "baseline statistics reset: 検出あり" in quality


def test_markdown_endpoint_priorities_and_info(quality_inputs):
    import copy
    policy, history, endpoint = quality_inputs
    zeros = {"p95_ms": 0, "p99_ms": 0, "rps": 0}
    report = MODULE.build_report(history([{}]), policy,
        baseline_path=history([zeros], "baseline.csv"),
        endpoint_path=endpoint({}), baseline_endpoint_path=endpoint(zeros, "baseline-endpoint.csv"))
    normal = copy.deepcopy(report["endpoints"]["GET /items"])
    normal["findings"] = [item for item in normal["findings"] if item["status"] == "PASS"]
    report["endpoints"] = {"GET /normal": normal, **report["endpoints"]}
    markdown = MODULE.render_markdown(report)
    assert "未評価・比較不能" in markdown_section(markdown, 1)
    assert "NOT_EVALUATED" in markdown_section(markdown, 4)
    problems = markdown_section(markdown, 5)
    assert "NOT_EVALUATED" in problems
    assert "GET /normal" not in problems
    assert "INFO" not in problems
    assert markdown.index("### GET /items") < markdown.index("| GET /normal |")
    references = markdown_section(markdown, 6)
    assert "endpoint RPS INFO" in references
    assert "比較不能" in references
    assert "baseline値や比較条件" in markdown_section(markdown, 7)
    # A usual nonzero INFO comparison also belongs only in reference information.
    info = next(item for item in report["endpoints"]["GET /items"]["findings"] if item["status"] == "INFO")
    info["decrease_percent"] = 40
    markdown = MODULE.render_markdown(report)
    assert "40%" in markdown_section(markdown, 6)
    assert "40%" not in markdown_section(markdown, 5)


def test_markdown_sections_optional_metrics_and_no_hypotheses(quality_inputs):
    policy, _, _ = quality_inputs
    report = MODULE.build_report(ROOT / "data" / "locust_history_sample.csv", policy)
    markdown = MODULE.render_markdown(report)
    headings = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert headings == ["## 1. 総合判定", "## 2. データ品質・評価条件", "## 3. 閾値違反・リソース警告",
                        "## 4. baseline回帰", "## 5. endpoint別問題", "## 6. 参考情報", "## 7. 追加確認事項"]
    assert "cpu_percent: 未提供（評価省略）" in markdown_section(markdown, 6)
    assert "memory_percent: 未提供（評価省略）" in markdown_section(markdown, 6)
    checks = markdown_section(markdown, 7)
    assert not any(word in checks for word in ("DB", "CPU", "ネットワーク", "依存サービス"))


def test_markdown_table_delimiters_have_consistent_spaces():
    import re
    report = MODULE.build_report(
        ROOT / "data" / "degraded.csv", ROOT / "config" / "thresholds.json",
        baseline_path=ROOT / "data" / "baseline.csv",
    )
    markdown = MODULE.render_markdown(report)
    regression = markdown_section(markdown, 4)
    assert "| p95_ms | 105.0 → 380.0 | 261.9%（変化率） | 20.0% | FAIL |  |" in regression
    for line in markdown.splitlines():
        if line.startswith("| "):
            delimiters = list(re.finditer(r"(?<!\\)\|", line))
            assert line.endswith(" |")
            for delimiter in delimiters:
                index = delimiter.start()
                if index > 0:
                    assert line[index - 1] == " "
                if index < len(line) - 1:
                    assert line[index + 1] == " "
