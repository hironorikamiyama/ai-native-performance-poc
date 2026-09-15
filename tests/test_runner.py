import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_scenario.py"
SPEC = importlib.util.spec_from_file_location("run_scenario", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_baseline_and_regression_are_comparable() -> None:
    plan = MODULE.load_plan(ROOT / "config" / "test_plan.json")
    baseline = MODULE.workload_signature(plan["scenarios"]["baseline"])
    regression = MODULE.workload_signature(plan["scenarios"]["regression"])
    assert baseline == regression


def test_build_command_uses_configured_output_and_load() -> None:
    plan = MODULE.load_plan(
        ROOT / "config" / "test_plan.json"
    )
    command = MODULE.build_command(
        plan,
        "baseline",
        Path("results/run/locust"),
    )

    assert command[:3] == [
        sys.executable,
        "-m",
        "locust",
    ]
    assert (
        command[command.index("--exit-code-on-error") + 1]
        == "0"
    )
    assert command[command.index("-u") + 1] == "50"
    assert (
        command[command.index("--csv") + 1]
        == "results/run/locust"
    )


def test_manifest_records_stats_reset_configuration() -> None:
    plan_path = ROOT / "config" / "test_plan.json"
    policy_path = ROOT / "config" / "thresholds.json"
    plan = MODULE.load_plan(plan_path)

    command = MODULE.build_command(
        plan,
        "baseline",
        Path("results/run/locust"),
    )
    manifest = MODULE.create_manifest(
        plan,
        "baseline",
        command,
        plan_path,
        policy_path,
        warmup_seconds=10.0,
    )

    assert manifest["schema_version"] == "1.1"
    assert (
        manifest["evaluation"]["policy_file"]
        == "config/thresholds.json"
    )
    assert (
        manifest["evaluation"]["warmup_seconds"]
        == 10.0
    )
    assert (
        manifest["evaluation"]["stats_reset_mode"]
        == "locust_reset_all"
    )
    assert manifest["evaluation"]["policy_sha256"]
