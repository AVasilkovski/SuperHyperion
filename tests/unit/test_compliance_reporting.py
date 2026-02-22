from __future__ import annotations

import json

from src.sdk.compliance import build_compliance_report, write_compliance_outputs


def _write(path, payload):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def test_compliance_reporting_deterministic_metrics(tmp_path):
    bundles = tmp_path / "bundles"
    bundles.mkdir()

    _write(
        bundles / "run-a_governance_summary.json",
        {
            "contract_version": "v1",
            "status": "STAGED",
            "session_id": "s1",
            "persisted_evidence_ids": ["ev-1"],
            "intent_id": "i1",
            "proposal_id": "p1",
            "mutation_ids": [],
            "scope_lock_id": "sl1",
            "hold_code": None,
            "hold_reason": None,
            "gate_code": "GOVERNANCE_STAGED",
            "failure_reason": None,
            "duration_ms": 10,
            "source_refs": {},
        },
    )
    _write(bundles / "run-a_run_capsule_manifest.json", {"capsule_id": "run-a"})
    _write(
        bundles / "run-a_replay_verify_verdict.json",
        {
            "contract_version": "v1",
            "status": "PASS",
            "reasons": [],
            "details": {},
            "source_refs": {},
        },
    )

    _write(
        bundles / "run-b_governance_summary.json",
        {
            "contract_version": "v1",
            "status": "HOLD",
            "session_id": "s2",
            "persisted_evidence_ids": [],
            "intent_id": None,
            "proposal_id": None,
            "mutation_ids": [],
            "scope_lock_id": None,
            "hold_code": "NO_EVIDENCE_PERSISTED",
            "hold_reason": "none",
            "gate_code": "NO_EVIDENCE_PERSISTED",
            "failure_reason": "none",
            "duration_ms": 30,
            "source_refs": {},
        },
    )

    report = build_compliance_report(str(bundles))
    assert report["total_runs"] == 2
    assert report["counts"]["COMMIT"] == 1
    assert report["counts"]["HOLD"] == 1
    assert report["replay"]["pass_rate"] == 1.0

    written = write_compliance_outputs(str(bundles), str(tmp_path / "out"), include_csv=True)
    assert any(p.endswith("compliance_report.json") for p in written)
    assert any(p.endswith("runs.csv") for p in written)
    assert any(p.endswith("hold_codes.csv") for p in written)
