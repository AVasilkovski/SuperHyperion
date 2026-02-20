#!/usr/bin/env python3
"""OPS-1.3 trust-gate per-run summary artifact."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_gate_dir(path: Path) -> dict[str, Any]:
    gov_files = sorted(path.glob("*_governance_summary.json"))
    rep_files = sorted(path.glob("*_replay_verify_verdict.json"))
    manifest_files = sorted(path.glob("*_run_capsule_manifest.json"))

    governance = _read_json(gov_files[0]) if gov_files else None
    replay = _read_json(rep_files[0]) if rep_files else None
    manifest = _read_json(manifest_files[0]) if manifest_files else None

    return {
        "governance": governance,
        "replay": replay,
        "manifest": manifest,
        "capsule_id": (manifest or {}).get("capsule_id"),
        "duration_ms": (governance or {}).get("duration_ms"),
        "status": (governance or {}).get("status"),
        "hold_code": (governance or {}).get("hold_code"),
        "replay_status": (replay or {}).get("status"),
    }


def build_summary(in_dir: str) -> dict[str, Any]:
    root = Path(in_dir)
    commit = _load_gate_dir(root / "commit")
    hold = _load_gate_dir(root / "hold")

    commit_pass = bool(commit["status"] == "STAGED" and commit["capsule_id"] and commit["replay_status"] == "PASS")
    hold_pass = bool(hold["status"] == "HOLD" and hold["capsule_id"] is None and hold["hold_code"] is not None)

    hold_code_distribution = []
    if hold["hold_code"] is not None:
        hold_code_distribution.append({"hold_code": str(hold["hold_code"]), "count": 1})

    summary = {
        "contract_version": "v1",
        "bundle_root": str(root),
        "run_prefixes": ["commit", "hold"],
        "timestamp_utc": os.environ.get("GITHUB_RUN_CREATED_AT"),
        "git_sha": os.environ.get("GITHUB_SHA"),
        "commit_gate": {
            "pass": commit_pass,
            "governance_status": commit["status"],
            "capsule_id": commit["capsule_id"],
            "replay_status": commit["replay_status"],
            "duration_ms": commit["duration_ms"],
        },
        "hold_gate": {
            "pass": hold_pass,
            "governance_status": hold["status"],
            "hold_code": hold["hold_code"],
            "capsule_id": hold["capsule_id"],
            "duration_ms": hold["duration_ms"],
            "hold_code_distribution": hold_code_distribution,
        },
    }
    return summary


def build_step_summary_lines(summary: dict[str, Any]) -> list[str]:
    commit = summary["commit_gate"]
    hold = summary["hold_gate"]
    return [
        "## OPS-1.3 Trust Gate Summary",
        (
            f"- COMMIT gate: {'PASS' if commit['pass'] else 'FAIL'}"
            f" | capsule_id={commit['capsule_id']}"
            f" | replay={commit['replay_status']}"
            f" | ms={commit['duration_ms']}"
        ),
        (
            f"- HOLD gate: {'PASS' if hold['pass'] else 'FAIL'}"
            f" | hold_code={hold['hold_code']}"
            f" | capsule_id={hold['capsule_id']}"
            f" | ms={hold['duration_ms']}"
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="OPS-1.3 trust gate summary")
    parser.add_argument("--in-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    summary = build_summary(args.in_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)

    print(json.dumps(summary, indent=2, sort_keys=True))

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        lines = build_step_summary_lines(summary)
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
