"""
Tests for Theory Change Operator (Phase 16.2)

Verifies:
- Evidence aggregation (with channel parameter)
- Conflict/entropy metrics 
- Deterministic action selection
- Proposal generation
- Canonical ID resolution
- Confidence clamping
"""

import pytest

from src.epistemology.evidence_roles import EvidenceRole
from src.epistemology.theory_change_operator import (
    FORK_THRESHOLD,
    EvidenceAggregate,
    TheoryAction,
    aggregate_evidence,
    compute_conflict_score,
    compute_entropy_proxy,
    compute_theory_change_action,
    generate_proposal,
    get_confidence_value,
    get_evidence_entity_id,
)


class TestCanonicalResolvers:
    """Tests for canonical ID and confidence resolvers."""

    def test_get_evidence_entity_id_snake_case(self):
        """Should resolve entity_id (snake_case)."""
        ev = {"entity_id": "ev-123"}
        assert get_evidence_entity_id(ev) == "ev-123"

    def test_get_evidence_entity_id_kebab_case(self):
        """Should resolve entity-id (kebab-case)."""
        ev = {"entity-id": "ev-456"}
        assert get_evidence_entity_id(ev) == "ev-456"

    def test_get_evidence_entity_id_fallback(self):
        """Should return 'unknown' when no ID found."""
        ev = {"other_field": "value"}
        assert get_evidence_entity_id(ev) == "unknown"

    def test_get_confidence_value_clamps_high(self):
        """Should clamp values > 1.0."""
        ev = {"confidence_score": 1.5}
        assert get_confidence_value(ev) == 1.0

    def test_get_confidence_value_clamps_low(self):
        """Should clamp values < 0.0."""
        ev = {"confidence_score": -0.5}
        assert get_confidence_value(ev) == 0.0

    def test_get_confidence_value_handles_kebab_case(self):
        """Should resolve confidence-score (kebab-case)."""
        ev = {"confidence-score": 0.8}
        assert get_confidence_value(ev) == 0.8


class TestEvidenceAggregation:
    """Tests for evidence aggregation."""

    def test_aggregate_support_evidence(self):
        """Should correctly aggregate support evidence."""
        evidence = [
            ({"confidence_score": 0.9}, EvidenceRole.SUPPORT, "validation"),
            ({"confidence_score": 0.8}, EvidenceRole.SUPPORT, "validation"),
        ]
        agg = aggregate_evidence("claim-1", evidence)

        assert agg.support_count == 2
        assert agg.support_max_conf == 0.9
        assert agg.support_mean_conf == pytest.approx(0.85)
        assert agg.refute_count == 0

    def test_aggregate_refute_evidence(self):
        """Should correctly aggregate refute evidence."""
        evidence = [
            ({"refutation_strength": 0.7}, EvidenceRole.REFUTE, "negative"),
        ]
        agg = aggregate_evidence("claim-1", evidence)

        assert agg.refute_count == 1
        assert agg.refute_max_conf == 0.7

    def test_aggregate_replicate_by_channel(self):
        """Should correctly classify replicate by channel."""
        evidence = [
            ({"confidence_score": 0.9}, EvidenceRole.REPLICATE, "validation"),  # success
            ({"confidence_score": 0.8}, EvidenceRole.REPLICATE, "negative"),    # failure
        ]
        agg = aggregate_evidence("claim-1", evidence)

        assert agg.replicate_success_count == 1
        assert agg.replicate_fail_count == 1

    def test_aggregate_mixed_evidence(self):
        """Should correctly aggregate mixed evidence."""
        evidence = [
            ({"confidence_score": 0.9}, EvidenceRole.SUPPORT, "validation"),
            ({"refutation_strength": 0.8}, EvidenceRole.REFUTE, "negative"),
            ({"confidence_score": 0.95}, EvidenceRole.UNDERCUT, "negative"),
        ]
        agg = aggregate_evidence("claim-1", evidence)

        assert agg.support_count == 1
        assert agg.refute_count == 1
        assert agg.undercut_count == 1
        assert agg.total_count == 3


class TestConflictMetrics:
    """Tests for conflict and entropy metrics."""

    def test_no_conflict_all_support(self):
        """Should return 0 conflict when all evidence is support."""
        agg = EvidenceAggregate(
            claim_id="claim-1",
            support_count=3, support_max_conf=0.9, support_mean_conf=0.8,
            refute_count=0, refute_max_conf=0.0, refute_mean_conf=0.0,
            undercut_count=0, undercut_max_conf=0.0,
            replicate_success_count=0, replicate_fail_count=0,
        )
        assert compute_conflict_score(agg) == 0.0

    def test_max_conflict_equal_support_refute(self):
        """Should return ~1.0 conflict when support equals refute."""
        agg = EvidenceAggregate(
            claim_id="claim-1",
            support_count=2, support_max_conf=0.8, support_mean_conf=0.8,
            refute_count=2, refute_max_conf=0.8, refute_mean_conf=0.8,
            undercut_count=0, undercut_max_conf=0.0,
            replicate_success_count=0, replicate_fail_count=0,
        )
        conflict = compute_conflict_score(agg)
        assert conflict == pytest.approx(1.0)

    def test_entropy_single_type(self):
        """Should return low entropy when evidence is homogeneous."""
        agg = EvidenceAggregate(
            claim_id="claim-1",
            support_count=5, support_max_conf=0.9, support_mean_conf=0.8,
            refute_count=0, refute_max_conf=0.0, refute_mean_conf=0.0,
            undercut_count=0, undercut_max_conf=0.0,
            replicate_success_count=0, replicate_fail_count=0,
        )
        entropy = compute_entropy_proxy(agg)
        assert entropy == 0.0


