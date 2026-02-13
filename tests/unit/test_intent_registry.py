"""
Tests for Intent Registry (Phase 16.2)

Verifies:
- Registry access functions
- Per-lane approval policies
- Per-lane scope-lock policies
- Payload validation (including scope-lock and ID field enforcement)
"""

import pytest

from src.hitl.intent_registry import (
    INTENT_REGISTRY,
    ApprovalPolicy,
    get_approval_decision,
    get_intent_spec,
    is_intent_type_known,
    requires_scope_lock,
    validate_intent_payload,
)


class TestRegistryAccess:
    """Tests for registry access functions."""

    def test_get_known_intent_spec(self):
        """Should return spec for known intent type."""
        spec = get_intent_spec("create_proposition")
        assert spec.intent_type == "create_proposition"
        assert "claim_id" in spec.required_id_fields

    def test_get_unknown_intent_spec_raises(self):
        """Should raise ValueError for unknown intent type."""
        with pytest.raises(ValueError, match="Unknown intent type"):
            get_intent_spec("nonexistent_type")

    def test_is_intent_type_known(self):
        """Should correctly identify known/unknown types."""
        assert is_intent_type_known("create_proposition") is True
        assert is_intent_type_known("metrics_update") is True
        assert is_intent_type_known("nonexistent") is False


class TestApprovalPolicy:
    """Tests for per-lane approval policies."""

    def test_create_claim_speculative_auto_approves(self):
        """Speculative create_claim should auto-approve."""
        policy = get_approval_decision("create_claim", "speculative")
        assert policy == ApprovalPolicy.AUTO

    def test_create_claim_grounded_denied(self):
        """Grounded create_claim should be denied (use create_proposition)."""
        policy = get_approval_decision("create_claim", "grounded")
        assert policy == ApprovalPolicy.DENY

    def test_create_proposition_grounded_requires_hitl(self):
        """Grounded create_proposition should require HITL."""
        policy = get_approval_decision("create_proposition", "grounded")
        assert policy == ApprovalPolicy.HITL

    def test_metrics_update_auto_approves_both_lanes(self):
        """Low-risk intents should auto-approve in both lanes."""
        assert get_approval_decision("metrics_update", "grounded") == ApprovalPolicy.AUTO
        assert get_approval_decision("metrics_update", "speculative") == ApprovalPolicy.AUTO

    def test_revise_proposition_requires_hitl(self):
        """Theory change intents should require HITL."""
        assert get_approval_decision("revise_proposition", "grounded") == ApprovalPolicy.HITL
        assert get_approval_decision("fork_proposition", "grounded") == ApprovalPolicy.HITL
        assert get_approval_decision("quarantine_proposition", "grounded") == ApprovalPolicy.HITL

    def test_stage_epistemic_proposal_auto_approves(self):
        """Proposal staging (read-only) should auto-approve."""
        assert get_approval_decision("stage_epistemic_proposal", "grounded") == ApprovalPolicy.AUTO


class TestScopeLockPolicy:
    """Tests for per-lane scope-lock policies."""

    def test_create_proposition_grounded_requires_scope_lock(self):
        """Grounded create_proposition should require scope lock."""
        assert requires_scope_lock("create_proposition", "grounded") is True

    def test_create_claim_speculative_optional_scope_lock(self):
        """Speculative create_claim should not require scope lock."""
        assert requires_scope_lock("create_claim", "speculative") is False

    def test_metrics_update_never_requires_scope_lock(self):
        """Low-risk intents should not require scope lock."""
        assert requires_scope_lock("metrics_update", "grounded") is False
        assert requires_scope_lock("metrics_update", "speculative") is False

    def test_theory_change_intents_require_scope_lock(self):
        """All theory change intents should require scope lock."""
        for intent_type in ["revise_proposition", "fork_proposition", "quarantine_proposition"]:
            assert requires_scope_lock(intent_type, "grounded") is True


class TestPayloadValidation:
    """Tests for payload validation."""

    def test_valid_payload_passes(self):
        """Should pass validation for valid payload."""
        validate_intent_payload(
            "create_proposition",
            {"claim_id": "prop-123", "content": "Test"}, # scope_lock_id moved to envelope
            "grounded"
        )

    def test_missing_required_field_raises(self):
        """Should raise for missing required field."""
        with pytest.raises(ValueError, match="Missing required fields"):
            validate_intent_payload(
                "create_proposition",
                {"claim_id": "prop-123"},  # missing content
                "grounded"
            )

    def test_unknown_field_raises(self):
        """Should raise for unknown field."""
        with pytest.raises(ValueError, match="Unknown fields"):
            validate_intent_payload(
                "create_proposition",
                {"claim_id": "prop-123", "content": "Test", "unknown": "bad"},
                "grounded"
            )

    def test_wrong_lane_raises(self):
        """Should raise for intent type not allowed in lane."""
        with pytest.raises(ValueError, match="not allowed in lane"):
            validate_intent_payload(
                "create_proposition",  # grounded-only
                {"claim_id": "prop-123", "content": "Test"},
                "speculative"
            )

    def test_lane_in_payload_raises(self):
        """Should raise when lane is in payload (lane is envelope metadata)."""
        with pytest.raises(ValueError, match="Payload must not contain 'lane'"):
            validate_intent_payload(
                "create_claim",
                {"claim_id": "prop-123", "content": "Test", "lane": "speculative"},
                "speculative"
            )

    def test_missing_id_field_raises(self):
        """Should raise when required ID field is empty."""
        with pytest.raises(ValueError, match="Missing or empty ID fields"):
            validate_intent_payload(
                "update_epistemic_status",
                {"claim_id": "", "new_status": "validated"},
                "grounded"
            )

    def test_fork_requires_both_claim_ids(self):
        """Fork proposition should require both parent_claim_id and new_claim_id."""
        with pytest.raises(ValueError, match="Missing or empty ID fields"):
            validate_intent_payload(
                "fork_proposition",
                {"parent_claim_id": "prop-1", "new_claim_id": "", "content": "Test",
                 "fork_rationale": "conflict"},
                "grounded"
            )

    def test_valid_fork_payload_passes(self):
        """Should pass validation for valid fork payload."""
        validate_intent_payload(
            "fork_proposition",
            {
                "parent_claim_id": "prop-1",
                "new_claim_id": "prop-2",
                "content": "Forked hypothesis",
                "fork_rationale": "High conflict",
            },
            "grounded"
        )


class TestRegistryCompleteness:
    """Tests for registry completeness."""

    def test_all_phase_16_2_intents_present(self):
        """Should have all Phase 16.2 theory change intents."""
        required = {"revise_proposition", "fork_proposition", "quarantine_proposition", "stage_epistemic_proposal"}
        assert required.issubset(set(INTENT_REGISTRY.keys()))

    def test_all_low_risk_intents_present(self):
        """Should have all low-risk auto-approve intents."""
        required = {"metrics_update", "cache_write", "trace_append"}
        assert required.issubset(set(INTENT_REGISTRY.keys()))

    def test_all_specs_have_descriptions(self):
        """All specs should have non-empty descriptions."""
        for intent_type, spec in INTENT_REGISTRY.items():
            assert spec.description, f"{intent_type} missing description"

    def test_create_claim_not_allowed_in_grounded(self):
        """create_claim should not be allowed in grounded lane."""
        spec = get_intent_spec("create_claim")
        assert "grounded" not in spec.allowed_lanes
