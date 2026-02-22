"""
Brainstorm → MC Design Bridge Tests

These tests verify the epistemic firewall between the speculative lane
and the grounded lane, specifically:

1. SpeculativeAgent produces typed ExperimentHints
2. VerifyAgent consumes hints for experiment design
3. ExperimentSpec rejects speculative residue
4. Steward guard rejects hints in evidence payload
"""

import pytest

# =============================================================================
# Type Tests
# =============================================================================


def test_experiment_hints_type_creation():
    """ExperimentHints can be created with tight typing."""
    from src.montecarlo.types import ExperimentHints, PriorSuggestion

    hints = ExperimentHints(
        claim_id="claim-1",
        candidate_mechanisms=["mechanism A", "mechanism B"],
        discriminative_predictions=["If A, then X; if B, then Y"],
        sensitivity_axes=["temperature", "dose"],
        prior_suggestions=[PriorSuggestion(domain="pharmacology", parallel="dose-response curve")],
        falsification_criteria=["observe X under condition Z"],
    )

    assert hints.claim_id == "claim-1"
    assert hints.epistemic_status == "speculative"
    assert len(hints.candidate_mechanisms) == 2
    assert len(hints.prior_suggestions) == 1


def test_experiment_hints_digest_is_stable():
    """Digest is deterministic for audit trail reproducibility."""
    from src.montecarlo.types import ExperimentHints

    hints1 = ExperimentHints(
        claim_id="claim-1",
        sensitivity_axes=["temp", "dose"],
    )
    hints2 = ExperimentHints(
        claim_id="claim-1",
        sensitivity_axes=["dose", "temp"],  # Different order
    )

    # Digests should be equal (sorted internally)
    assert hints1.digest() == hints2.digest()


def test_experiment_hints_digest_differs_for_different_content():
    """Different hints produce different digests."""
    from src.montecarlo.types import ExperimentHints

    hints1 = ExperimentHints(claim_id="claim-1", sensitivity_axes=["temp"])
    hints2 = ExperimentHints(claim_id="claim-1", sensitivity_axes=["dose"])

    assert hints1.digest() != hints2.digest()


# =============================================================================
# ExperimentSpec No-Residue Guard Tests
# =============================================================================


def test_experiment_spec_rejects_experiment_hints_field():
    """ExperimentSpec cannot contain experiment_hints field (no-residue)."""
    from src.montecarlo.types import ExperimentSpec

    with pytest.raises(ValueError, match="INVARIANT VIOLATION.*experiment_hints"):
        ExperimentSpec(
            claim_id="claim-1",
            hypothesis="test",
            template_id="numeric_consistency",
            experiment_hints={"some": "data"},
        )


def test_experiment_spec_rejects_speculative_context_field():
    """ExperimentSpec cannot contain speculative_context field (no-residue)."""
    from src.montecarlo.types import ExperimentSpec

    with pytest.raises(ValueError, match="INVARIANT VIOLATION.*speculative_context"):
        ExperimentSpec(
            claim_id="claim-1",
            hypothesis="test",
            template_id="numeric_consistency",
            speculative_context={"alternatives": []},
        )


def test_experiment_spec_rejects_epistemic_status_field():
    """ExperimentSpec cannot contain epistemic_status field (no-residue)."""
    from src.montecarlo.types import ExperimentSpec

    with pytest.raises(ValueError, match="INVARIANT VIOLATION.*epistemic_status"):
        ExperimentSpec(
            claim_id="claim-1",
            hypothesis="test",
            template_id="numeric_consistency",
            epistemic_status="speculative",
        )


def test_experiment_spec_rejects_nested_speculative_content():
    """ExperimentSpec rejects nested dicts with epistemic_status=speculative."""
    from src.montecarlo.types import ExperimentSpec

    with pytest.raises(ValueError, match="INVARIANT VIOLATION.*[Ss]peculative"):
        ExperimentSpec(
            claim_id="claim-1",
            hypothesis="test",
            template_id="numeric_consistency",
            scope_lock_id="scope-1",
            params={"nested": {"epistemic_status": "speculative"}},
        )


def test_experiment_spec_accepts_clean_spec():
    """ExperimentSpec accepts well-formed specs without speculative residue."""
    from src.montecarlo.types import ExperimentSpec

    spec = ExperimentSpec(
        claim_id="claim-1",
        hypothesis="Verify that X holds",
        template_id="numeric_consistency",
        scope_lock_id="scope-1",
        params={"claimed_value": 0.5, "observed_values": [0.4, 0.5, 0.6]},
        assumptions={"independence_assumed": True},
    )

    assert spec.claim_id == "claim-1"
    assert spec.template_id == "numeric_consistency"


# =============================================================================
# SpeculativeAgent Hint Extraction Tests
# =============================================================================


