
import pytest
from unittest.mock import MagicMock
from typing import Dict, Any

from src.agents.verify_agent import VerifyAgent
from src.agents.base_agent import AgentContext
from src.montecarlo.templates import TemplateRegistry, TemplateExecution
from src.montecarlo.types import ExperimentSpec
from src.graph.state import Evidence

from pydantic import BaseModel, ConfigDict
class MockParams(BaseModel):
    model_config = ConfigDict(extra="allow")
    data: list = []
    simulate_fragility: bool = False
    simulate_bad_ess: bool = False

class MockTemplate:
    template_id = "mock_template"
    ParamModel = MockParams
    description = "Mock template for testing"
    is_write_template = False
    def validate(self, params): return MockParams(**params)

# Mock Registry and Templates
class MockRegistry(TemplateRegistry):
    def __init__(self):
        # STRICT MOCKING: Do not call super().__init__() to avoid default registrations
        self._templates = {}
        
        # Explicitly register mocks
        t1 = MockTemplate()
        t1.template_id = "bootstrap_ci"
        self.register(t1)
        
        t2 = MockTemplate()
        t2.template_id = "sensitivity_suite"
        self.register(t2)
        
        t3 = MockTemplate()
        t3.template_id = "bayesian_update"
        self.register(t3)
        
        t4 = MockTemplate()
        t4.template_id = "mock_template"
        self.register(t4)
        
        # Phase 14 Addition
        t5 = MockTemplate()
        t5.template_id = "citation_check"
        self.register(t5)        

    def run_template(self, template_id, params, context=None, caller_role="verify") -> TemplateExecution:
        # Simulate execution based on params to test fragility flags
        
        # Default success result
        result = {
            "estimate": 0.5,
            "ci_low": 0.4,
            "ci_high": 0.6,
            "variance": 0.01,
            "diagnostics": {"ess": 500, "converged": True, "toy_ok": True},
            "sensitivity": {"prior_widened_flips": False, "noise_model_flips": False},
            "summary": "Mock success"
        }
        
        # Simulate Fragility from params
        if params.get("simulate_fragility"):
            result["sensitivity"]["prior_widened_flips"] = True
            result["fragile"] = True
            
        # Simulate Bad Diagnostics
        if params.get("simulate_bad_ess"):
            result["diagnostics"]["ess"] = 100
            
        return TemplateExecution(
            execution_id="exec-mock",
            template_id=template_id,
            claim_id=context.get("claim_id", "unknown"),
            params=params,
            result=result,
            success=True,
            runtime_ms=10,
            warnings=[]
        )



@pytest.mark.asyncio
async def test_p13_verify_pipeline_happy_path():
    """Test full pipeline: Design -> Execute -> Analyze -> Evidence."""
    # Setup
    agent = VerifyAgent()
    agent.registry = MockRegistry()
    
    # Mock LLM design step to return a valid spec
    # Mock LLM design step to return a valid spec (async)
    async def mock_design(*args, **kwargs):
        return ExperimentSpec(
            claim_id="claim-1",
            hypothesis="Test hypothesis",
            template_id="bootstrap_ci",
            params={"data": [1,2,3]},
            units={"estimate": "kg"}
        )
    agent._design_experiment_spec = mock_design
    
    context = AgentContext(graph_context={
        "atomic_claims": [{"claim_id": "claim-1", "content": "Test Claim content"}],
        "hypothesis_id": "hyp-1"
    })
    
    # Run
    await agent.run(context)
    
    # Verify Artifacts
    executions = context.graph_context["template_executions"]
    evidence_list = context.graph_context["evidence"]
    
    assert len(executions) == 1
    assert len(evidence_list) == 1
    
    ev = evidence_list[0]
    # Check Phase 13 fields
    assert ev["is_fragile"] is False
    assert ev["feynman"]["all_pass"] is True
    assert ev["feynman"]["checks"]["dimensions"]["pass"] is True # Units matched
    assert ev["feynman"]["checks"]["diagnostics"]["pass"] is True # ESS 500 > 400

@pytest.mark.asyncio
async def test_p13_verify_fragility_detection():
    """Test that failed Feynman checks mark evidence as fragile."""
    agent = VerifyAgent()
    agent.registry = MockRegistry()
    
    # Mock LLM to request fragility simulation
    # Mock LLM to request fragility simulation
    async def mock_fragile_design(*args, **kwargs):
        return ExperimentSpec(
            claim_id="claim-fragile",
            hypothesis="Fragile hypothesis",
            template_id="sensitivity_suite",
            params={"simulate_fragility": True} # Trigger mock behavior
        )
    agent._design_experiment_spec = mock_fragile_design
    
    context = AgentContext(graph_context={
        "atomic_claims": [{"claim_id": "claim-fragile", "content": "Fragile Content"}],
        "hypothesis_id": "hyp-1"
    })
    
    await agent.run(context)
    
    ev = context.graph_context["evidence"][0]
    
    assert ev["is_fragile"] is True
    assert ev["feynman"]["all_pass"] is False
    assert ev["feynman"]["checks"]["sensitivity"]["pass"] is False # Prior flip detected

