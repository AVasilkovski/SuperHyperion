

import pytest

from src.agents.base_agent import AgentContext
from src.agents.ontology_steward import OntologySteward
from src.db.typedb_client import TypeDBConnection


class MockTypeDB(TypeDBConnection):
    def __init__(self):
        super().__init__()
        self.inserts = []
        self.deletes = []
        self._mock_mode = True

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
async def test_v22_end_to_end_persistence(steward, mock_db):
    """
    Test a full session persistence cycle ensuring all v2.2 artifacts 
    generate correct TypeQL queries.
    """
    # Setup context with one of each artifact
    context = AgentContext(
        graph_context={
            "session_id": "sess-integration-test",
            "user_query": "Does X cause Y?",
            "traces": [
                {
                    "step_index": 1,
                    "node": "verify",
                    "phase": "execution",
                    "agent_id": "ValidatorAgent.A",
                    "output": "Simulating...",
                    "timestamp": "2023-01-01T00:00:00"
                }
            ],
            "template_executions": [
                {
                    "execution_id": "exec-001",
                    "template_id": "bootstrap_ci",
                    "claim_id": "claim-alpha",
                    "success": True,
                    "runtime_ms": 150,
                    "params": {"n": 100},
                    "result": {"mean": 0.5}
                }
            ],
            "epistemic_update_proposal": [
                {
                    "claim_id": "claim-alpha",
                    "proposed_status": "supported",
                    "final_proposed_status": "supported",
                    "confidence_score": 0.85,
                    "cap_reasons": [],
                    "requires_hitl": False
                }
            ],
            "write_intents": [
                {
                    "intent_id": "intent-1",
                    "intent_type": "update_epistemic_status",
                    "payload": {"claim_id": "claim-alpha", "status": "supported"}
                }
            ],
            "approved_write_intents": [
                {
                    "intent_id": "intent-1",
                    "intent_type": "update_epistemic_status",
                    "payload": {"claim_id": "claim-alpha", "status": "supported"}
                }
            ]
        }
    )

    # Run Steward
    await steward.run(context)

    # Assertions
    inserts_str = "\n".join(mock_db.inserts)
    deletes_str = "\n".join(mock_db.deletes)

    # 1. Session
    assert 'isa run-session' in inserts_str
    assert 'has session-id "sess-integration-test"' in inserts_str
    assert 'has run-status "running"' in inserts_str
    # Check session completion update (separate insert/delete)
    assert 'insert $s has ended-at' in inserts_str
    assert 'delete has $old of $s' in deletes_str
    assert 'insert $s has run-status "complete"' in inserts_str

    # 2. Trace
    assert 'isa trace-entry' in inserts_str
    assert 'has node-name "verify"' in inserts_str
    assert 'isa session-has-trace' in inserts_str

    # 3. Execution
    assert 'isa template-execution' in inserts_str
    assert 'has execution-id "exec-001"' in inserts_str
    assert 'has template-id "bootstrap_ci"' in inserts_str
    assert 'has params-hash' in inserts_str
    assert 'has result-hash' in inserts_str
    assert 'isa session-has-execution' in inserts_str

    # 4. Proposal
    assert 'isa epistemic-proposal' in inserts_str
    assert 'has final-proposed-status "supported"' in inserts_str
    assert 'isa session-has-epistemic-proposal' in inserts_str
    # Check Linking
    assert 'isa proposal-targets-proposition' in inserts_str
    assert 'has entity-id "claim-alpha"' in inserts_str

    # 5. Write Intent
    assert 'isa write-intent' in inserts_str
    assert 'has intent-id "intent-1"' in inserts_str
    assert 'has intent-status "approved"' in inserts_str
    assert 'isa session-has-write-intent' in inserts_str

    # 6. Intent Execution (Mutation)
    # Check separate delete and insert queries
    assert 'delete has $old of $c' in deletes_str
    # Check insert contains the new status
    assert 'insert $c has epistemic-status "supported"' in inserts_str

    # 7. Intent Status Event
    assert 'isa intent-status-event' in inserts_str
    assert 'has intent-status "executed"' in inserts_str
    assert 'isa intent-has-status-event' in inserts_str
