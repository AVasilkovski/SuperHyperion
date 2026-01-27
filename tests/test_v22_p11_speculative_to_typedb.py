"""
Phase 11 E2E Tests: Speculative Hypotheses Persistence

Tests:
1. Happy path: hypothesis persistence + session link + proposition link (if exists)
2. Segregation: speculative context does NOT create validation evidence
3. Missing proposition: hypothesis persisted, but link IS NOT created
4. Guard: ValueError on speculative evidence
5. Guard: ValueError on missing claim_id in evidence
"""

import pytest
import re
from src.agents.ontology_steward import OntologySteward, q_insert_validation_evidence
from src.agents.base_agent import AgentContext


import re

class StrictMockTypeDB:
    """
    Mock DB that simulates match semantics:
    - Tracks existing propositions.
    - Only records proposition links if target proposition exists.
    """
    def __init__(self):
        self.queries = []
        self.data = {
            "run-session": [],
            "proposition": set(),  # existing proposition entity-ids
            "speculative-hypothesis": [],
            "session-has-speculative-hypothesis": [],
            "attempted_speculative_hypothesis_targets_proposition": [],
            "created_speculative_hypothesis_targets_proposition": [],
            "validation-evidence": [],
            "truth-assertion": [],
        }
    
    def query_insert(self, q):
        self.queries.append(q)
        q_stripped = q.strip()
        
        # --------------------------------------------------
        # Track run-session inserts
        # --------------------------------------------------
        if "insert" in q_stripped and "isa run-session" in q_stripped:
            self.data["run-session"].append(q_stripped)
        
        # --------------------------------------------------
        # Track REAL proposition creation (INSERT ONLY)
        # --------------------------------------------------
        if "insert" in q_stripped and "isa proposition" in q_stripped:
            m = re.search(
                r'has\s+entity-id\s+"([^"]+)"',
                q_stripped,
                flags=re.IGNORECASE | re.DOTALL
            )
            if m:
                self.data["proposition"].add(m.group(1))
        
        # --------------------------------------------------
        # Speculative hypothesis entity
        # --------------------------------------------------
        if "isa speculative-hypothesis" in q_stripped and "has content" in q_stripped:
            self.data["speculative-hypothesis"].append(q_stripped)
        
        # --------------------------------------------------
        # Session → speculative-hypothesis link
        # --------------------------------------------------
        if (
            "isa session-has-speculative-hypothesis" in q_stripped
            and "hypothesis:" in q_stripped
        ):
            self.data["session-has-speculative-hypothesis"].append(q_stripped)
        
        # --------------------------------------------------
        # Speculative hypothesis → proposition link (attempted vs created)
        # --------------------------------------------------
        if "isa speculative-hypothesis-targets-proposition" in q_stripped:
            self.data["attempted_speculative_hypothesis_targets_proposition"].append(q_stripped)
            
            m = re.search(
                r'\$p\s+isa\s+proposition\s*,?\s*has\s+entity-id\s+"([^"]+)"',
                q_stripped,
                flags=re.IGNORECASE | re.DOTALL
            )
            if m:
                prop_id = m.group(1)
                if prop_id in self.data["proposition"]:
                    self.data["created_speculative_hypothesis_targets_proposition"].append(q_stripped)
        
        # --------------------------------------------------
        # Guards: grounded artifacts must not appear
        # --------------------------------------------------
        if "isa validation-evidence" in q_stripped:
            self.data["validation-evidence"].append(q_stripped)
            
        if "isa truth-assertion" in q_stripped:
            self.data["truth-assertion"].append(q_stripped)
        
    def query_delete(self, q):
        self.queries.append(f"DELETE: {q}")
        
    def query_read(self, q):
        return []


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v22_p11_speculative_happy_path_with_proposition():
    """
    E2E: Hypothesis + session link + proposition link (proposition exists).
    """
    steward = OntologySteward()
    mock_db = StrictMockTypeDB()
    steward.db = mock_db
    steward.insert_to_graph = mock_db.query_insert
    
    session_id = "sess-happy"
    claim_id = "claim-happy"
    
    # --- Pre-create proposition in mock ---
    mock_db.query_insert(f'''
    insert $p isa proposition, has entity-id "{claim_id}", has content "C";
    ''')
    
    context = AgentContext(graph_context={
        "session_id": session_id,
        "speculative_context": {
            claim_id: {
                "alternatives": [
                    {"hypothesis": "Alt A", "confidence": 0.4},
                    {"hypothesis": "Alt B", "confidence": 0.3},
                ]
            }
        }
    })
    
    await steward.run(context)
    
    hyps = mock_db.data["speculative-hypothesis"]
    links = mock_db.data["session-has-speculative-hypothesis"]
    attempted = mock_db.data["attempted_speculative_hypothesis_targets_proposition"]
    created = mock_db.data["created_speculative_hypothesis_targets_proposition"]
    
    # Assertions
    assert len(hyps) == 2
    assert any('has content "Alt A"' in q for q in hyps)
    assert any('has content "Alt B"' in q for q in hyps)
    assert all('has belief-state "proposed"' in q for q in hyps)
    assert all('has epistemic-status "speculative"' in q for q in hyps)
    
    assert len(links) == 2  # Both linked to session
    
    assert len(attempted) == 2  # Both link queries attempted
    assert len(created) == 2    # Both links CREATED (proposition exists)
    assert all(claim_id in q for q in created)


