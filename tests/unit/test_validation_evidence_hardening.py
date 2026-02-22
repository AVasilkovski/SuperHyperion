import pytest

from src.agents.ontology_steward import q_insert_validation_evidence

# Common fixture payload
VALID_PAYLOAD = {
    "claim_id": "prop-123",
    "execution_id": "exec-456",
    "template_qid": "template@1.0.0",
    "scope_lock_id": "scope-789",
    "success": True,
    "confidence_score": 0.95,
}


def test_insert_valid_evidence():
    """Happy path should produce valid TypeQL."""
    query = q_insert_validation_evidence("sess-1", VALID_PAYLOAD)
    # ID should be present and start with ev-
    assert 'has entity-id "ev-' in query
    assert 'has evidence-role "support"' in query
    assert "has confidence-score 0.95" in query


def test_insert_with_explicit_id():
    """Should use provided evidence_id."""
    query = q_insert_validation_evidence("sess-1", VALID_PAYLOAD, evidence_id="manual-id-123")
    assert 'has entity-id "manual-id-123"' in query


def test_missing_claim_id_raises():
    """Must require claim_id."""
    payload = VALID_PAYLOAD.copy()
    del payload["claim_id"]
    with pytest.raises(ValueError, match="missing claim_id"):
        q_insert_validation_evidence("sess-1", payload)


def test_missing_scope_lock_id_raises():
    """Must require scope_lock_id (hardening)."""
    payload = VALID_PAYLOAD.copy()
    del payload["scope_lock_id"]
    with pytest.raises(ValueError, match="missing scope_lock_id"):
        q_insert_validation_evidence("sess-1", payload)


def test_missing_template_qid_raises():
    """Must require template_id (hardening)."""
    payload = VALID_PAYLOAD.copy()
    del payload["template_qid"]
    with pytest.raises(ValueError, match="missing template_qid"):
        q_insert_validation_evidence("sess-1", payload)


def test_speculative_evidence_raises():
    """Must reject speculative evidence."""
    payload = VALID_PAYLOAD.copy()
    payload["epistemic_status"] = "speculative"
    with pytest.raises(ValueError, match="Attempted to persist speculative evidence"):
        q_insert_validation_evidence("sess-1", payload)


def test_confidence_clamping():
    """Should clamp values > 1.0 or < 0.0."""
    payload = VALID_PAYLOAD.copy()

    # High clamp
    payload["confidence_score"] = 1.5
    query = q_insert_validation_evidence("sess-1", payload)
    assert "has confidence-score 1.0" in query

    # Low clamp
    payload["confidence_score"] = -0.5
    query = q_insert_validation_evidence("sess-1", payload)
    assert "has confidence-score 0.0" in query


def test_nan_confidence_raises():
    """Should reject NaN/Inf confidence."""
    payload = VALID_PAYLOAD.copy()
    payload["confidence_score"] = float("nan")
    with pytest.raises(ValueError, match="must be finite"):
        q_insert_validation_evidence("sess-1", payload)


def test_execution_id_normalization():
    """Should handle both snake_case and kebab-case inputs."""
    payload = VALID_PAYLOAD.copy()
    del payload["execution_id"]
    payload["execution-id"] = "exec-kebab"

    query = q_insert_validation_evidence("sess-1", payload)
    assert 'has execution-id "exec-kebab"' in query
