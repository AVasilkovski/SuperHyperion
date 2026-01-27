
import pytest
import re
from unittest.mock import MagicMock

from src.agents.verify_agent import VerifyAgent
from src.agents.ontology_steward import OntologySteward
from src.agents.base_agent import AgentContext
from src.db.typedb_client import TypeDBConnection

# ----------------------------
# Strict MockTypeDB
# ----------------------------
class StrictMockTypeDB(TypeDBConnection):
    def __init__(self):
        super().__init__()
        self.inserts = []
        self.deletes = []
        self.propositions = set()
        self._mock_mode = True

    def query_insert(self, query: str):
        self.inserts.append(query)

        # Track inserted propositions
        if "insert" in query and "isa proposition" in query and 'has entity-id "' in query:
            m = re.search(r'has entity-id "([^"]+)"', query)
            if m:
                self.propositions.add(m.group(1))

        # Enforce proposition existence when matching for links
        is_linking = ("isa evidence-for-proposition" in query) or ("isa proposal-targets-proposition" in query)
        if is_linking:
            m = re.search(r'isa proposition, has entity-id "([^"]+)"', query)
            if m and m.group(1) not in self.propositions:
                raise RuntimeError(f"Missing proposition violation: {m.group(1)} was not found. Current propositions: {self.propositions}")

    def query_delete(self, query: str):
        self.deletes.append(query)

    def connect(self):
        return True

# ----------------------------
# Helper Classes for Tests
# ----------------------------
class TestVerifyAgent(VerifyAgent):
    """
    Override _design_experiment_spec and registry execution deterministically.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # We need to simulate different scenarios via setup
        self.mock_runtime = 250
        self.mock_diagnostics = {"toy_ok": True, "ess": 500}
        self.mock_template_id = "bootstrap_ci"

    async def _design_experiment_spec(self, claim, context):
        # Minimal spec: choose an MC template to exercise strict diagnostics rules
        from src.montecarlo.types import ExperimentSpec
        return ExperimentSpec(
            claim_id=claim["claim_id"],
            hypothesis=f"Verify: {claim['content']}",
            template_id=self.mock_template_id,
            params={"n_runs": 1000, "data": [1,2,3,4,5]},
            units={"estimate": "unit"},
            assumptions={"independence_assumed": True},
        )

    def _codeact_execute_template(self, spec, context):
        # Return a deterministic TemplateExecution-like object
        # Must match your TemplateExecution shape
        from src.montecarlo.templates import TemplateExecution
        return TemplateExecution(
            execution_id=f"exec-{spec.claim_id}",
            template_id=spec.template_id,
            claim_id=spec.claim_id,
            params=spec.params,
            result={
                "estimate": 1.23,
                "ci_low": 1.0,
                "ci_high": 1.5,
                "variance": 0.02,
                "diagnostics": self.mock_diagnostics,
                "sensitivity": {"prior_widened_flips": False, "noise_model_flips": False},
                "consistent": True
            },
            success=True,
            runtime_ms=self.mock_runtime,   
            warnings=[]
        )

class TestOntologySteward(OntologySteward):
    def __init__(self, db):
        super().__init__()
        self.db = db

    def insert_to_graph(self, query: str):
        self.db.query_insert(query)

# ----------------------------
# Test Cases
# ----------------------------

@pytest.mark.asyncio
async def test_v22_e2e_verify_to_steward_happy():
    """Happy path: Verify runs, passes checks, Steward persists linked evidence."""
    db = StrictMockTypeDB()

    # 1) Seed the proposition (hard dependency for evidence/proposal links)
    seed_prop = '''
    insert $p isa proposition, has entity-id "claim-e2e-1";
    '''
    db.query_insert(seed_prop)

    # 2) Run Verify
    verify = TestVerifyAgent(max_budget_ms=30_000)
    context = AgentContext(graph_context={
        "session_id": "sess-e2e",
        "user_query": "E2E test query",
        "atomic_claims": [{"claim_id": "claim-e2e-1", "content": "Drug X reduces biomarker Y"}],
    })

    context = await verify.run(context)

    # VerifyAgent contract checks
    assert context.graph_context.get("template_executions"), "Verify did not produce template_executions"
    assert context.graph_context.get("is_fragile") is not None, "Verify did not populate is_fragile scalar"
    assert context.graph_context.get("diagnostics"), "Verify did not populate diagnostics scalar"
    assert context.graph_context["is_fragile"] is False

    # 3) Run Steward (persist)
    steward = TestOntologySteward(db=db)
    await steward.run(context)

    inserts = "\n".join(db.inserts)
    deletes = "\n".join(db.deletes)

    # Session + lifecycle (status delete/insert + ended-at delete/insert)
    assert "isa run-session" in inserts
    assert "has ended-at" in inserts

    # Template execution persisted
    assert "isa template-execution" in inserts
    assert 'has execution-id "exec-claim-e2e-1"' in inserts
    assert "has success true" in inserts.lower()

    # Validation evidence persisted + linked to proposition
    assert "isa validation-evidence" in inserts
    assert "isa evidence-for-proposition" in inserts
    
    # Check JSON payload for Feynman checks
    # Assert on escaped key presence directly (robust for TQL string)
    assert '\\"feynman\\":' in inserts, "Feynman report key not found in persisted JSON"
    # Also check it has content (not just empty dict if that was a concern, but key presence is P0)
    assert '\\"all_pass\\":' in inserts or '\\"checks\\":' in inserts

@pytest.mark.asyncio
async def test_v22_e2e_budget_exceeded():
    """Case A: Budget exceeded -> Persist Fragility."""
    db = StrictMockTypeDB()
    db.query_insert('insert $p isa proposition, has entity-id "claim-budget";')
    
    verify = TestVerifyAgent(max_budget_ms=100)
    verify.mock_runtime = 5000 # Exceeds budget
    
    context = AgentContext(graph_context={
        "session_id": "sess-budget",
        "atomic_claims": [{"claim_id": "claim-budget", "content": "Too slow"}],
    })
    
    context = await verify.run(context)
    
    # Check memory state
    assert context.graph_context["is_fragile"] is True, "Scalar state not fragile"
    
    # Run Steward
    steward = TestOntologySteward(db=db)
    await steward.run(context)
    
    inserts = "\n".join(db.inserts)
    
    # Check persistence of fragility
    # Look for escaped json key-value
    assert '\\"is_fragile\\": true' in inserts, "Fragility flag was not persisted as true in JSON"

@pytest.mark.asyncio
async def test_v22_e2e_diagnostic_failure():
    """Case B: Diagnostics failure (missing ESS) -> Persist Fragility."""
    db = StrictMockTypeDB()
    db.query_insert('insert $p isa proposition, has entity-id "claim-diag";')
    
    verify = TestVerifyAgent()
    verify.mock_diagnostics = {"toy_ok": True} # Missing ESS for MC template
    
    context = AgentContext(graph_context={
        "session_id": "sess-diag",
        "atomic_claims": [{"claim_id": "claim-diag", "content": "Bad Diag"}],
    })
    
    context = await verify.run(context)
    
    assert context.graph_context["is_fragile"] is True, "Diagnostics failure didn't trigger fragility"
    
    steward = TestOntologySteward(db=db)
    await steward.run(context)
    
    inserts = "\n".join(db.inserts)
    
    # Verify persistence
    assert '\\"is_fragile\\": true' in inserts, "Fragility flag from diagnostics was not persisted"
