"""SuperHyperion Agents

v2.1: Full 13-step scientific reasoning pipeline.
"""

from src.agents.base_agent import AgentContext, BaseAgent
from src.agents.belief_agent import BeliefMaintenanceAgent, belief_agent
from src.agents.benchmark_agent import BenchmarkAgent, benchmark_agent

# v2.1 Pipeline Agents
from src.agents.clarifier_agent import ClarifierAgent, clarifier_agent
from src.agents.codeact_executor import CodeActExecutor, codeact, execute_python
from src.agents.decomposer_agent import DecomposerAgent, decomposer_agent
from src.agents.grounding_agent import GroundingAgent, grounding_agent
from src.agents.integrator_agent import IntegratorAgent, integrator_agent
from src.agents.meta_critic_agent import MetaCriticAgent, meta_critic_agent
from src.agents.ontology_steward import OntologySteward, ontology_steward
from src.agents.socratic_agent import SocraticDebateAgent, socratic_agent
from src.agents.speculative_agent import SpeculativeAgent, speculative_agent
from src.agents.uncertainty_agent import UncertaintyAgent, uncertainty_agent
from src.agents.validator_agent import ValidatorAgent, validator_agent
from src.agents.visual_agent import VisualEvidenceAgent, visual_agent

__all__ = [
    # Base
    "BaseAgent",
    "AgentContext",
    "CodeActExecutor",
    "codeact",
    "execute_python",
    # Legacy agents
    "BeliefMaintenanceAgent",
    "belief_agent",
    "SocraticDebateAgent",
    "socratic_agent",
    "VisualEvidenceAgent",
    "visual_agent",
    # v2.1 Pipeline agents
    "ClarifierAgent",
    "clarifier_agent",
    "DecomposerAgent",
    "decomposer_agent",
    "GroundingAgent",
    "grounding_agent",
    "SpeculativeAgent",
    "speculative_agent",
    "ValidatorAgent",
    "validator_agent",
    "BenchmarkAgent",
    "benchmark_agent",
    "UncertaintyAgent",
    "uncertainty_agent",
    "MetaCriticAgent",
    "meta_critic_agent",
    "IntegratorAgent",
    "integrator_agent",
    "OntologySteward",
    "ontology_steward",
]
