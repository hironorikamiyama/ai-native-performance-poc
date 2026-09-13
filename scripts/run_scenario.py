#!/usr/bin/env python3
"""Run one configured Locust scenario and write a reproducible run manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_plan(path: Path) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan["tool"]["name"] != "Locust":
        raise ValueError("This runner currently supports Locust only")
    return plan


def workload_signature(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "users": scenario["users"],
        "spawn_rate": scenario["spawn_rate"],
        "duration": scenario["duration"],
        "task_profile": scenario["task_profile"],
    }


def build_command(plan: dict[str, Any], scenario_name: str, csv_prefix: Path) -> list[str]:
    try:
        scenario = plan["scenarios"][scenario_name]
    except KeyError as exc:
        raise ValueError(f"Unknown scenario: {scenario_name}") from exc
    return [
        sys.executable,
        "-m",
        "locust",
        "-f",
        plan["tool"]["scenario_file"],
        "--headless",
        "-u",
        str(scenario["users"]),
        "-r",
        str(scenario["spawn_rate"]),
        "-t",
        scenario["duration"],
        "--host",
        plan["target"]["base_url"],
        "--csv",
        str(csv_prefix),
    ]


def create_manifest(plan: dict[str, Any], scenario_name: str, command: list[str], plan_path: Path) -> dict[str, Any]:
    scenario = plan["scenarios"][scenario_name]
    return {
        "schema_version": "1.0",
        "run_id": None,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed_at_utc": None,
        "status": "PLANNED",
        "exit_code": None,
        "plan_id": plan["plan_id"],
        "assumption_status": plan["assumption_status"],
        "scenario_name": scenario_name,
        "scenario_purpose": scenario["purpose"],
        "tool": plan["tool"],
        "target": plan["target"],
        "workload_signature": workload_signature(scenario),
        "target_behavior": {
            "delay_ms": scenario["delay_ms"],
            "fail_rate": scenario["fail_rate"],
        },
        "output": plan["output"],
        "command": command,
        "test_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=("smoke", "baseline", "regression", "stress"))
    parser.add_argument("--plan", type=Path, default=ROOT / "config" / "test_plan.json")
    parser.add_argument("--run-id", help="Stable ID for CI or a human-readable test cycle")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    plan = load_plan(args.plan)
    run_id = args.run_id or f"{args.scenario}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = ROOT / "results" / "runs" / run_id
    csv_prefix = run_dir / "locust"
    command = build_command(plan, args.scenario, csv_prefix)
    manifest = create_manifest(plan, args.scenario, command, args.plan)
    manifest["run_id"] = run_id

    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return

    run_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    env = os.environ.copy()
    scenario = plan["scenarios"][args.scenario]
    env["POC_DELAY_MS"] = str(scenario["delay_ms"])
    env["POC_FAIL_RATE"] = str(scenario["fail_rate"])
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)

    manifest["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["exit_code"] = completed.returncode
    manifest["status"] = "COMPLETED" if completed.returncode == 0 else "FAILED"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    print(f"Run completed: {run_dir}")


if __name__ == "__main__":
    main()
