"""
Phase 16.5 — Coherence & Primacy Integration Tests

Red-team regression tests that lock the governance coherence filter
and ledger primacy verifier. These prevent regression into "sticker mode"
where fake/mismatched evidence IDs can pass through to synthesis.

Tests mock the TypeDB query layer (query_fetch) to simulate ledger
responses without requiring a live database.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.graph.state import create_initial_state
from src.hitl.intent_service import IntentStatus, WriteIntent

# =============================================================================
# Helpers
# =============================================================================

def _make_staged_intent(
    intent_id: str = "intent-test-001",
    proposal_id: str = "prop-test-001",
    scope_lock_id: str = "scope-lock-001",
    evidence_ids: list = None,
    claim_id: str = "claim-1",
) -> dict:
    """Build a dict matching InMemoryIntentStore's shape."""
    return {
        "intent_id": intent_id,
        "intent_type": "stage_epistemic_proposal",
        "lane": "grounded",
        "payload": {
            "action": "REVISE",
            "claim_id": claim_id,
            "evidence_ids": evidence_ids or ["ev-real-001", "ev-real-002"],
            "conflict_score": 0.5,
            "rationale": "test rationale",
        },
        "impact_score": 0.5,
        "status": "staged",
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(days=7),
        "scope_lock_id": scope_lock_id,
        "supersedes_intent_id": None,
        "proposal_id": proposal_id,
    }


def _make_write_intent_from_dict(d: dict) -> WriteIntent:
    """Reconstruct a WriteIntent object from a store dict."""
    return WriteIntent(
        intent_id=d["intent_id"],
        intent_type=d["intent_type"],
        lane=d.get("lane", "grounded"),
        payload=d.get("payload", {}),
        impact_score=d.get("impact_score", 0.0),
        status=IntentStatus(d["status"]),
        created_at=d["created_at"],
        expires_at=d.get("expires_at"),
        scope_lock_id=d.get("scope_lock_id"),
        supersedes_intent_id=d.get("supersedes_intent_id"),
        proposal_id=d.get("proposal_id"),
    )


def _make_governance_state(
    evidence_ids: list,
    intent_id: str = "intent-test-001",
    proposal_id: str = "prop-test-001",
    scope_lock_id: str = "scope-lock-001",
    session_id: str = "sess-test-100",
    status: str = "STAGED",
):
    """Build a governance dict as produced by governance_gate_node."""
    return {
        "status": status,
        "lane": "grounded",
        "session_id": session_id,
        "persisted_evidence_ids": evidence_ids,
        "intent_id": intent_id,
        "proposal_id": proposal_id,
        "scope_lock_id": scope_lock_id,
        "hold_code": None,
        "hold_reason": None,
    }


def _mock_db_rows(evidence_ids, claim_id="claim-1", scope_lock_id="scope-lock-001"):
    """Build TypeDB-style result rows for mocked query_fetch."""
    return [
        {"id": eid, "claim": claim_id, "scope": scope_lock_id}
        for eid in evidence_ids
    ]


# =============================================================================
# Test 1: Integrator holds on fake evidence ID
# =============================================================================

@pytest.mark.asyncio
async def test_integrator_holds_on_fake_evidence_id():
    """
    Red-team: Inject ev-fake999 into persisted_evidence_ids.
    Gate may STAGE (internal coherence can pass if intent is rigged too),
    but Integrator MUST HOLD with EVIDENCE_MISSING_FROM_LEDGER because
    the ledger doesn't have ev-fake999.
    """
    from src.agents.integrator_agent import integrator_agent
    from src.graph.workflow_v21 import integrate_node

    real_ids = ["ev-real-001", "ev-real-002"]
    fake_id = "ev-fake999"
    all_ids = real_ids + [fake_id]

    state = create_initial_state("Test query — fake evidence")
    state["governance"] = _make_governance_state(
        evidence_ids=all_ids,
        status="STAGED",
    )
    state["graph_context"]["atomic_claims"] = [
        {"claim_id": "claim-1", "content": "Test claim"},
    ]

    # Mock TypeDB to return only real IDs (fake is missing from ledger)
    with patch.object(
        integrator_agent, "query_graph",
        return_value=_mock_db_rows(real_ids),
    ):
        result = await integrate_node(state)

    assert result["grounded_response"]["status"] == "HOLD"
    assert result["grounded_response"]["hold_code"] == "EVIDENCE_MISSING_FROM_LEDGER"
    assert fake_id in result["grounded_response"]["details"]["missing"]
    assert result["speculative_alternatives"] == []


# =============================================================================
# Test 2: Governance gate holds on evidence set mismatch
# =============================================================================

