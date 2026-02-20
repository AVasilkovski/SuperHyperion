from __future__ import annotations

import pytest

from src.sdk.explainability import ExplainabilitySummaryV1, build_explainability_summary


def test_explainability_governance_only_hold_is_deterministic():
    governance = {
        "contract_version": "v1",
        "status": "HOLD",
        "session_id": "sess-hold-1",
        "persisted_evidence_ids": ["ev-b", "ev-a"],
        "intent_id": None,
        "proposal_id": None,
        "mutation_ids": ["mut-b", "mut-a"],
        "scope_lock_id": None,
        "hold_code": "NO_EVIDENCE_PERSISTED",
        "hold_reason": "No evidence",
        "gate_code": "NO_EVIDENCE_PERSISTED",
        "failure_reason": "No evidence",
        "duration_ms": 0,
        "source_refs": {"governance_summary_file": "no-capsule-sess-hold-1_governance_summary.json"},
    }

    summary = build_explainability_summary(governance)
    dumped = summary.model_dump()

    assert dumped["status"] == "HOLD"
    assert dumped["capsule_id"] is None
    assert dumped["hold"]["hold_code"] == "NO_EVIDENCE_PERSISTED"
    assert dumped["evidence"]["persisted_ids"] == ["ev-a", "ev-b"]
    assert dumped["evidence"]["mutation_ids"] == ["mut-a", "mut-b"]
    assert dumped["source_refs"]["replay_verdict_file"] is None
    assert dumped["source_refs"]["capsule_manifest_file"] is None


def test_explainability_full_bundle_commit_is_deterministic():
    governance = {
        "contract_version": "v1",
        "status": "STAGED",
        "session_id": "sess-1",
        "persisted_evidence_ids": ["ev-2", "ev-1"],
        "intent_id": "int-1",
        "proposal_id": "prop-1",
        "mutation_ids": ["mut-2", "mut-1"],
        "scope_lock_id": "scope-1",
        "hold_code": None,
        "hold_reason": None,
        "gate_code": "GOVERNANCE_STAGED",
        "failure_reason": None,
        "duration_ms": 5,
        "source_refs": {
            "governance_summary_file": "run-1_governance_summary.json",
            "replay_verdict_file": "run-1_replay_verify_verdict.json",
            "capsule_manifest_file": "run-1_run_capsule_manifest.json",
        },
    }
    replay = {
        "contract_version": "v1",
        "status": "PASS",
        "reasons": [],
        "details": {
            "hash_integrity": {"expected": "abc", "computed": "abc"},
            "primacy": {"code": "PASS"},
            "mutation_linkage": {"missing": []},
        },
    }
    manifest = {"capsule_id": "run-1", "tenant_id": "acme", "query_hash": "q-hash"}

    summary = build_explainability_summary(governance, replay, manifest).model_dump()
    assert summary["status"] == "COMMIT"
    assert summary["capsule_id"] == "run-1"
    assert summary["tenant_id"] == "acme"
    assert summary["governance_checks"]["hash_integrity"]["ok"] is True
    assert summary["governance_checks"]["primacy"] == {"ok": True, "code": "PASS"}
    assert summary["lineage"]["query_hash"] == "q-hash"


def test_explainability_extra_fields_forbidden():
    with pytest.raises(Exception):
        ExplainabilitySummaryV1(contract_version="v1", tenant_id="x", status="HOLD", hold={"hold_code": None, "hold_reason": None}, source_refs={"governance_summary_file": "a"}, governance_gate={"status": "HOLD", "gate_code": "X", "duration_ms": 0, "failure_reason": None}, governance_checks={"hash_integrity": {"ok": False}, "primacy": {"ok": False, "code": "FAIL"}, "mutation_linkage": {"ok": False, "missing": []}}, evidence={"persisted_ids": [], "mutation_ids": [], "intent_id": None, "proposal_id": None}, lineage={"session_id": None, "scope_lock_id": None, "query_hash": None}, unexpected="boom")
