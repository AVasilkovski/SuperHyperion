"""
v2.2 Hardening Tests (Fixed)

Verifies:
1. Template parameter bounds
2. Output contracts
3. Cap enforcement logic
4. Reground loop termination
5. Staged write intents
6. Steward-only write enforcement
7. Float determinism
"""

import math
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.agents.propose_agent import ProposeAgent
from src.agents.retrieval_gate import RetrievalQualityGate
from src.graph.state import Evidence
from src.montecarlo.templates import (
    BootstrapCIParams,
    BootstrapCITemplate,
    NumericConsistencyTemplate,
    registry,
)

# =============================================================================
# 1. Template Hardening Tests
# =============================================================================


@pytest.mark.asyncio
async def test_template_param_bounds():
    """Verify templates reject out-of-bound parameters."""
    template = BootstrapCITemplate()

    # Test n_bootstrap too high
    with pytest.raises(ValidationError):
        template.validate(
            {
                "data": [1.0, 2.0],
                "n_bootstrap": 10000,  # Max is 5000
                "confidence_level": 0.95,
            }
        )

    # Test n_bootstrap too low
    with pytest.raises(ValidationError):
        template.validate(
            {
                "data": [1.0, 2.0],
                "n_bootstrap": 10,  # Min is 100
                "confidence_level": 0.95,
            }
        )


@pytest.mark.asyncio
async def test_numeric_consistency_bounds():
    """Verify numeric consistency params."""
    template = NumericConsistencyTemplate()

    with pytest.raises(ValidationError):
        template.validate(
            {
                "claimed_value": 0.5,
                "observed_values": [],  # Min length 1
                "tolerance": 0.1,
            }
        )


@pytest.mark.asyncio
async def test_determinism():
    """Verify stochastic templates respect seed."""
    template = BootstrapCITemplate()
    params = BootstrapCIParams(data=[1.0, 2.0, 3.0, 4.0, 5.0], n_bootstrap=500, seed=42)

    # Run sync (templates are CPU-bound sync functions)
    run1 = template.run(params, {"session_id": "test"})
    run2 = template.run(params, {"session_id": "test"})

    # Float-tolerant comparison
    assert math.isclose(run1["estimate"], run2["estimate"], rel_tol=0, abs_tol=1e-9)
    assert math.isclose(run1["ci_low"], run2["ci_low"], rel_tol=0, abs_tol=1e-9)


# =============================================================================
# 2. Cap Enforcement Tests (ProposeAgent)
# =============================================================================


@pytest.mark.asyncio
async def test_cap_enforcement_logic():
    agent = ProposeAgent()

    # Scenario 1: Fragile claim -> Capped at SUPPORTED
    max_stat, reasons = agent._compute_max_allowed_status(
        claim_id="c1",
        fragility_report={"fragile": True, "fragile_claims": ["c1"]},
        meta_critique={"severity": "low"},
        contradictions={"unresolved_count": 0},
    )
    assert max_stat == "SUPPORTED"
    assert any("Fragile" in r for r in reasons)

    # Scenario 2: Critical severity -> Capped at SUPPORTED
    max_stat, reasons = agent._compute_max_allowed_status(
        claim_id="c1",
        fragility_report={"fragile": False},
        meta_critique={"severity": "critical"},
        contradictions={"unresolved_count": 0},
    )
    assert max_stat == "SUPPORTED"
    assert any("MetaCritic" in r for r in reasons)

    # Scenario 3: Unresolved contradictions -> Capped at UNRESOLVED
    max_stat, reasons = agent._compute_max_allowed_status(
        claim_id="c1",
        fragility_report={"fragile": False},
        meta_critique={"severity": "low"},
        contradictions={"unresolved_count": 1},
    )
    assert max_stat == "UNRESOLVED"
    assert any("Unresolved contradictions" in r for r in reasons)


# =============================================================================
# 3. Reground Loop Termination Tests
# =============================================================================


class MockContext:
    def __init__(self, attempts=0):
        self.graph_context = {"reground_attempts": attempts}


@pytest.mark.asyncio
async def test_reground_loop_termination():
    gate = RetrievalQualityGate()

    # Force _decide to always return 'reground'
    with patch.object(gate, "_decide", return_value="reground"):
        # Case 1: Under cap
        ctx = MockContext(attempts=0)
        await gate.run(ctx)
        assert ctx.graph_context["retrieval_decision"] == "reground"
        assert ctx.graph_context["reground_attempts"] == 1

        # Case 2: At cap (MAX=3)
        ctx = MockContext(attempts=3)
        await gate.run(ctx)
        # Should force speculate
        assert ctx.graph_context["retrieval_decision"] == "speculate"
        assert ctx.graph_context.get("retrieval_loop_capped") is True
        assert ctx.graph_context["reground_attempts"] == 3


# =============================================================================
# 4. Evidence Output Contract
# =============================================================================


def test_evidence_contract():
    """Verify Evidence dataclass output contracts."""
    # With explicit None uncertainty (v2.2 style)
    ev = Evidence(
        hypothesis_id="h1",
        claim_id="c1",
        template_id="test_tmpl",
        test_description="desc",
        execution_id="exec_1",
        result={},
        metrics={"val": 0.5},
        uncertainty=None,  # Explicitly optional
        success=True,
    )

    assert ev.authorizes_update() is True

    # Missing execution_id failure
    ev_no_id = Evidence(
        hypothesis_id="h1",
        claim_id="c1",
        template_id="test_tmpl",
        test_description="desc",
        execution_id="",  # Empty
        result={},
        success=True,
    )
    assert ev_no_id.authorizes_update() is False

    # Critical warning failure
    ev_warn = Evidence(
        hypothesis_id="h1",
        claim_id="c1",
        template_id="test_tmpl",
        test_description="desc",
        execution_id="exec_1",
        result={},
        warnings=["CRITICAL: Data corruption detected"],
        success=True,
    )
    assert ev_warn.authorizes_update() is False


# =============================================================================
# 5. Steward-Only Write Enforcement
# =============================================================================


class MockWriteTemplate(BootstrapCITemplate):
    template_id = "write_test_hardening"
    is_write_template = True
    description = "Mock write template"


@pytest.mark.asyncio
async def test_write_template_permissions():
    """Verify write templates fail for non-steward roles."""

    # Register real template instead of mocking to avoid TypeError
    tmpl = MockWriteTemplate()
    # Need to hack registry to allow re-registration if needed or just use unique ID
    registry._templates[tmpl.template_id] = tmpl

    # Needs valid params because validate is called if check fails (but it shouldn't be reached)
    # However we'll provide valid params just in case
    valid_params = {"data": [1.0, 2.0], "n_bootstrap": 100, "confidence_level": 0.95}

    # Use qualified template_id format (Phase 14.5 requirement)
    qualified_id = f"{tmpl.template_id}@1.0.0"

    # 1. Non-steward caller -> PermissionError
    with pytest.raises(PermissionError):
        registry.run_template(template_id=qualified_id, params=valid_params, caller_role="verify")

    # 2. Steward caller -> Success (or at least no PermissionError)
    # This might fail validation/run if params are wrong, but PermissionError shouldn't be raised
    result = registry.run_template(
        template_id=qualified_id, params=valid_params, caller_role="steward"
    )
    assert result.success is True
