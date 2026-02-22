"""
Phase 16.2-Readiness Tests

Tests for Phase 16.2-proofing safeguards:
- negative-evidence role=support constraint
- Numeric clamping
- require_evidence_role helper
- Precision fixes (NaN/inf rejection, strict mode)
"""

import pytest

from src.agents.ontology_steward import q_insert_negative_evidence
from src.epistemology.evidence_roles import (
    EvidenceRole,
    clamp_probability,
    require_evidence_role,
)


class TestPhase162Safeguards:
    """Tests for Phase 16.2-readiness constraints."""

    def test_negative_evidence_cannot_have_role_support(self):
        """negative-evidence with role='support' should raise ValueError."""
        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "test@v1",
        }

        with pytest.raises(ValueError) as exc_info:
            q_insert_negative_evidence("sess-001", ev, evidence_role="support")

        assert "cannot have role='support'" in str(exc_info.value)
        assert "Use validation-evidence" in str(exc_info.value)

    def test_negative_evidence_allows_refute_role(self):
        """negative-evidence with role='refute' should succeed."""
        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "test@v1",
        }

        query = q_insert_negative_evidence("sess-001", ev, evidence_role="refute")
        assert "negative-evidence" in query
        assert 'has evidence-role "refute"' in query

    def test_negative_evidence_allows_undercut_role(self):
        """negative-evidence with role='undercut' should succeed."""
        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "test@v1",
        }

        query = q_insert_negative_evidence("sess-001", ev, evidence_role="undercut")
        assert "negative-evidence" in query
        assert 'has evidence-role "undercut"' in query

    def test_negative_evidence_allows_replicate_role(self):
        """negative-evidence with role='replicate' should succeed."""
        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "test@v1",
        }

        query = q_insert_negative_evidence("sess-001", ev, evidence_role="replicate")
        assert "negative-evidence" in query
        assert 'has evidence-role "replicate"' in query

    def test_require_evidence_role_with_none_returns_default(self):
        """require_evidence_role with None should return default."""
        result = require_evidence_role(None, EvidenceRole.REFUTE)
        assert result == EvidenceRole.REFUTE

    def test_require_evidence_role_with_valid_value(self):
        """require_evidence_role with valid value should return enum."""
        result = require_evidence_role("undercut", EvidenceRole.REFUTE)
        assert result == EvidenceRole.UNDERCUT

    def test_clamp_probability_returns_clamped_value(self):
        """clamp_probability should clamp to [0,1]."""
        assert clamp_probability(0.5, "test") == 0.5
        assert clamp_probability(1.5, "test") == 1.0
        assert clamp_probability(-0.5, "test") == 0.0
        assert clamp_probability(0.0, "test") == 0.0
        assert clamp_probability(1.0, "test") == 1.0

    def test_negative_evidence_clamps_refutation_strength(self):
        """refutation_strength should be clamped to [0,1]."""
        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "test@v1",
            "refutation_strength": 1.5,  # Out of bounds
        }

        query = q_insert_negative_evidence("sess-001", ev)
        # Should be clamped to 1.0
        assert "refutation-strength 1.0" in query

    def test_negative_evidence_clamps_confidence_score(self):
        """confidence_score should be clamped to [0,1]."""
        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "test@v1",
            "confidence_score": -0.5,  # Out of bounds
        }

        query = q_insert_negative_evidence("sess-001", ev)
        # Should be clamped to 0.0
        assert "confidence-score 0.0" in query

    # Precision fix tests

    def test_clamp_probability_rejects_nan(self):
        """clamp_probability should reject NaN."""
        with pytest.raises(ValueError) as exc_info:
            clamp_probability(float("nan"), "test")
        assert "must be finite" in str(exc_info.value)

    def test_clamp_probability_rejects_inf(self):
        """clamp_probability should reject infinity."""
        with pytest.raises(ValueError) as exc_info:
            clamp_probability(float("inf"), "test")
        assert "must be finite" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            clamp_probability(float("-inf"), "test")
        assert "must be finite" in str(exc_info.value)

    def test_require_evidence_role_strict_raises_on_invalid(self):
        """require_evidence_role with strict=True should raise on invalid input."""
        with pytest.raises(ValueError) as exc_info:
            require_evidence_role("invalid_role", EvidenceRole.REFUTE, strict=True)
        assert "Invalid evidence role" in str(exc_info.value)

    def test_require_evidence_role_permissive_uses_default(self):
        """require_evidence_role with strict=False should use default on invalid."""
        result = require_evidence_role("invalid_role", EvidenceRole.REFUTE, strict=False)
        assert result == EvidenceRole.REFUTE

    def test_negative_evidence_strict_role_validation(self):
        """Typos in evidence_role should raise ValueError in grounded lane."""
        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "test@v1",
        }

        with pytest.raises(ValueError) as exc_info:
            q_insert_negative_evidence("sess-001", ev, evidence_role="reufte")  # typo
        assert "Invalid evidence role" in str(exc_info.value)


class TestDispatchWiring:
    """Tests for production wiring of negative evidence dispatch."""

    def test_seal_uses_negative_prefix_for_negative_channel(self):
        """Seal helper should use nev- prefix for negative channel."""
        from src.governance.fingerprinting import make_evidence_id, make_negative_evidence_id

        session_id = "sess-test"
        claim_id = "claim-abc"
        exec_id = "exec-123"
        template_qid = "test@v1"

        positive_id = make_evidence_id(session_id, claim_id, exec_id, template_qid)
        negative_id = make_negative_evidence_id(session_id, claim_id, exec_id, template_qid)

        assert positive_id.startswith("ev-"), f"Expected ev- prefix, got {positive_id}"
        assert negative_id.startswith("nev-"), f"Expected nev- prefix, got {negative_id}"
        assert positive_id != negative_id

    def test_seal_helper_validates_channel(self):
        """Invalid channel should raise ValueError."""
        from src.agents.ontology_steward import OntologySteward

        steward = OntologySteward()
        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "test@v1",
            "scope_lock_id": "lock-789",
        }

        with pytest.raises(ValueError) as exc_info:
            # Mock template_store to avoid seal operator failures
            class MockStore:
                def get_metadata(self, *args):
                    return None

            steward.template_store = MockStore()
            steward._seal_evidence_dict_before_mint("sess-001", ev, channel="invalid")

        assert "Invalid evidence channel" in str(exc_info.value)

    def test_negative_evidence_query_contains_channel_marker(self):
        """Negative evidence query should contain negative-evidence type."""
        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "test@v1",
        }

        query = q_insert_negative_evidence("sess-001", ev, evidence_role="refute")

        assert "isa negative-evidence" in query
        assert 'has evidence-role "refute"' in query
        assert "success true" in query  # execution succeeded semantics
