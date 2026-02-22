from __future__ import annotations

from src.sdk.explainability import (
    ExplainabilitySummaryV1,
    build_explainability_summary,
    parse_explainability_summary,
)


def test_explainability_v1_1_narrative_is_deterministic():
    governance = {
        "status": "HOLD",
        "session_id": "s1",
        "persisted_evidence_ids": [],
        "mutation_ids": [],
        "hold_code": "NO_EVIDENCE_PERSISTED",
        "hold_reason": "No evidence",
        "gate_code": "NO_EVIDENCE_PERSISTED",
        "failure_reason": "No evidence",
        "duration_ms": 0,
        "source_refs": {"governance_summary_file": "g.json"},
    }
    summary = build_explainability_summary(governance).model_dump()
    assert summary["contract_version"] == "v1.1"
    assert summary["why_hold"] == "Hold enforced by code NO_EVIDENCE_PERSISTED: No evidence."
    assert summary["blocking_checks"] == [
        "governance_status:HOLD",
        "hold_code:NO_EVIDENCE_PERSISTED",
        "hash_integrity",
        "primacy",
        "mutation_linkage",
    ]


def test_parser_accepts_v1_payload():
    payload_v1 = {
        "contract_version": "v1",
        "capsule_id": None,
        "tenant_id": "x",
        "status": "HOLD",
        "hold": {"hold_code": None, "hold_reason": None},
        "source_refs": {
            "governance_summary_file": "a.json",
            "replay_verdict_file": None,
            "capsule_manifest_file": None,
        },
        "governance_gate": {
            "status": "HOLD",
            "gate_code": "X",
            "duration_ms": 0,
            "failure_reason": None,
        },
        "governance_checks": {
            "hash_integrity": {"ok": False},
            "primacy": {"ok": False, "code": "FAIL"},
            "mutation_linkage": {"ok": False, "missing": []},
        },
        "evidence": {
            "persisted_ids": [],
            "mutation_ids": [],
            "intent_id": None,
            "proposal_id": None,
        },
        "lineage": {"session_id": None, "scope_lock_id": None, "query_hash": None},
    }
    parsed = parse_explainability_summary(payload_v1)
    assert isinstance(parsed, ExplainabilitySummaryV1)
