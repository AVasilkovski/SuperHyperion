import asyncio
import pytest
from src.epistemology.theory_change_operator import TheoryAction
from src.governance.fingerprinting import make_evidence_id
from src.graph.evidence_normalization import normalize_validation_evidence
from src.graph.nodes.govern_and_stage import govern_and_stage_node
from src.graph.state import create_initial_state
from src.hitl.intent_service import write_intent_service
from src.db.typedb_client import typedb

@pytest.fixture(autouse=True)
def setup_mock_db():
    """Ensure all integration tests run in mock mode for CI/CD parity."""
    typedb._mock_mode = True
    yield

@pytest.mark.asyncio
async def test_evidence_fingerprint_integrity():
    """Test 1: Check ID determinism for evidence fingerprints."""
    sid = "sess-test-001"
    cid = "claim-1"
    exid = "exec-42"
    qid = "stat-test@1.0.0"
    
    id1 = make_evidence_id(sid, cid, exid, qid)
    id2 = make_evidence_id(sid, cid, exid, qid)
    
    assert id1 == id2
    assert id1.startswith("ev-")
    assert len(id1) == 35

@pytest.mark.asyncio
async def test_proposal_generation_logic_revise():
    """Test 2: Ensure REVISE is computed when evidence is consistent."""
    state = create_initial_state("Is caffeine a stimulant?")
    state["graph_context"]["session_id"] = "sess-test-002"
    
    # Mock positive evidence
    state["evidence"] = [
        {
            "claim_id": "caffeine-stimulant",
            "execution_id": "ex-1",
            "template_qid": "bio-test@1.0.0",
            "role": "support",
            "confidence_score": 0.9,
            "success": True,
            "scope_lock_id": "sl1"
        },
        {
            "claim_id": "caffeine-stimulant",
            "execution_id": "ex-2",
            "template_qid": "bio-test@1.1.0",
            "role": "support",
            "confidence_score": 0.85,
            "success": True,
            "scope_lock_id": "sl1"
        }
    ]
    
    # Run the Constitutional Spine node
    await govern_and_stage_node(state)
    
    # Check if proposals were staged
    proposals = write_intent_service.list_staged()
    # Filter for our session
    session_props = [p for p in proposals if p["intent_type"] == "stage_epistemic_proposal" 
                     and p["payload"]["claim_id"] == "caffeine-stimulant"]
    
    assert len(session_props) == 1
    assert session_props[0]["payload"]["action"] == TheoryAction.REVISE.value

@pytest.mark.asyncio
async def test_channel_enforcement_rejection():
    """Test 3: Ensure invalid channel usage (negative support) is handled."""
    state = create_initial_state("Does water boil at 50C?")
    state["graph_context"]["session_id"] = "sess-test-003"
    
    state["graph_context"]["negative_evidence"] = [
        {
            "claim_id": "boil-50c",
            "execution_id": "ex-3",
            "template_qid": "therm-test@1.0.0",
            "role": "support",  # ILLEGAL for negative channel
            "confidence_score": 0.1
        }
    ]
    
    await govern_and_stage_node(state)
    pass


# =============================================================================
# Phase 16.4 Contract Tests
# =============================================================================

def test_normalization_maps_validator_keys():
    """Phase 16.4 E1-1: Normalization maps validator keys to steward contract."""
    # Simulates what validator_agent emits after __dict__ serialization
    validator_evidence = {
        "hypothesis_id": "claim-abc-123",
        "codeact_execution_id": 42,
        "execution_id": "",   
        "claim_id": None,     
        "template_id": "my-template",
        "success": True,
        "confidence_score": 0.9,
    }

    result = normalize_validation_evidence(
        validator_evidence,
        scope_lock_id="lock-xyz",
    )

    assert result["claim_id"] == "claim-abc-123"
    assert result["execution_id"] == "42"
    assert result["template_qid"] == "codeact_v1@1.0.0"
    assert result["scope_lock_id"] == "lock-xyz"


def test_normalization_does_not_overwrite_existing_keys():
    """Phase 16.4: Normalization must not clobber existing canonical keys."""
    evidence_already_normalized = {
        "claim_id": "explicit-claim",
        "execution_id": "explicit-exec",
        "template_qid": "custom-template@2.0.0",
        "scope_lock_id": "existing-lock",
        "hypothesis_id": "should-not-overwrite",
    }

    result = normalize_validation_evidence(
        evidence_already_normalized,
        scope_lock_id="different-lock",
    )

    assert result["claim_id"] == "explicit-claim"
    assert result["execution_id"] == "explicit-exec"
    assert result["template_qid"] == "custom-template@2.0.0"
    assert result["scope_lock_id"] == "existing-lock"


