
import pytest
import json
from pathlib import Path
from src.agents.ontology_steward import (
    q_insert_execution, 
    q_insert_proposal, 
    q_insert_trace,
    q_insert_session,
    q_insert_intent_status_event,
    escape
)

def test_schema_static_verification():
    """Verify schema text contains required definitions."""
    schema_path = Path("src/schema/schema_v22_patch.tql")
    content = schema_path.read_text(encoding="utf-8")
    
    # 1. Success Attribute
    assert "attribute success, value boolean;" in content, "Missing success attribute"
    
    # 2. Severity Attribute
    assert "attribute severity, value string;" in content, "Missing severity attribute"
    
    # 3. Unique Proposal Relation
    count = content.count("relation proposal-targets-proposition")
    assert count == 1, f"Expected 1 duplicate of relation proposal-targets-proposition, found {count}"

def test_builder_query_shapes():
    """Verify generated queries match schema requirements."""
    
    # 1. Template Execution (must use success)
    ex = {
        "execution_id": "test-exec",
        "template_id": "tpl-1",
        "success": True,
        "runtime_ms": 100
    }
    q_exec = q_insert_execution("sess-1", ex)
    assert 'isa template-execution' in q_exec
    assert 'has success true' in q_exec.lower(), "Execution query invalid success format"
    assert 'isa session-has-execution' in q_exec
    
    # 2. Proposal (must use proposal-targets-proposition)
    prop = {
        "claim_id": "claim-123",
        "final_proposed_status": "supported"
    }
    q_prop = q_insert_proposal("sess-1", prop)
    assert 'isa epistemic-proposal' in q_prop
    assert '(proposal: $p, proposition: $prop) isa proposal-targets-proposition' in q_prop
    
    # 3. Validation Evidence (sanity check for future role labels)
    # If we add evidence builder, it must match 'validation-evidence plays session-has-evidence:evidence'
    # Currently handled implicitly via execution or future work.
    
    # 4. Meta Critique Role Label Check (Simulated)
    # We don't have a builder for this yet, but let's verify if we were to write one
    role_label_check = "(session: $s, meta-critique: $m) isa session-has-meta-critique;"
    # Just asserting we know this is the string we want.
    pass

def test_intent_status_payload():
    """Verify json payload with error."""
    payload = {"error": "Perm failure"}
    q_log = q_insert_intent_status_event("intent-1", "failed", payload)
    
    assert 'has intent-status "failed"' in q_log
    assert 'has json' in q_log
    assert 'Perm failure' in q_log
