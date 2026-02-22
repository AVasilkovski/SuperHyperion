#!/usr/bin/env python3
"""Diff two OPS-1.3 trust gate summary artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_diff(base: dict[str, Any], head: dict[str, Any]) -> dict[str, Any]:
    base_commit = base.get("commit_gate") or {}
    head_commit = head.get("commit_gate") or {}
    base_hold = base.get("hold_gate") or {}
    head_hold = head.get("hold_gate") or {}

    return {
        "contract_version": "v1",
        "base_bundle_root": base.get("bundle_root"),
        "head_bundle_root": head.get("bundle_root"),
        "run_prefixes": sorted(
            set((base.get("run_prefixes") or []) + (head.get("run_prefixes") or []))
        ),
        "commit_gate": {
            "pass_changed": bool(base_commit.get("pass") != head_commit.get("pass")),
            "base_pass": base_commit.get("pass"),
            "head_pass": head_commit.get("pass"),
            "replay_status_changed": bool(
                base_commit.get("replay_status") != head_commit.get("replay_status")
            ),
            "base_replay_status": base_commit.get("replay_status"),
            "head_replay_status": head_commit.get("replay_status"),
            "duration_ms_delta": _delta(
                base_commit.get("duration_ms"), head_commit.get("duration_ms")
            ),
        },
        "hold_gate": {
            "pass_changed": bool(base_hold.get("pass") != head_hold.get("pass")),
            "base_pass": base_hold.get("pass"),
            "head_pass": head_hold.get("pass"),
            "hold_code_changed": bool(base_hold.get("hold_code") != head_hold.get("hold_code")),
            "base_hold_code": base_hold.get("hold_code"),
            "head_hold_code": head_hold.get("hold_code"),
            "duration_ms_delta": _delta(base_hold.get("duration_ms"), head_hold.get("duration_ms")),
        },
    }


def _delta(base_value: Any, head_value: Any) -> int | None:
    if base_value is None or head_value is None:
        return None
    try:
        return int(head_value) - int(base_value)
    except Exception:
        return None


def build_step_lines(diff: dict[str, Any]) -> list[str]:
    commit = diff["commit_gate"]
    hold = diff["hold_gate"]
    return [
        "## OPS-1.3 Trust Gate Delta",
        (
            f"- COMMIT changed={commit['pass_changed']}"
            f" | replay_changed={commit['replay_status_changed']}"
            f" | duration_delta_ms={commit['duration_ms_delta']}"
        ),
        (
            f"- HOLD changed={hold['pass_changed']}"
            f" | hold_code_changed={hold['hold_code_changed']}"
            f" | duration_delta_ms={hold['duration_ms_delta']}"
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="OPS-1.3 trust gate summary diff")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    payload = build_diff(_read(args.base), _read(args.head))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
