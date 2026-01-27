
import pytest
from unittest.mock import MagicMock
from src.agents.ontology_steward import OntologySteward
from src.agents.base_agent import AgentContext

# -------------------------------------------------------------------------
# Mock TypeDB (Strict) for Schema Validation
# -------------------------------------------------------------------------

class StrictMockTypeDB:
    def __init__(self):
        self.queries = []
        self.data = {
            "run-session": [],
            "speculative-hypothesis": [],
            "session-has-speculative-hypothesis": [],
            "speculative-hypothesis-targets-proposition": [],
            "validation-evidence": [],
            "truth-assertion": [],
            "proposition": []
        }
    
    def query_insert(self, q):
        self.queries.append(q)
        q = q.strip()
        
        # Parse simple insert patterns for testing
        # Use more precise checks to avoid counting MATCH clauses -> INSERT as 2x
        # Entity insert has attributes like "has content"
        if "isa speculative-hypothesis" in q and "has content" in q:
            self.data["speculative-hypothesis"].append(q)
            
        if "isa session-has-speculative-hypothesis" in q:
            # New role is (session: $s, hypothesis: $h)
            if "hypothesis:" in q:
                 self.data["session-has-speculative-hypothesis"].append(q)
            
        if "isa speculative-hypothesis-targets-proposition" in q:
            # New role is (hypothesis: $h, proposition: $p)
             if "hypothesis:" in q:
                self.data["speculative-hypothesis-targets-proposition"].append(q)
            
        if "isa validation-evidence" in q:
            self.data["validation-evidence"].append(q)
            
        if "isa truth-assertion" in q:
            self.data["truth-assertion"].append(q)
            
    def query_delete(self, q):
        self.queries.append(f"DELETE: {q}")
        
    def query_read(self, q):
        return []

# -------------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_p11_speculative_persistence_segregation():
    """
    Verify Phase 11 Core Requirement:
    Speculative hypotheses are persisted as 'speculative-hypothesis' entities
    and DO NOT leak into grounded artifacts (validation-evidence/truth-assertion).
    """
    steward = OntologySteward()
    mock_db = StrictMockTypeDB()
    steward.db = mock_db
    steward.insert_to_graph = mock_db.query_insert # Direct patch
    
    # 1. Setup Context with Speculative Output
    context = AgentContext(graph_context={
        "session_id": "sess-test-p11",
        "speculative_context": {
            "claim-123": {
                "alternatives": [
                    {"hypothesis": "Alt A", "confidence": 0.4},
                    {"hypothesis": "Alt B", "confidence": 0.2}
                ]
            }
        }
    })
    
    # 2. Run Steward
    await steward.run(context)
    
    # 3. Verify Speculative Persistence
    # Should have 2 hypotheses inserted
    hyps = mock_db.data["speculative-hypothesis"]
    assert len(hyps) == 2
    assert 'has content "Alt A"' in hyps[0] or 'has content "Alt A"' in hyps[1]
    assert 'has belief-state "proposed"' in hyps[0]
    assert 'has epistemic-status "speculative"' in hyps[0]
    
    # Should have 2 session links
    links = mock_db.data["session-has-speculative-hypothesis"]
    assert len(links) == 2
    
    # 4. Verify SEGREGATION (The Audit Requirement)
    # Speculation must NOT produce evidence or truth assertions
    assert len(mock_db.data["validation-evidence"]) == 0
    assert len(mock_db.data["truth-assertion"]) == 0
    
    # 5. Verify Target Linking (Best Effort)
    # Since we mock the separate call, we expect the detailed linking query to occur
    # The current logic tries to link if claim_id exists.
    # Our mocked logic registers the queries.
    target_links = mock_db.data["speculative-hypothesis-targets-proposition"]
    assert len(target_links) == 2
    assert "claim-123" in target_links[0]