def test_speculative_agent_extract_experiment_hints():
    """SpeculativeAgent._extract_experiment_hints produces typed hints."""
    from src.agents.speculative_agent import SpeculativeAgent
    from src.montecarlo.types import ExperimentHints

    agent = SpeculativeAgent()

    spec_results = {
        "claim-1": {
            "alternatives": [
                {"mechanism": "M1", "testable_prediction": "P1"},
                {"mechanism": "M2", "testable_prediction": "P2"},
            ],
            "analogies": [
                {"domain": "physics", "parallel": "wave-particle duality"},
            ],
            "edge_cases": ["low temperature", "high dose"],
            "epistemic_status": "speculative",
        }
    }

    hints = agent._extract_experiment_hints(spec_results)

    assert "claim-1" in hints
    h = hints["claim-1"]
    assert isinstance(h, ExperimentHints)
    assert h.epistemic_status == "speculative"
    assert h.candidate_mechanisms == ["M1", "M2"]
    assert h.sensitivity_axes == ["low temperature", "high dose"]
    assert len(h.prior_suggestions) == 1
    assert h.prior_suggestions[0].domain == "physics"


def test_speculative_agent_hints_have_digests():
    """Extracted hints have computable digests for audit trail."""
    from src.agents.speculative_agent import SpeculativeAgent

    agent = SpeculativeAgent()

    spec_results = {
        "claim-1": {
            "alternatives": [{"mechanism": "M1"}],
            "analogies": [],
            "edge_cases": ["edge1"],
        }
    }

    hints = agent._extract_experiment_hints(spec_results)

    # Digest should be a 16-char hex string
    digest = hints["claim-1"].digest()
    assert len(digest) == 16
    assert all(c in "0123456789abcdef" for c in digest)


# =============================================================================
# Steward Guard Tests (hints in evidence must be rejected)
# =============================================================================


def test_steward_rejects_experiment_hints_in_evidence_via_epistemic_status():
    """Steward guard catches hints leaked into evidence payload."""
    from src.agents.ontology_steward import q_insert_validation_evidence

    ev = {
        "claim_id": "claim-1",
        "execution_id": "exec-1",
        "template_id": "numeric_consistency",
        "template_qid": "numeric_consistency@v1",
        "scope_lock_id": "lock-1",
        "success": True,
        "confidence_score": 0.9,
        # Leaking hints into evidence (should be caught)
        "experiment_hints": {
            "claim_id": "claim-1",
            "sensitivity_axes": ["temp"],
            "epistemic_status": "speculative",
        },
    }

    with pytest.raises(ValueError, match="CRITICAL: Attempted to persist speculative"):
        q_insert_validation_evidence("sess-1", ev)


def test_steward_rejects_raw_speculative_context_in_evidence():
    """Steward guard catches speculative_context leaked into evidence."""
    from src.agents.ontology_steward import q_insert_validation_evidence

    ev = {
        "claim_id": "claim-1",
        "execution_id": "exec-1",
        "template_id": "numeric_consistency",
        "template_qid": "numeric_consistency@v1",
        "scope_lock_id": "lock-1",
        "success": True,
        "speculative_context": {
            "alternatives": [],
            "epistemic_status": "speculative",
        },
    }

    with pytest.raises(ValueError, match="CRITICAL: Attempted to persist speculative"):
        q_insert_validation_evidence("sess-1", ev)


# =============================================================================
# Integration: VerifyAgent uses hints
# =============================================================================


def test_verify_agent_design_uses_hints_for_template_selection():
    """VerifyAgent selects sensitivity_suite when hints have sensitivity_axes."""
    import asyncio

    from src.agents.base_agent import AgentContext
    from src.agents.verify_agent import VerifyAgent
    from src.montecarlo.types import ExperimentHints

    agent = VerifyAgent()

    context = AgentContext(
        graph_context={
            "experiment_hints": {
                "claim-1": ExperimentHints(
                    claim_id="claim-1",
                    sensitivity_axes=["temperature", "pressure"],
                ),
            },
        }
    )

    claim = {"claim_id": "claim-1", "content": "Test claim"}

    spec = asyncio.run(agent._design_experiment_spec(claim, context))

    # Should select sensitivity_suite due to sensitivity_axes
    assert spec is not None
    assert spec.template_id == "sensitivity_suite"
    assert "sensitivity_axes" in spec.params


def test_verify_agent_design_falls_back_without_hints():
    """VerifyAgent uses default template when no hints available."""
    import asyncio

    from src.agents.base_agent import AgentContext
    from src.agents.verify_agent import VerifyAgent

    agent = VerifyAgent()

    context = AgentContext(graph_context={})  # No hints

    claim = {"claim_id": "claim-2", "content": "Test claim without hints"}

    spec = asyncio.run(agent._design_experiment_spec(claim, context))

    # Should use default template
    assert spec is not None
    assert spec.template_id == "numeric_consistency"