class TestTheoryChangeAction:
    """Tests for theory change action computation."""

    def test_hold_on_insufficient_evidence(self):
        """Should return HOLD when evidence < MIN_EVIDENCE_COUNT."""
        evidence = [
            ({"confidence_score": 0.9}, EvidenceRole.SUPPORT, "validation"),
        ]
        action, meta = compute_theory_change_action("claim-1", evidence)
        assert action == TheoryAction.HOLD
        assert "Insufficient evidence" in meta["rationale"]

    def test_quarantine_on_high_undercut(self):
        """Should return QUARANTINE when undercut confidence is high."""
        evidence = [
            ({"confidence_score": 0.95}, EvidenceRole.UNDERCUT, "negative"),
            ({"confidence_score": 0.5}, EvidenceRole.SUPPORT, "validation"),
        ]
        action, meta = compute_theory_change_action("claim-1", evidence)
        assert action == TheoryAction.QUARANTINE
        assert "undercut" in meta["rationale"].lower()

    def test_fork_on_high_conflict(self):
        """Should return FORK when conflict exceeds threshold."""
        evidence = [
            ({"confidence_score": 0.9}, EvidenceRole.SUPPORT, "validation"),
            ({"confidence_score": 0.9}, EvidenceRole.SUPPORT, "validation"),
            ({"refutation_strength": 0.9}, EvidenceRole.REFUTE, "negative"),
            ({"refutation_strength": 0.9}, EvidenceRole.REFUTE, "negative"),
        ]
        action, meta = compute_theory_change_action("claim-1", evidence)
        assert action == TheoryAction.FORK
        assert meta["conflict_score"] > FORK_THRESHOLD

    def test_revise_on_low_conflict(self):
        """Should return REVISE when conflict is low."""
        evidence = [
            ({"confidence_score": 0.9}, EvidenceRole.SUPPORT, "validation"),
            ({"confidence_score": 0.8}, EvidenceRole.SUPPORT, "validation"),
            ({"confidence_score": 0.7}, EvidenceRole.SUPPORT, "validation"),
        ]
        action, meta = compute_theory_change_action("claim-1", evidence)
        assert action == TheoryAction.REVISE
        assert meta["conflict_score"] == 0.0


class TestProposalGeneration:
    """Tests for proposal generation."""

    def test_generate_proposal_creates_valid_proposal(self):
        """Should generate a valid proposal object."""
        evidence = [
            ({"entity_id": "ev-1", "confidence_score": 0.9}, EvidenceRole.SUPPORT, "validation"),
            ({"entity_id": "ev-2", "confidence_score": 0.8}, EvidenceRole.SUPPORT, "validation"),
        ]
        proposal = generate_proposal("claim-1", evidence, proposal_id="prop-test")

        assert proposal.claim_id == "claim-1"
        assert proposal.action == TheoryAction.REVISE
        assert "ev-1" in proposal.evidence_ids
        assert "ev-2" in proposal.evidence_ids

    def test_proposal_to_intent_payload(self):
        """Should convert proposal to valid intent payload."""
        evidence = [
            ({"entity_id": "ev-1", "confidence_score": 0.9}, EvidenceRole.SUPPORT, "validation"),
            ({"entity-id": "ev-2", "confidence_score": 0.9}, EvidenceRole.SUPPORT, "validation"),
        ]
        proposal = generate_proposal("claim-1", evidence, proposal_id="prop-test")
        payload = proposal.to_intent_payload()

        assert payload["proposal_id"] == "prop-test"
        assert payload["action"] == "revise"
        assert payload["claim_id"] == "claim-1"

    def test_proposal_extracts_kebab_case_ids(self):
        """Should correctly extract entity-id (kebab-case) from evidence."""
        evidence = [
            ({"entity-id": "ev-kebab", "confidence_score": 0.9}, EvidenceRole.SUPPORT, "validation"),
            ({"entity_id": "ev-snake", "confidence_score": 0.8}, EvidenceRole.SUPPORT, "validation"),
        ]
        proposal = generate_proposal("claim-1", evidence, proposal_id="prop-test")

        assert "ev-kebab" in proposal.evidence_ids
        assert "ev-snake" in proposal.evidence_ids