@pytest.mark.asyncio
async def test_integrate_fails_closed_without_governance():
    """Phase 16.4 E1-2: integrate_node returns HOLD when governance is None."""
    from src.graph.workflow_v21 import integrate_node

    state = create_initial_state("Test query")
    state["governance"] = None

    result = await integrate_node(state)

    assert result["grounded_response"] is not None
    assert result["grounded_response"]["status"] == "HOLD"
    assert "HOLD" in result["response"]


@pytest.mark.asyncio
async def test_integrate_fails_closed_on_hold():
    """Phase 16.4: integrate_node returns HOLD when governance status is HOLD."""
    from src.graph.workflow_v21 import integrate_node

    state = create_initial_state("Test query")
    state["governance"] = {
        "status": "HOLD",
        "hold_reason": "No evidence persisted",
        "persisted_evidence_ids": [],
        "intent_id": None,
    }

    result = await integrate_node(state)

    assert result["grounded_response"]["status"] == "HOLD"
    assert "No evidence persisted" in result["response"]


@pytest.mark.asyncio
async def test_integrate_includes_evidence_ids():
    """Phase 16.4 E1-3: Grounded claims include evidence_ids when STAGED."""
    from unittest.mock import patch

    from src.agents.integrator_agent import integrator_agent
    from src.graph.workflow_v21 import integrate_node

    state = create_initial_state("Test query")
    state["graph_context"]["session_id"] = "sess-integrate-test"

    # Set up governance as STAGED
    state["governance"] = {
        "status": "STAGED",
        "persisted_evidence_ids": ["ev-abc123", "ev-def456"],
        "intent_id": "intent-001",
        "proposal_id": "prop-001",
        "session_id": "sess-test-ev",
        "scope_lock_id": "lock-001",
    }

    # Set up evidence with minted evidence_ids (from steward B2)
    state["graph_context"]["evidence"] = [
        {
            "claim_id": "test-claim-1",
            "hypothesis_id": "test-claim-1",
            "success": True,
            "evidence_id": "ev-abc123",
            "execution_id": "exec-1",
            "scope_lock_id": "sl1",
            "template_qid": "tpl@1.0.0"
        },
        {
            "claim_id": "test-claim-1",
            "hypothesis_id": "test-claim-1",
            "success": True,
            "evidence_id": "ev-def456",
            "execution_id": "exec-2",
            "scope_lock_id": "sl1",
            "template_qid": "tpl@1.0.0"
        },
    ]
    state["evidence"] = state["graph_context"]["evidence"]

    # Set up atomic claims
    state["graph_context"]["atomic_claims"] = [
        {"claim_id": "test-claim-1", "content": "Test claim content"},
    ]
    state["atomic_claims"] = state["graph_context"]["atomic_claims"]

    # Phase 16.5: Mock primacy query to return matching evidence
    mock_db_rows = [
        {"id": "ev-abc123", "claim": "test-claim-1", "scope": "lock-001"},
        {"id": "ev-def456", "claim": "test-claim-1", "scope": "lock-001"},
    ]

    with patch.object(integrator_agent, "query_graph", return_value=mock_db_rows):
        result = await integrate_node(state)

    # Should NOT be HOLD (mock bypass should trigger)
    assert "HOLD" not in (result.get("response") or "")

    # Grounded response should include evidence_ids
    grounded = result["grounded_response"]
    assert grounded is not None
    assert len(grounded["claims"]) == 1
    assert grounded["claims"][0]["evidence_ids"] == ["ev-abc123", "ev-def456"]
    assert grounded["governance"]["cited_intent_id"] == "intent-001"
    assert grounded["governance"]["cited_proposal_id"] == "prop-001"

if __name__ == "__main__":
    asyncio.run(test_evidence_fingerprint_integrity())
    asyncio.run(test_proposal_generation_logic_revise())
    test_normalization_maps_validator_keys()
    test_normalization_does_not_overwrite_existing_keys()
    asyncio.run(test_integrate_fails_closed_without_governance())
    asyncio.run(test_integrate_fails_closed_on_hold())
    asyncio.run(test_integrate_includes_evidence_ids())