@pytest.mark.asyncio
async def test_governance_gate_holds_on_intent_evidence_set_mismatch():
    """
    Intent payload evidence_ids ≠ state persisted_evidence_ids.
    Gate MUST HOLD with EVIDENCE_SET_MISMATCH.
    """
    from src.graph.nodes.governance_gate import governance_gate_node

    state = create_initial_state("Test query — evidence mismatch")

    # State has IDs A,B — intent has IDs A,C
    state["graph_context"]["persisted_all_evidence_ids"] = ["ev-aaa", "ev-bbb"]
    state["graph_context"]["latest_staged_intent_id"] = "intent-mismatch-001"
    state["graph_context"]["latest_staged_proposal_id"] = "prop-mismatch-001"
    state["graph_context"]["proposal_generation_error"] = None

    # Build a mismatched intent (different evidence set)
    mismatched_intent = _make_staged_intent(
        intent_id="intent-mismatch-001",
        proposal_id="prop-mismatch-001",
        evidence_ids=["ev-aaa", "ev-ccc"],  # ev-ccc ≠ ev-bbb
    )
    mock_intent = _make_write_intent_from_dict(mismatched_intent)

    # Patch the global write_intent_service singleton (lazy import inside gate reads this)
    mock_svc = MagicMock()
    mock_svc.get.return_value = mock_intent

    with patch("src.hitl.intent_service.write_intent_service", mock_svc):
        result = await governance_gate_node(state)

    gov = result["governance"]
    assert gov["status"] == "HOLD"
    assert gov["hold_code"] == "EVIDENCE_SET_MISMATCH"
    assert "only_in_intent" in gov["hold_reason"] or "only_in_state" in gov["hold_reason"]


# =============================================================================
# Test 3: Integrator holds on scope mismatch
# =============================================================================

@pytest.mark.asyncio
async def test_integrator_holds_on_scope_mismatch():
    """
    Evidence exists but scope-lock-id differs from expected.
    Integrator MUST HOLD with EVIDENCE_SCOPE_MISMATCH.
    """
    from src.agents.integrator_agent import integrator_agent
    from src.graph.workflow_v21 import integrate_node

    evidence_ids = ["ev-scope-001", "ev-scope-002"]

    state = create_initial_state("Test query — scope mismatch")
    state["governance"] = _make_governance_state(
        evidence_ids=evidence_ids,
        scope_lock_id="scope-lock-EXPECTED",
        status="STAGED",
    )
    state["graph_context"]["atomic_claims"] = [
        {"claim_id": "claim-1", "content": "Test claim"},
    ]

    # Mock TypeDB: evidence exists but has WRONG scope
    wrong_scope_rows = _mock_db_rows(
        evidence_ids,
        scope_lock_id="scope-lock-WRONG",  # Different from expected
    )

    with patch.object(
        integrator_agent, "query_graph",
        return_value=wrong_scope_rows,
    ):
        result = await integrate_node(state)

    assert result["grounded_response"]["status"] == "HOLD"
    assert result["grounded_response"]["hold_code"] == "EVIDENCE_SCOPE_MISMATCH"
    assert "scope-lock-EXPECTED" in str(result["grounded_response"]["details"])
    assert result["speculative_alternatives"] == []


# =============================================================================
# Test 4: Integrator holds on claim mismatch
# =============================================================================

@pytest.mark.asyncio
async def test_integrator_holds_on_claim_mismatch():
    """
    Evidence exists but claim-id doesn't match the claim being synthesized.
    Integrator MUST HOLD with EVIDENCE_CLAIM_MISMATCH.
    """
    from src.agents.integrator_agent import integrator_agent
    from src.graph.workflow_v21 import integrate_node

    evidence_ids = ["ev-claim-001", "ev-claim-002"]

    state = create_initial_state("Test query — claim mismatch")
    state["governance"] = _make_governance_state(
        evidence_ids=evidence_ids,
        status="STAGED",
    )
    # Synthesis expects claim "expected-claim" but evidence cites "wrong-claim"
    state["graph_context"]["atomic_claims"] = [
        {"claim_id": "expected-claim", "content": "The expected claim"},
    ]

    # Mock TypeDB: evidence cites wrong claim
    wrong_claim_rows = _mock_db_rows(
        evidence_ids,
        claim_id="wrong-claim",  # Different from expected
    )

    with patch.object(
        integrator_agent, "query_graph",
        return_value=wrong_claim_rows,
    ):
        result = await integrate_node(state)

    assert result["grounded_response"]["status"] == "HOLD"
    assert result["grounded_response"]["hold_code"] == "EVIDENCE_CLAIM_MISMATCH"
    assert "expected-claim" in str(result["grounded_response"]["details"].get("expected_claims", []))
    assert result["speculative_alternatives"] == []


# =============================================================================
# Main runner
# =============================================================================

if __name__ == "__main__":
    asyncio.run(test_integrator_holds_on_fake_evidence_id())
    asyncio.run(test_governance_gate_holds_on_intent_evidence_set_mismatch())
    asyncio.run(test_integrator_holds_on_scope_mismatch())
    asyncio.run(test_integrator_holds_on_claim_mismatch())
    print("All Phase 16.5 coherence & primacy tests passed.")
