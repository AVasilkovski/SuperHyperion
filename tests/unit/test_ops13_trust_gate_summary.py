from __future__ import annotations

import json

from scripts.ops13_trust_gate_summary import build_step_summary_lines, build_summary


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def test_ops13_summary_builds_expected_structure(tmp_path):
    _write(
        tmp_path / "commit" / "run-1_governance_summary.json",
        {"status": "STAGED", "duration_ms": 5, "hold_code": None},
    )
    _write(tmp_path / "commit" / "run-1_run_capsule_manifest.json", {"capsule_id": "run-1"})
    _write(tmp_path / "commit" / "run-1_replay_verify_verdict.json", {"status": "PASS"})

    _write(
        tmp_path / "hold" / "run-2_governance_summary.json",
        {"status": "HOLD", "duration_ms": 0, "hold_code": "NO_EVIDENCE_PERSISTED"},
    )

    summary = build_summary(str(tmp_path))
    assert summary["commit_gate"]["pass"] is True
    assert summary["hold_gate"]["pass"] is True
    assert summary["hold_gate"]["hold_code"] == "NO_EVIDENCE_PERSISTED"
    assert summary["hold_gate"]["hold_code_distribution"] == [{"hold_code": "NO_EVIDENCE_PERSISTED", "count": 1}]
    assert summary["run_prefixes"] == ["commit", "hold"]


def test_ops13_step_summary_lines_include_capsule_and_replay(tmp_path):
    _write(tmp_path / "commit" / "run-1_governance_summary.json", {"status": "STAGED", "duration_ms": 7, "hold_code": None})
    _write(tmp_path / "commit" / "run-1_run_capsule_manifest.json", {"capsule_id": "run-1"})
    _write(tmp_path / "commit" / "run-1_replay_verify_verdict.json", {"status": "PASS"})
    _write(tmp_path / "hold" / "run-2_governance_summary.json", {"status": "HOLD", "duration_ms": 0, "hold_code": "NO_EVIDENCE_PERSISTED"})

    lines = build_step_summary_lines(build_summary(str(tmp_path)))
    assert "capsule_id=run-1" in lines[1]
    assert "replay=PASS" in lines[1]
    assert "hold_code=NO_EVIDENCE_PERSISTED" in lines[2]
