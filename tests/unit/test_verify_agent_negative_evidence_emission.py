
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base_agent import AgentContext
from src.agents.verify_agent import VerifyAgent
from src.montecarlo.template_metadata import EpistemicSemantics, TemplateSpec
from src.montecarlo.templates import TemplateExecution
from src.montecarlo.types import ExperimentSpec


@pytest.fixture
def mock_context():
    ctx = MagicMock(spec=AgentContext)
    ctx.graph_context = {
        "template_executions": [],
        "evidence": [],
        "negative_evidence": []
    }
    return ctx

@pytest.fixture
def agent():
    return VerifyAgent()

@pytest.fixture
def experiment_spec():
    return ExperimentSpec(
        claim_id="test_claim",
        hypothesis="test hypothesis",
        template_id="bootstrap_ci",
        scope_lock_id="scope-123",
        params={"data": [1, 2, 3]}
    )

@pytest.fixture
def mock_registry_spec():
    with patch("src.agents.verify_agent.VERSIONED_REGISTRY") as mock_reg:
        yield mock_reg

@pytest.mark.asyncio
async def test_emit_negative_evidence_refute(agent, mock_context, experiment_spec, mock_registry_spec):
    """Test emission of negative evidence with 'refute' role."""

    # Setup Mocks
    agent._design_experiment_spec = AsyncMock(return_value=experiment_spec)

    # Mock Execution Result
    execution = TemplateExecution(
        execution_id="exec-123",
        template_qid="bootstrap_ci@1.0.0",
        template_id="bootstrap_ci",
        claim_id="test_claim",
        params={},
        result={"estimate": 0.0},
        success=True,
        runtime_ms=100,
        warnings=[]
    )
    agent._codeact_execute_template = MagicMock(return_value=execution)

    # Mock MCResult (supports_claim = False)
    # We must patch _determine_support or ensure raw result leads to False
    agent._determine_support = MagicMock(return_value=False)
    # Mock Feynman checks to pass (so we don't get distracted by fragility)
    agent._feynman_checks = MagicMock(return_value={"all_pass": True, "checks": {}})

    # Mock Registry Spec with Refute Semantics
    mock_spec = MagicMock(spec=TemplateSpec)
    mock_spec.template_id = "bootstrap_ci"
    mock_spec.epistemic = EpistemicSemantics(
        instrument="falsification",
        negative_role_on_fail="refute",
        default_failure_mode="sign_flip",
        strength_model="binary_default"
    )
    mock_registry_spec.get_spec.return_value = mock_spec

    # Run
    await agent.run_mc_pipeline({"claim_id": "test_claim"}, mock_context)

    # Assertions
    neg_ev_list = mock_context.graph_context.get("negative_evidence", [])
    assert len(neg_ev_list) == 1
    neg_ev = neg_ev_list[0]

    assert neg_ev["role"] == "refute"
    assert neg_ev["failure_mode"] == "sign_flip"
    assert neg_ev["strength"] == 1.0
    assert neg_ev["template_qid"] == "bootstrap_ci@1.0.0"

    # Ensure NO positive evidence emitted
    pos_ev_list = mock_context.graph_context.get("evidence", [])
    assert len(pos_ev_list) == 0

@pytest.mark.asyncio
async def test_emit_negative_evidence_replicate(agent, mock_context, experiment_spec, mock_registry_spec):
    """Test emission of negative evidence with 'replicate' role (failed replication)."""

    # Setup Mocks
    agent._design_experiment_spec = AsyncMock(return_value=experiment_spec)

    execution = TemplateExecution(
        execution_id="exec-rep-1",
        template_qid="replication_machinery@1.0.0",
        template_id="replication_machinery",
        claim_id="test_claim",
        params={},
        result={"variance": 0.01}, # Low variance
        success=True,
        runtime_ms=100,
        warnings=[]
    )
    agent._codeact_execute_template = MagicMock(return_value=execution)
    agent._determine_support = MagicMock(return_value=False)
    agent._feynman_checks = MagicMock(return_value={"all_pass": True, "checks": {}})

    # Mock Registry Spec
    mock_spec = MagicMock(spec=TemplateSpec)
    mock_spec.template_id = "replication_machinery"
    mock_spec.epistemic = EpistemicSemantics(
        instrument="replication",
        negative_role_on_fail="replicate",
        default_failure_mode="null_effect",
        strength_model="ci_proximity_to_null"
    )
    mock_registry_spec.get_spec.return_value = mock_spec

    # Run
    await agent.run_mc_pipeline({"claim_id": "test_claim"}, mock_context)

    # Assertions
    neg_ev = mock_context.graph_context["negative_evidence"][0]
    assert neg_ev["role"] == "replicate"
    assert neg_ev["strength"] < 1.0 # Due to ci_proximity_to_null model with variance > 0
    assert 0.0 < neg_ev["strength"]

@pytest.mark.asyncio
async def test_emit_positive_evidence(agent, mock_context, experiment_spec, mock_registry_spec):
    """Test normal positive evidence emission."""

    agent._design_experiment_spec = AsyncMock(return_value=experiment_spec)

    execution = TemplateExecution(
        execution_id="exec-pos",
        template_qid="t@1",
        template_id="t",
        claim_id="c",
        params={},
        result={},
        success=True,
        runtime_ms=10,
        warnings=[]
    )
    agent._codeact_execute_template = MagicMock(return_value=execution)
    agent._determine_support = MagicMock(return_value=True) # Supports!
    agent._feynman_checks = MagicMock(return_value={"all_pass": True, "checks": {}})

    # Registry shouldn't even be called for semantics on positive path (currently)
    # But if it were, it shouldn't matter.

    await agent.run_mc_pipeline({"claim_id": "test_claim"}, mock_context)

    assert len(mock_context.graph_context["evidence"]) == 1
    assert len(mock_context.graph_context.get("negative_evidence", [])) == 0

@pytest.mark.asyncio
async def test_no_emission_on_execution_failure(agent, mock_context, experiment_spec):
    """Test that execution failure emits nothing."""

    agent._design_experiment_spec = AsyncMock(return_value=experiment_spec)

    execution = TemplateExecution(
        execution_id="exec-fail",
        template_qid="t@1",
        template_id="t",
        claim_id="c",
        params={},
        result={"error": "boom"},
        success=False, # FAILED
        runtime_ms=10,
        warnings=[]
    )
    agent._codeact_execute_template = MagicMock(return_value=execution)

    await agent.run_mc_pipeline({"claim_id": "test_claim"}, mock_context)

    assert len(mock_context.graph_context.get("evidence", [])) == 0
    assert len(mock_context.graph_context.get("negative_evidence", [])) == 0
