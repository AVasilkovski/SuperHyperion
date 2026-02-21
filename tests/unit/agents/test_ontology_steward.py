

import pytest

from src.agents.base_agent import AgentContext
from src.agents.ontology_steward import OntologySteward, iso_now


class MockTypeDB:
    def __init__(self):
        self.inserts = []
        self.deletes = []

    def query_insert(self, query, **kwargs):
        self.inserts.append(query)

    def query_delete(self, query, **kwargs):
        self.deletes.append(query)

    def connect(self):
        return True

@pytest.fixture
def mock_db():
    return MockTypeDB()

@pytest.fixture
def steward(mock_db):
    steward = OntologySteward()
    steward.db = mock_db
    return steward

@pytest.mark.asyncio
async def test_persist_session_traces(steward, mock_db):
    context = AgentContext(
        graph_context={
            "session_id": "sess-123",
            "traces": [
                {
                    "step": 1,
                    "node": "verify",
                    "output": "some result",
                    "summary": "some result",
                    "timestamp": "2023-01-01T00:00:00"
                }
            ]
        }
    )

    await steward.run(context)

    # Check session insert
    assert any('has session-id "sess-123"' in q for q in mock_db.inserts)

    # Check trace insert
    assert any('has node-name "verify"' in q for q in mock_db.inserts)
    assert any('has trace-summary "some result"' in q for q in mock_db.inserts)
    assert any('isa trace-entry' in q for q in mock_db.inserts)

@pytest.mark.asyncio
async def test_persist_execution(steward, mock_db):
    execution = {
        "execution_id": "exec-1",
        "template_id": "template_a",
        "params": {"p": 1},
        "result": {"val": 42},
        "success": True
    }

    context = AgentContext(
        graph_context={
            "session_id": "sess-123",
            "template_executions": [execution]
        }
    )

    await steward.run(context)

    # Check execution insert
    insert = next((q for q in mock_db.inserts if 'isa template-execution' in q), None)
    assert insert is not None
    assert 'has execution-id "exec-1"' in insert
    assert 'has template-id "template_a"' in insert
    assert 'has success true' in insert

@pytest.mark.asyncio
async def test_persist_proposal(steward, mock_db):
    proposal = {
        "claim_id": "claim-1",
        "final_proposed_status": "speculative",
        "confidence_score": 0.8,
        "cap_reasons": ["fragile"]
    }

    context = AgentContext(
        graph_context={
            "session_id": "sess-123",
            "epistemic_update_proposal": [proposal]
        }
    )

    await steward.run(context)

    # Check proposal insert
    insert = next((q for q in mock_db.inserts if 'isa epistemic-proposal' in q), None)
    assert insert is not None
    assert 'has final-proposed-status "speculative"' in insert
    assert 'has confidence-score 0.8' in insert
    assert 'has cap-reason' in insert
    assert 'has cap-reason' in insert
    assert 'isa proposal-targets-proposition' in insert

@pytest.mark.asyncio
async def test_execute_intent(steward, mock_db):
    intent = {
        "intent_type": "update_epistemic_status",
        "payload": {
            "claim_id": "claim-1",
            "status": "supported"
        }
    }

    context = AgentContext(
        graph_context={
            "session_id": "sess-123",
            "approved_write_intents": [intent]
        }
    )

    await steward.run(context)

    # Check execution success
    committed = context.graph_context.get("committed_intents", [])
    assert len(committed) == 1
    assert committed[0] == intent

    write_results = context.graph_context.get("steward_write_results", [])
    assert len(write_results) == 1
    assert write_results[0]["contract_version"] == "v1"
    assert write_results[0]["status"] == "executed"
    assert write_results[0]["duration_ms"] >= 0
    assert write_results[0]["idempotency_key"].startswith("iw-")

    # Check DB operations
    assert len(mock_db.deletes) >= 1
    # Find the specific delete for epistemic status
    delete_q = next((q for q in mock_db.deletes if 'delete has $old of $c' in q), None)
    assert delete_q is not None

    # Check insert (should be in inserts list)
    insert_q = next((q for q in mock_db.inserts if 'insert $c has epistemic-status' in q), None)
    assert insert_q is not None
    assert 'supported' in insert_q


# ============================================================================
# Phase 11 Regression Guards (bypass closures)
# ============================================================================

def test_v22_p11_guard_json_string_speculative():
    """Guard catches speculative marker hidden in JSON string (bypass closure)."""
    from src.agents.ontology_steward import q_insert_validation_evidence

    ev = {
        "claim_id": "claim-1",
        "execution_id": "exec-1",
        "template_id": "bootstrap_ci",
        "template_qid": "bootstrap_ci@v1",
        "scope_lock_id": "lock-1",
        "success": True,
        "confidence_score": 0.9,
        # bypass attempt: speculative marker hidden in JSON string
        "json": '{"some":"data","epistemic_status":"speculative"}',
    }

    with pytest.raises(ValueError, match="CRITICAL: Attempted to persist speculative evidence"):
        q_insert_validation_evidence("sess-1", ev)


def test_v22_p11_guard_json_string_kebab_speculative():
    """Guard catches kebab-case speculative marker hidden in JSON string."""
    from src.agents.ontology_steward import q_insert_validation_evidence

    ev = {
        "claim_id": "claim-2",
        "execution_id": "exec-2",
        "template_id": "bootstrap_ci",
        "template_qid": "bootstrap_ci@v1",
        "scope_lock_id": "lock-2",
        "success": True,
        "confidence_score": 0.9,
        # kebab-case variant in string
        "content": '{"epistemic-status":"speculative"}',
    }

    with pytest.raises(ValueError, match="CRITICAL: Attempted to persist speculative evidence"):
        q_insert_validation_evidence("sess-2", ev)


def test_v22_p11_claim_id_kebab_case_accepted():
    """Kebab-case claim-id is accepted (no missing claim_id error)."""
    from src.agents.ontology_steward import q_insert_validation_evidence

    ev = {
        "claim-id": "claim-kebab",
        "execution_id": "exec-3",
        "template_id": "bootstrap_ci",
        "template_qid": "bootstrap_ci@v1",
        "scope_lock_id": "lock-3",
        "success": True,
        "confidence_score": 0.9,
        "content": "ok",
        "json": {},
    }

    # Should not raise on missing claim_id (it is present via claim-id)
    q = q_insert_validation_evidence("sess-3", ev)
    assert 'has claim-id "claim-kebab"' in q


def test_v22_p11_missing_claim_id_does_not_fallback_to_entity_id():
    """Missing claim_id hard-fails even if entity_id exists (semantic correctness)."""
    from src.agents.ontology_steward import q_insert_validation_evidence

    ev = {
        "entity_id": "ev-should-not-be-used-as-claim",
        "execution_id": "exec-4",
        "template_id": "bootstrap_ci",
        "success": True,
        "confidence_score": 0.9,
        "content": "no claim id",
        "json": {},
    }

    with pytest.raises(ValueError, match="CRITICAL: Validation evidence missing claim_id"):
        q_insert_validation_evidence("sess-4", ev)


def test_iso_now_emits_timezone_naive_datetime_literal():
    literal = iso_now()
    assert "T" in literal
    assert "Z" not in literal
    assert "+" not in literal
