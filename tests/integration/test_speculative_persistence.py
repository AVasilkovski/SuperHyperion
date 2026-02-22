"""
Integration Tests: Speculative Hypotheses Persistence

Tests:
1. Happy path: hypothesis persistence + session link + proposition link (if exists)
2. Segregation: speculative context does NOT create validation evidence
3. Missing proposition: hypothesis persisted, but link IS NOT created
4. Guard: ValueError on speculative evidence
5. Guard: ValueError on missing claim_id in evidence
"""

import re

import pytest

from src.agents.base_agent import AgentContext
from src.agents.ontology_steward import OntologySteward, q_insert_validation_evidence

# -------------------------------------------------------------------------
# Mock TypeDB (Strict) for Schema Validation
# -------------------------------------------------------------------------


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
            "speculative-hypothesis-targets-proposition": [],  # Legacy tracking for first test
            "attempted_speculative_hypothesis_targets_proposition": [],  # Detailed tracking
            "created_speculative_hypothesis_targets_proposition": [],  # Detailed tracking
            "validation-evidence": [],
            "truth-assertion": [],
        }

    def query_insert(self, q, **kwargs):
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
                r'has\s+entity-id\s+"([^"]+)"', q_stripped, flags=re.IGNORECASE | re.DOTALL
            )
            if m:
                self.data["proposition"].add(m.group(1))

        # --------------------------------------------------
        # Speculative hypothesis entity
        # --------------------------------------------------
        if "isa speculative-hypothesis" in q_stripped and "has content" in q_stripped:
            self.data["speculative-hypothesis"].append(q_stripped)

        # --------------------------------------------------
        # Session -> speculative-hypothesis link
        # --------------------------------------------------
        if "isa session-has-speculative-hypothesis" in q_stripped and "hypothesis:" in q_stripped:
            self.data["session-has-speculative-hypothesis"].append(q_stripped)

        # --------------------------------------------------
        # Speculative hypothesis -> proposition link (attempted vs created)
        # --------------------------------------------------
        if "isa speculative-hypothesis-targets-proposition" in q_stripped:
            # Legacy tracking for segregation test (simple append)
            self.data["speculative-hypothesis-targets-proposition"].append(q_stripped)

            # Detailed tracking for logic tests
            self.data["attempted_speculative_hypothesis_targets_proposition"].append(q_stripped)

            m = re.search(
                r'\$p\s+isa\s+proposition.*?has\s+entity-id\s+"([^"]+)"',
                q_stripped,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if m:
                prop_id = m.group(1)
                # If proposition exists, we consider it "created" in our mock logic
                if prop_id in self.data["proposition"]:
                    self.data["created_speculative_hypothesis_targets_proposition"].append(
                        q_stripped
                    )

        # --------------------------------------------------
        # Guards: grounded artifacts must not appear
        # --------------------------------------------------
        if "isa validation-evidence" in q_stripped:
            self.data["validation-evidence"].append(q_stripped)

        if "isa truth-assertion" in q_stripped:
            self.data["truth-assertion"].append(q_stripped)

    def query_delete(self, q, **kwargs):
        self.queries.append(f"DELETE: {q}")

    def query_read(self, q):
        return []


# -------------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_speculative_persistence_segregation():
    """
    Verify Phase 11 Core Requirement:
    Speculative hypotheses are persisted as 'speculative-hypothesis' entities
    and DO NOT leak into grounded artifacts (validation-evidence/truth-assertion).
    """
    steward = OntologySteward()
    mock_db = StrictMockTypeDB()
    steward.db = mock_db
    steward.insert_to_graph = mock_db.query_insert  # Direct patch

    # 1. Setup Context with Speculative Output
    context = AgentContext(
        graph_context={
            "session_id": "sess-test-p11",
            "speculative_context": {
                "claim-123": {
                    "alternatives": [
                        {"hypothesis": "Alt A", "confidence": 0.4},
                        {"hypothesis": "Alt B", "confidence": 0.2},
                    ]
                }
            },
        }
    )

    # 2. Run Steward
    await steward.run(context)

    # 3. Verify Speculative Persistence
    # Should have 2 hypotheses inserted
    hyps = mock_db.data["speculative-hypothesis"]
    assert len(hyps) == 2
    assert any('has content "Alt A"' in q for q in hyps)
    assert any('has belief-state "proposed"' in q for q in hyps)

    # Should have 2 session links
    links = mock_db.data["session-has-speculative-hypothesis"]
    assert len(links) == 2

    # 4. Verify SEGREGATION (The Audit Requirement)
    # Speculation must NOT produce evidence or truth assertions
    assert len(mock_db.data["validation-evidence"]) == 0
    assert len(mock_db.data["truth-assertion"]) == 0

    # 5. Verify Target Linking (Best Effort - mocked proposition check skipped here)
    target_links = mock_db.data["attempted_speculative_hypothesis_targets_proposition"]
    assert len(target_links) == 2
    assert "claim-123" in target_links[0]


@pytest.mark.asyncio
async def test_speculative_happy_path_with_proposition():
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

    context = AgentContext(
        graph_context={
            "session_id": session_id,
            "speculative_context": {
                claim_id: {
                    "alternatives": [
                        {"hypothesis": "Alt A", "confidence": 0.4},
                        {"hypothesis": "Alt B", "confidence": 0.3},
                    ]
                }
            },
        }
    )

    await steward.run(context)

    hyps = mock_db.data["speculative-hypothesis"]
    links = mock_db.data["session-has-speculative-hypothesis"]
    attempted = mock_db.data["attempted_speculative_hypothesis_targets_proposition"]
    created = mock_db.data["created_speculative_hypothesis_targets_proposition"]

    # Assertions
    assert len(hyps) == 2
    assert any('has content "Alt A"' in q for q in hyps)
    assert len(links) == 2

    assert len(attempted) == 2  # Both link queries attempted
    assert len(created) == 2  # Both links CREATED (proposition exists)
    assert all(claim_id in q for q in created)


@pytest.mark.asyncio
async def test_speculative_no_proposition_no_link():
    """
    E2E: Hypothesis persisted, but proposition link NOT created (proposition missing).
    """
    steward = OntologySteward()
    mock_db = StrictMockTypeDB()
    steward.db = mock_db
    steward.insert_to_graph = mock_db.query_insert

    context = AgentContext(
        graph_context={
            "session_id": "sess-no-prop",
            "speculative_context": {
                "claim-missing": {"alternatives": [{"hypothesis": "Orphan Alt"}]}
            },
        }
    )

    await steward.run(context)

    hyps = mock_db.data["speculative-hypothesis"]
    attempted = mock_db.data["attempted_speculative_hypothesis_targets_proposition"]
    created = mock_db.data["created_speculative_hypothesis_targets_proposition"]

    assert len(hyps) == 1  # Hypothesis persisted
    assert len(attempted) == 1  # Link query attempted
    assert len(created) == 0  # BUT NOT created (no proposition)


def test_guard_speculative_evidence():
    """
    Unit: ValueError on speculative evidence in validation evidence builder.
    """
    ev = {
        "claim_id": "c1",
        "content": "spec",
        "template_qid": "q1",
        "scope_lock_id": "sl-1",
        "epistemic_status": "speculative",
    }
    with pytest.raises(ValueError, match="CRITICAL.*speculative"):
        q_insert_validation_evidence("sess-fail", ev)


def test_guard_nested_speculative():
    """
    Unit: ValueError on nested speculative marker inside JSON.
    """
    ev = {
        "claim_id": "c1",
        "content": "nested",
        "template_qid": "q1",
        "scope_lock_id": "sl-1",
        "json": {"epistemic_status": "speculative"},
    }
    with pytest.raises(ValueError, match="CRITICAL.*speculative"):
        q_insert_validation_evidence("sess-fail", ev)


def test_guard_missing_claim_id():
    """
    Unit: ValueError if validation evidence missing claim_id.
    """
    ev = {"content": "Missing claim", "epistemic_status": "supported"}
    with pytest.raises(ValueError, match="CRITICAL.*claim_id"):
        q_insert_validation_evidence("sess-fail", ev)


def test_guard_kebab_case_speculative():
    """
    Unit: ValueError on kebab-case speculative marker (key drift protection).
    """
    ev = {
        "claim_id": "c1",
        "content": "kebab",
        "template_qid": "q1",
        "scope_lock_id": "sl-1",
        "epistemic-status": "speculative",
    }
    with pytest.raises(ValueError, match="CRITICAL.*speculative"):
        q_insert_validation_evidence("sess-fail", ev)
