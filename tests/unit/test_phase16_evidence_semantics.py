"""
Phase 16.1 Evidence Semantics Tests

Tests for:
- Negative evidence persistence and deterministic IDs
- Evidence role validation
- Validation evidence success-only invariant preservation
"""

import pytest

from src.agents.ontology_steward import (
    q_insert_negative_evidence,
)
from src.epistemology.evidence_roles import (
    EvidenceRole,
    FailureMode,
    evidence_role_affects_belief,
    validate_evidence_role,
    validate_failure_mode,
)
from src.governance.fingerprinting import (
    make_capsule_id,
    make_evidence_id,
    make_mutation_id,
    make_negative_evidence_id,
)

# =============================================================================
# Evidence Role Tests
# =============================================================================


class TestEvidenceRoles:
    """Tests for evidence role validation and semantics."""

    def test_evidence_role_enum_values(self):
        """Verify all expected role values exist."""
        assert EvidenceRole.SUPPORT.value == "support"
        assert EvidenceRole.REFUTE.value == "refute"
        assert EvidenceRole.UNDERCUT.value == "undercut"
        assert EvidenceRole.REPLICATE.value == "replicate"

    def test_validate_evidence_role_valid(self):
        """Valid roles should pass validation."""
        assert validate_evidence_role("support") == EvidenceRole.SUPPORT
        assert validate_evidence_role("refute") == EvidenceRole.REFUTE
        assert validate_evidence_role("UNDERCUT") == EvidenceRole.UNDERCUT
        assert validate_evidence_role("  Replicate  ") == EvidenceRole.REPLICATE

    def test_validate_evidence_role_none(self):
        """None input should return None."""
        assert validate_evidence_role(None) is None

    def test_validate_evidence_role_invalid(self):
        """Invalid roles should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_evidence_role("invalid_role")
        assert "Invalid evidence role" in str(exc_info.value)

    def test_failure_mode_enum_values(self):
        """Verify all expected failure mode values exist."""
        assert FailureMode.NULL_EFFECT.value == "null_effect"
        assert FailureMode.SIGN_FLIP.value == "sign_flip"
        assert FailureMode.VIOLATED_ASSUMPTION.value == "violated_assumption"
        assert FailureMode.NONIDENTIFIABLE.value == "nonidentifiable"

    def test_validate_failure_mode_valid(self):
        """Valid failure modes should pass validation."""
        assert validate_failure_mode("null_effect") == FailureMode.NULL_EFFECT
        assert validate_failure_mode("SIGN_FLIP") == FailureMode.SIGN_FLIP

    def test_validate_failure_mode_invalid(self):
        """Invalid failure modes should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_failure_mode("unknown_failure")
        assert "Invalid failure mode" in str(exc_info.value)

    def test_evidence_role_affects_belief_support(self):
        """Support role should have positive direction."""
        effects = evidence_role_affects_belief(EvidenceRole.SUPPORT)
        assert effects["direction"] == 1
        assert effects["can_prove"] is True

    def test_evidence_role_affects_belief_refute(self):
        """Refute role should have negative direction and require HITL."""
        effects = evidence_role_affects_belief(EvidenceRole.REFUTE)
        assert effects["direction"] == -1
        assert effects["requires_hitl"] is True
        assert effects["can_prove"] is False

    def test_evidence_role_affects_belief_undercut(self):
        """Undercut role should be neutral and require HITL."""
        effects = evidence_role_affects_belief(EvidenceRole.UNDERCUT)
        assert effects["direction"] == 0
        assert effects["requires_hitl"] is True

    def test_evidence_role_affects_belief_replicate(self):
        """Replicate role direction depends on outcome."""
        effects = evidence_role_affects_belief(EvidenceRole.REPLICATE)
        assert effects["direction"] is None  # Context-dependent
        assert effects["can_prove"] is True


# =============================================================================
# Fingerprinting Tests
# =============================================================================


class TestFingerprinting:
    """Tests for deterministic ID generation."""

    def test_make_evidence_id_deterministic(self):
        """Same inputs should produce same ID."""
        id1 = make_evidence_id("sess-1", "claim-1", "exec-1", "qid-1")
        id2 = make_evidence_id("sess-1", "claim-1", "exec-1", "qid-1")
        assert id1 == id2

    def test_make_evidence_id_prefix(self):
        """Validation evidence should have 'ev-' prefix."""
        id1 = make_evidence_id("sess-1", "claim-1", "exec-1", "qid-1")
        assert id1.startswith("ev-")
        assert len(id1) == 35  # ev- + 32 hex chars

    def test_make_negative_evidence_id_prefix(self):
        """Negative evidence should have 'nev-' prefix."""
        id1 = make_negative_evidence_id("sess-1", "claim-1", "exec-1", "qid-1")
        assert id1.startswith("nev-")
        assert len(id1) == 36  # nev- + 32 hex chars

    def test_evidence_id_different_channels(self):
        """Same inputs should produce different IDs for different channels."""
        pos_id = make_evidence_id("sess-1", "claim-1", "exec-1", "qid-1")
        neg_id = make_negative_evidence_id("sess-1", "claim-1", "exec-1", "qid-1")

        # Prefixes differ
        assert pos_id[:3] != neg_id[:4]
        # Hash parts are the same (same payload)
        assert pos_id[3:] == neg_id[4:]

    def test_make_mutation_id_deterministic(self):
        """Mutation IDs should be deterministic and namespaced."""
        id1 = make_mutation_id("sess-1", "intent-1", "claim-1", "verified")
        id2 = make_mutation_id("sess-1", "intent-1", "claim-1", "verified")
        assert id1 == id2
        assert id1.startswith("mut-")

    def test_make_capsule_id_deterministic(self):
        """Capsule IDs should be deterministic."""
        id1 = make_capsule_id("qid-1", "spec-hash", "code-hash", "retr-digest")
        id2 = make_capsule_id("qid-1", "spec-hash", "code-hash", "retr-digest")
        assert id1 == id2
        assert id1.startswith("cap-")


