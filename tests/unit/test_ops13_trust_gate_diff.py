from __future__ import annotations

from scripts.ops13_trust_gate_diff import build_diff, build_step_lines


def test_ops13_diff_detects_pass_hold_code_and_duration_changes():
    base = {
        "bundle_root": "ci_artifacts",
        "run_prefixes": ["commit", "hold"],
        "commit_gate": {"pass": True, "replay_status": "PASS", "duration_ms": 10},
        "hold_gate": {"pass": True, "hold_code": "NO_EVIDENCE_PERSISTED", "duration_ms": 0},
    }
    head = {
        "bundle_root": "ci_artifacts",
        "run_prefixes": ["commit", "hold"],
        "commit_gate": {"pass": False, "replay_status": "FAIL", "duration_ms": 12},
        "hold_gate": {"pass": True, "hold_code": "MISSING_SCOPE_LOCK", "duration_ms": 1},
    }

    diff = build_diff(base, head)
    assert diff["commit_gate"]["pass_changed"] is True
    assert diff["commit_gate"]["replay_status_changed"] is True
    assert diff["commit_gate"]["duration_ms_delta"] == 2

    assert diff["hold_gate"]["pass_changed"] is False
    assert diff["hold_gate"]["hold_code_changed"] is True
    assert diff["hold_gate"]["duration_ms_delta"] == 1

    lines = build_step_lines(diff)
    assert "COMMIT changed=True" in lines[1]
    assert "HOLD changed=False" in lines[2]