@pytest.mark.asyncio
async def test_p13_verify_diagnostic_failure():
    """Test that poor diagnostics (ESS < 400) triggers fragility."""
    agent = VerifyAgent()
    agent.registry = MockRegistry()
    
    async def mock_bad_diag_design(*args, **kwargs):
        return ExperimentSpec(
            claim_id="claim-bad-diag",
            hypothesis="Bad ESS",
            template_id="bayesian_update",
            params={"simulate_bad_ess": True}
        )
    agent._design_experiment_spec = mock_bad_diag_design
    
    context = AgentContext(graph_context={
        "atomic_claims": [{"claim_id": "claim-bad-diag", "content": "Bad ESS Content"}],
         "hypothesis_id": "hyp-1"
    })
    
    await agent.run(context)
    
    ev = context.graph_context["evidence"][0]
    
    # Should be marked fragile due to bad diagnostics
    assert ev["is_fragile"] is True
    assert ev["feynman"]["checks"]["diagnostics"]["pass"] is False
    assert "ESS=100" in ev["feynman"]["checks"]["diagnostics"]["reason"]

@pytest.mark.asyncio
async def test_p13_verify_budget_failure():
    """Test that runtime exceeding budget triggers fragility."""
    agent = VerifyAgent(max_budget_ms=5) # Tight budget
    agent.registry = MockRegistry()
    
    async def mock_slow_design(*args, **kwargs):
        return ExperimentSpec(
            claim_id="claim-slow",
            hypothesis="Slow Run",
            template_id="bootstrap_ci",
            params={"data": [1,2,3]}
        )
    agent._design_experiment_spec = mock_slow_design
    
    context = AgentContext(graph_context={
        "atomic_claims": [{"claim_id": "claim-slow", "content": "Slow Content"}],
         "hypothesis_id": "hyp-1"
    })
    
    # MockRegistry returns runtime_ms=10 which > 5
    await agent.run(context)
    
    ev = context.graph_context["evidence"][0]
    
    # Should be marked fragile due to budget
    assert ev["is_fragile"] is True
    assert ev["feynman"]["checks"]["budget"]["pass"] is False
    assert "Runtime" in ev["feynman"]["checks"]["budget"]["reason"]

@pytest.mark.asyncio
async def test_p13_verify_citation_check_registered_and_runs():
    """Verify citation_check template is reachable and runs."""
    agent = VerifyAgent()
    agent.registry = MockRegistry()

    async def mock_design(*args, **kwargs):
        return ExperimentSpec(
            claim_id="claim-cite",
            hypothesis="Must have citations",
            template_id="citation_check",
            params={"evidence_bundle": [{"claim_id": "claim-cite", "source": "paper-1"}], "claim_id": "claim-cite"},
            units={"estimate": "unit"}
        )

    agent._design_experiment_spec = mock_design

    context = AgentContext(graph_context={
        "atomic_claims": [{"claim_id": "claim-cite", "content": "Claim requiring citations"}],
        "hypothesis_id": "hyp-1"
    })

    await agent.run(context)

    ev = context.graph_context["evidence"][0]
    assert ev["template_id"] == "citation_check"
    assert "feynman" in ev

def test_registry_has_all_experiment_spec_templates():
    """Invariant: Registry must contain all templates defined in ExperimentSpec."""
    from src.montecarlo.templates import TemplateRegistry
    from src.montecarlo.types import ExperimentSpec
    
    # Use real registry for this test
    reg = TemplateRegistry()
    available = set(reg._templates.keys())
    
    # Extract Literal values from ExperimentSpec.template_id
    # Note: Depending on Pydantic version, this introspection might vary
    # For now, we trust the Pydantic v2 introspection or fallback
    try:
        # Pydantic v2
        field_info = ExperimentSpec.model_fields["template_id"]
        # Handle Union/Literal inspection
        if hasattr(field_info.annotation, "__args__"):
             required = set(field_info.annotation.__args__)
        else:
             # Fallback if simple type (unlikely for Literal)
             required = set()
    except Exception:
        # Fallback manual list if introspection is tricky in this env
        required = {
            "bootstrap_ci", "bayesian_update", "threshold_check", 
            "numeric_consistency", "sensitivity_suite", "contradiction_detect",
            "citation_check", "effect_direction"
        }
        
    assert required.issubset(available), f"Missing templates: {required - available}"