@pytest.mark.asyncio
async def test_v22_p11_speculative_no_proposition_no_link():
    """
    E2E: Hypothesis persisted, but proposition link NOT created (proposition missing).
    """
    steward = OntologySteward()
    mock_db = StrictMockTypeDB()
    steward.db = mock_db
    steward.insert_to_graph = mock_db.query_insert
    
    context = AgentContext(graph_context={
        "session_id": "sess-no-prop",
        "speculative_context": {
            "claim-missing": {
                "alternatives": [{"hypothesis": "Orphan Alt"}]
            }
        }
    })
    
    await steward.run(context)
    
    hyps = mock_db.data["speculative-hypothesis"]
    attempted = mock_db.data["attempted_speculative_hypothesis_targets_proposition"]
    created = mock_db.data["created_speculative_hypothesis_targets_proposition"]
    
    assert len(hyps) == 1  # Hypothesis persisted
    assert len(attempted) == 1  # Link query attempted
    assert len(created) == 0  # BUT NOT created (no proposition)


@pytest.mark.asyncio
async def test_v22_p11_speculative_segregation():
    """
    E2E: Speculative context does NOT create validation evidence or truth assertions.
    """
    steward = OntologySteward()
    mock_db = StrictMockTypeDB()
    steward.db = mock_db
    steward.insert_to_graph = mock_db.query_insert
    
    context = AgentContext(graph_context={
        "session_id": "sess-segregation",
        "speculative_context": {
            "claim-X": {"alternatives": [{"hypothesis": "Bad Evidence?"}]}
        }
    })
    
    await steward.run(context)
    
    assert len(mock_db.data["speculative-hypothesis"]) == 1
    assert len(mock_db.data["validation-evidence"]) == 0
    assert len(mock_db.data["truth-assertion"]) == 0


def test_v22_p11_guard_speculative_evidence():
    """
    Unit: ValueError on speculative evidence in validation evidence builder.
    """
    ev = {"claim_id": "c1", "content": "spec", "epistemic_status": "speculative"}
    with pytest.raises(ValueError, match="CRITICAL.*speculative"):
        q_insert_validation_evidence("sess-fail", ev)


def test_v22_p11_guard_nested_speculative():
    """
    Unit: ValueError on nested speculative marker inside JSON.
    """
    ev = {"claim_id": "c1", "content": "nested", "json": {"epistemic_status": "speculative"}}
    with pytest.raises(ValueError, match="CRITICAL.*speculative"):
        q_insert_validation_evidence("sess-fail", ev)


def test_v22_p11_guard_missing_claim_id():
    """
    Unit: ValueError if validation evidence missing claim_id.
    """
    ev = {"content": "Missing claim", "epistemic_status": "supported"}
    with pytest.raises(ValueError, match="CRITICAL.*claim_id"):
        q_insert_validation_evidence("sess-fail", ev)


def test_v22_p11_guard_kebab_case_speculative():
    """
    Unit: ValueError on kebab-case speculative marker (key drift protection).
    """
    ev = {"claim_id": "c1", "content": "kebab", "epistemic-status": "speculative"}
    with pytest.raises(ValueError, match="CRITICAL.*speculative"):
        q_insert_validation_evidence("sess-fail", ev)
