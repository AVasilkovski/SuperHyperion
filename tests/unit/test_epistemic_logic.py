"""
Epistemic Module Tests

v2.1: Tests for EpistemicStatus, EpistemicClassifierAgent, and decision rules.
"""

import pytest

from src.epistemic.classifier import EpistemicClassifierAgent
from src.epistemic.status import EpistemicStatus, requires_hitl_approval
from src.epistemic.uncertainty import (
    calculate_scientific_uncertainty,
    compute_confidence_interval,
)


class TestEpistemicStatus:
    """Test epistemic status determination."""

    def test_no_evidence_returns_speculative(self):
        """No evidence → SPECULATIVE."""
        status = EpistemicStatus.from_evidence(
            has_evidence=False,
            experiment_count=0,
            variance=0.0,
            has_contradiction=False,
        )
        assert status == EpistemicStatus.SPECULATIVE

    def test_one_experiment_returns_supported(self):
        """One experiment → SUPPORTED."""
        status = EpistemicStatus.from_evidence(
            has_evidence=True,
            experiment_count=1,
            variance=0.2,
            has_contradiction=False,
        )
        assert status == EpistemicStatus.SUPPORTED

    def test_replication_low_variance_returns_proven(self):
        """Replication + low variance → PROVEN."""
        status = EpistemicStatus.from_evidence(
            has_evidence=True,
            experiment_count=3,
            variance=0.05,
            has_contradiction=False,
        )
        assert status == EpistemicStatus.PROVEN

    def test_replication_high_variance_returns_supported(self):
        """Replication + high variance → SUPPORTED (not PROVEN)."""
        status = EpistemicStatus.from_evidence(
            has_evidence=True,
            experiment_count=3,
            variance=0.5,
            has_contradiction=False,
        )
        assert status == EpistemicStatus.SUPPORTED

    def test_contradiction_returns_unresolved(self):
        """Contradiction present → UNRESOLVED."""
        status = EpistemicStatus.from_evidence(
            has_evidence=True,
            experiment_count=2,
            variance=0.1,
            has_contradiction=True,
        )
        assert status == EpistemicStatus.UNRESOLVED

    def test_refuted_returns_refuted(self):
        """Explicit refutation → REFUTED."""
        status = EpistemicStatus.from_evidence(
            has_evidence=True,
            experiment_count=1,
            variance=0.1,
            has_contradiction=False,
            refuted=True,
        )
        assert status == EpistemicStatus.REFUTED


class TestHITLTransitions:
    """Test HITL approval requirements for transitions."""

    def test_speculative_to_supported_requires_hitl(self):
        """SPECULATIVE → SUPPORTED requires HITL."""
        assert requires_hitl_approval(
            EpistemicStatus.SPECULATIVE,
            EpistemicStatus.SUPPORTED
        ) is True

    def test_supported_to_proven_requires_hitl(self):
        """SUPPORTED → PROVEN requires HITL."""
        assert requires_hitl_approval(
            EpistemicStatus.SUPPORTED,
            EpistemicStatus.PROVEN
        ) is True

    def test_unresolved_to_refuted_requires_hitl(self):
        """UNRESOLVED → REFUTED requires HITL."""
        assert requires_hitl_approval(
            EpistemicStatus.UNRESOLVED,
            EpistemicStatus.REFUTED
        ) is True

    def test_same_status_no_hitl(self):
        """Same status → No HITL needed."""
        assert requires_hitl_approval(
            EpistemicStatus.SUPPORTED,
            EpistemicStatus.SUPPORTED
        ) is False

    def test_downgrade_no_hitl(self):
        """PROVEN → SUPPORTED (downgrade) → No HITL."""
        # Not in the required transitions set
        assert requires_hitl_approval(
            EpistemicStatus.PROVEN,
            EpistemicStatus.SUPPORTED
        ) is False


class TestScientificUncertainty:
    """Test scientific uncertainty calculation."""

    def test_no_samples_returns_max_uncertainty(self):
        """Zero samples → maximum uncertainty (1.0)."""
        uncertainty = calculate_scientific_uncertainty(
            variance=0.5,
            sensitivity_to_assumptions=0.3,
            sample_size=0,
            model_fit_error=0.1,
        )
        assert uncertainty == 1.0

    def test_high_variance_high_uncertainty(self):
        """High variance → higher uncertainty."""
        high = calculate_scientific_uncertainty(
            variance=0.9,
            sensitivity_to_assumptions=0.5,
            sample_size=10,
            model_fit_error=0.1,
        )
        low = calculate_scientific_uncertainty(
            variance=0.1,
            sensitivity_to_assumptions=0.5,
            sample_size=10,
            model_fit_error=0.1,
        )
        assert high > low

    def test_more_samples_lower_uncertainty(self):
        """More samples → lower uncertainty."""
        few = calculate_scientific_uncertainty(
            variance=0.5,
            sensitivity_to_assumptions=0.5,
            sample_size=5,
            model_fit_error=0.1,
        )
        many = calculate_scientific_uncertainty(
            variance=0.5,
            sensitivity_to_assumptions=0.5,
            sample_size=50,
            model_fit_error=0.1,
        )
        assert few > many

    def test_confidence_interval_empty_list(self):
        """Empty list → (0.0, 1.0) interval."""
        ci = compute_confidence_interval([])
        assert ci == (0.0, 1.0)

    def test_confidence_interval_single_value(self):
        """Single value → point interval."""
        ci = compute_confidence_interval([0.5])
        assert ci == (0.5, 0.5)

    def test_confidence_interval_multiple_values(self):
        """Multiple values → proper interval."""
        values = [0.4, 0.5, 0.6, 0.5, 0.55]
        ci = compute_confidence_interval(values)

        # Should contain the mean
        mean = sum(values) / len(values)
        assert ci[0] < mean < ci[1]


class TestEpistemicClassifierAgent:
    """Test epistemic classifier agent."""

    @pytest.fixture
    def classifier(self):
        return EpistemicClassifierAgent()

    def test_classify_no_evidence(self, classifier):
        """Claim with no evidence → SPECULATIVE."""
        result = classifier.classify_claim(
            claim={"claim_id": "C1", "content": "Test claim"},
            evidence=[],
            contradictions=[],
        )

        assert result.status == EpistemicStatus.SPECULATIVE
        assert "no experimental evidence" in result.justification.lower()

    def test_classify_with_evidence(self, classifier):
        """Claim with evidence → SUPPORTED."""
        result = classifier.classify_claim(
            claim={"claim_id": "C1", "content": "Test claim"},
            evidence=[{
                "hypothesis_id": "C1",
                "success": True,
                "result": {"value": 0.8},
            }],
            contradictions=[],
        )

        assert result.status == EpistemicStatus.SUPPORTED
        assert result.confidence > 0

    def test_output_includes_justification(self, classifier):
        """Output must include justification."""
        result = classifier.classify_claim(
            claim={"claim_id": "C1", "content": "Test"},
            evidence=[],
            contradictions=[],
        )

        assert isinstance(result.justification, str)
        assert len(result.justification) > 0

    def test_output_identifies_missing_evidence(self, classifier):
        """Output lists missing evidence."""
        result = classifier.classify_claim(
            claim={"claim_id": "C1", "content": "Test"},
            evidence=[{
                "hypothesis_id": "C1",
                "success": True,
                "result": {"value": 0.5},
            }],
            contradictions=[],
        )

        assert isinstance(result.missing_evidence, list)
        # Should mention replication needed
        assert any("replication" in me.lower() for me in result.missing_evidence)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