# =============================================================================
# Negative Evidence Query Tests
# =============================================================================


class TestNegativeEvidenceQuery:
    """Tests for q_insert_negative_evidence query builder."""

    def test_negative_evidence_query_basic(self):
        """Basic negative evidence query should be valid."""
        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "numeric_consistency@v1.0.0",
            "template_id": "numeric_consistency",
            "failure_mode": "null_effect",
            "refutation_strength": 0.8,
            "confidence_score": 0.7,
        }
        query = q_insert_negative_evidence("sess-001", ev)

        assert "negative-evidence" in query
        assert "claim-123" in query
        assert "failure-mode" in query
        assert "null_effect" in query
        assert "refutation-strength 0.8" in query
        assert "success true" in query  # Execution succeeded
        assert 'has evidence-role "refute"' in query  # Correct TypeQL syntax

    def test_negative_evidence_requires_claim_id(self):
        """Negative evidence without claim_id should raise ValueError."""
        ev = {
            "execution_id": "exec-456",
            "template_qid": "numeric_consistency@v1.0.0",
        }
        with pytest.raises(ValueError) as exc_info:
            q_insert_negative_evidence("sess-001", ev)
        assert "missing claim_id" in str(exc_info.value)

    def test_negative_evidence_uses_deterministic_id(self):
        """Negative evidence should use deterministic ID."""
        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "numeric_consistency@v1.0.0",
        }
        query = q_insert_negative_evidence("sess-001", ev)

        # Extract entity-id from query
        expected_id = make_negative_evidence_id(
            "sess-001", "claim-123", "exec-456", "numeric_consistency@v1.0.0"
        )
        assert expected_id in query

    def test_negative_evidence_custom_id(self):
        """Custom evidence_id should be used if provided."""
        ev = {"claim_id": "claim-123", "execution_id": "exec-456", "template_qid": "qid-1"}
        custom_id = "nev-custom-12345"
        query = q_insert_negative_evidence("sess-001", ev, evidence_id=custom_id)

        assert custom_id in query

    def test_negative_evidence_default_role(self):
        """Default evidence role should be 'refute'."""
        ev = {"claim_id": "claim-123", "execution_id": "exec-1", "template_qid": "qid-1"}
        query = q_insert_negative_evidence("sess-001", ev)

        assert 'has evidence-role "refute"' in query

    def test_negative_evidence_custom_role(self):
        """Custom evidence role should be used if provided."""
        ev = {"claim_id": "claim-123", "execution_id": "exec-1", "template_qid": "qid-1"}
        query = q_insert_negative_evidence("sess-001", ev, evidence_role="undercut")

        assert 'has evidence-role "undercut"' in query


# =============================================================================
# Invariant Preservation Tests
# =============================================================================


class TestInvariantPreservation:
    """Tests ensuring Phase 15 invariants are preserved."""

    def test_validation_evidence_success_only_preserved(self):
        """Validation evidence should still be success-only.

        This test ensures we haven't broken the existing invariant.
        The new negative-evidence channel is separate.
        """
        from src.agents.ontology_steward import q_insert_validation_evidence

        ev = {
            "claim_id": "claim-123",
            "execution_id": "exec-456",
            "template_qid": "numeric_consistency@v1.0.0",
            "scope_lock_id": "sl-123",
            "success": True,
            "confidence_score": 0.9,
        }
        query = q_insert_validation_evidence("sess-001", ev)

        # Validation evidence is a different entity type
        assert "validation-evidence" in query
        assert "negative-evidence" not in query

    def test_evidence_channels_are_separate(self):
        """Positive and negative evidence channels should be completely separate."""
        from src.agents.ontology_steward import q_insert_validation_evidence

        ev_pos = {
            "claim_id": "c1",
            "execution_id": "e1",
            "template_qid": "q1",
            "success": True,
            "scope_lock_id": "sl-1",
        }
        ev_neg = {
            "claim_id": "c1",
            "execution_id": "e1",
            "template_qid": "q1",
            "failure_mode": "null_effect",
            "scope_lock_id": "sl-1",
        }

        query_pos = q_insert_validation_evidence("s1", ev_pos)
        query_neg = q_insert_negative_evidence("s1", ev_neg)

        # Different entity types
        assert "validation-evidence" in query_pos
        assert "negative-evidence" in query_neg

        # Different ID prefixes
        assert 'entity-id "ev-' in query_pos
        assert 'entity-id "nev-' in query_neg
