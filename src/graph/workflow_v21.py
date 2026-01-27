"""
LangGraph v2.1 Workflow Definition

13-step scientific reasoning pipeline with dual-lane architecture.
Implements CodeAct as belief gatekeeper and HITL gates.
"""

from typing import Literal, Dict, Any
import logging

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.graph.state import AgentState, NodeType, create_initial_state
from src.agents import (
    clarifier_agent,
    decomposer_agent,
    grounding_agent,
    speculative_agent,
    validator_agent,
    benchmark_agent,
    uncertainty_agent,
    meta_critic_agent,
    integrator_agent,
    ontology_steward,
    socratic_agent,
)
from src.epistemic import EpistemicClassifierAgent
from src.hitl import EpistemicApprovalGate, HighImpactWriteCheckpoint, audit_log
from src.config import config

logger = logging.getLogger(__name__)


# =============================================================================
# v2.1 Node Functions
# =============================================================================

async def clarify_node(state: AgentState) -> AgentState:
    """Step 2: Clarify hypothesis into testable form."""
    logger.info("v2.1: Clarify Node")
    state["current_node"] = NodeType.CLARIFY.value
    state["epistemic_mode"] = "speculative"
    
    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.messages = state["messages"]
    context.graph_context = state.get("graph_context", {})
    
    result = await clarifier_agent.run(context)
    
    state["graph_context"] = result.graph_context
    return state


async def decompose_node(state: AgentState) -> AgentState:
    """Step 3: Decompose hypothesis into atomic claims."""
    logger.info("v2.1: Decompose Node")
    state["current_node"] = NodeType.DECOMPOSE.value
    
    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    context.current_hypothesis = state["graph_context"].get(
        "clarified_hypothesis", {}
    ).get("clarified_hypothesis", state["query"])
    
    result = await decomposer_agent.run(context)
    
    state["graph_context"] = result.graph_context
    state["atomic_claims"] = result.graph_context.get("atomic_claims", [])
    return state


async def ground_node(state: AgentState) -> AgentState:
    """Step 4: Constraint-anchored grounding from TypeDB."""
    logger.info("v2.1: Grounding Node (entering grounded lane)")
    state["current_node"] = NodeType.GROUND.value
    state["epistemic_mode"] = "grounded"
    
    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    
    result = await grounding_agent.run(context)
    
    state["grounded_context"] = result.graph_context.get("grounded_context", {})
    state["graph_context"] = result.graph_context
    return state


async def speculate_node(state: AgentState) -> AgentState:
    """Step 5: Generate speculative alternatives."""
    logger.info("v2.1: Speculative Node (speculative lane)")
    state["current_node"] = NodeType.SPECULATE.value
    # Note: stays in current mode, output is tagged as speculative
    
    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    
    result = await speculative_agent.run(context)
    
    state["speculative_context"] = result.graph_context.get("speculative_context", {})
    state["graph_context"] = result.graph_context
    return state


async def validate_node(state: AgentState) -> AgentState:
    """
    Step 6: CodeAct validation - THE BELIEF GATEKEEPER.
    
    CRITICAL: Only this node produces Evidence objects.
    No belief update is legal without Evidence.authorizes_update() == True.
    """
    logger.info("v2.1: Validate Node (BELIEF GATEKEEPER)")
    state["current_node"] = NodeType.VALIDATE.value
    state["epistemic_mode"] = "grounded"
    
    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    context.code_results = state.get("code_executions", [])
    
    result = await validator_agent.run(context)
    
    state["evidence"] = result.graph_context.get("evidence", [])
    state["code_executions"] = result.code_results
    state["graph_context"] = result.graph_context
    return state


async def critique_node(state: AgentState) -> AgentState:
    """Step 7: Socratic critique (cannot reduce entropy directly)."""
    logger.info("v2.1: Critique Node")
    state["current_node"] = NodeType.CRITIQUE.value
    
    # Use existing socratic agent for critique
    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    context.messages = state["messages"]
    
    result = await socratic_agent.run(context)
    
    state["critique"] = result.response
    state["graph_context"] = result.graph_context
    
    # NOTE: Critique CANNOT reduce entropy directly
    # It can only propose counter-evidence and alternatives
    return state


async def benchmark_node(state: AgentState) -> AgentState:
    """Step 9: Score against ground truth."""
    logger.info("v2.1: Benchmark Node")
    state["current_node"] = NodeType.BENCHMARK.value
    
    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    
    result = await benchmark_agent.run(context)
    
    state["graph_context"] = result.graph_context
    return state


async def uncertainty_node(state: AgentState) -> AgentState:
    """Step 10: Compute scientific uncertainty."""
    logger.info("v2.1: Uncertainty Node")
    state["current_node"] = NodeType.UNCERTAINTY.value
    
    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    
    result = await uncertainty_agent.run(context)
    
    # Update scientific uncertainty (NOT dialectical entropy)
    uncertainty_data = result.graph_context.get("uncertainty", {})
    if uncertainty_data:
        total_values = [u.get("total", 0.5) for u in uncertainty_data.values()]
        avg_uncertainty = sum(total_values) / len(total_values) if total_values else 0.5
        state["scientific_uncertainty"] = {
            "average": avg_uncertainty,
            "per_claim": uncertainty_data,
        }
    
    state["graph_context"] = result.graph_context
    return state


async def meta_critic_node(state: AgentState) -> AgentState:
    """Step 11: Detect systemic bias and failure modes."""
    logger.info("v2.1: Meta-Critic Node")
    state["current_node"] = NodeType.META_CRITIC.value
    
    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    
    result = await meta_critic_agent.run(context)
    
    state["graph_context"] = result.graph_context
    return state


async def epistemic_gate_node(state: AgentState) -> AgentState:
    """Step 9.5: HITL gate for epistemic transitions."""
    logger.info("v2.1: Epistemic Gate Node (HITL)")
    
    gate = EpistemicApprovalGate()
    classifier = EpistemicClassifierAgent()
    
    pending_decisions = []
    classifications = state["graph_context"].get("classifications", [])
    
    for classification in classifications:
        gate_context = {
            "claim_id": classification.get("claim_id"),
            "current_status": "speculative",  # Default
            "proposed_status": classification.get("status"),
            "confidence": classification.get("confidence", 0.0),
            "evidence": state.get("evidence", []),
        }
        
        if gate.should_trigger(gate_context):
            pending = gate.create_pending_item(gate_context)
            pending_decisions.append(pending.to_dict())
            audit_log.log_gate_triggered(
                claim_id=classification.get("claim_id", "unknown"),
                gate_type="epistemic",
                trigger_reason=f"Transition to {classification.get('status')}"
            )
    
    state["pending_hitl_decisions"] = pending_decisions
    return state


async def integrate_node(state: AgentState) -> AgentState:
    """Step 12: Synthesize dual outputs."""
    logger.info("v2.1: Integrate Node")
    state["current_node"] = NodeType.INTEGRATE.value
    
    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    context.response = state.get("response")
    
    result = await integrator_agent.run(context)
    
    state["grounded_response"] = result.graph_context.get("grounded_response")
    state["speculative_alternatives"] = result.graph_context.get("speculative_alternatives", [])
    state["response"] = result.response
    state["graph_context"] = result.graph_context
    return state


async def impact_gate_node(state: AgentState) -> AgentState:
    """Step 10.5: HITL gate for high-impact writes."""
    logger.info("v2.1: Impact Gate Node (HITL)")
    
    gate = HighImpactWriteCheckpoint()
    
    # Check each claim that passed epistemic gate
    approved = state.get("approved_transitions", [])
    
    for transition in approved:
        gate_context = {
            "claim_id": transition.get("claim_id"),
            "current_status": transition.get("current_status"),
            "proposed_status": transition.get("proposed_status"),
            "new_confidence": transition.get("confidence", 0.0),
            "old_confidence": 0.0,
            "graph_centrality": 0.3,  # Would be computed from graph
            "downstream_dependency_count": 5,  # Would be computed
        }
        
        if gate.should_trigger(gate_context):
            pending = gate.create_pending_item(gate_context)
            state["pending_hitl_decisions"].append(pending.to_dict())
    
    return state


async def steward_node(state: AgentState) -> AgentState:
    """Step 13: Update ontology with vetted knowledge."""
    logger.info("v2.1: Ontology Steward Node")
    state["current_node"] = NodeType.STEWARD.value
    
    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    
    result = await ontology_steward.run(context)
    
    state["graph_context"] = result.graph_context
    return state


# =============================================================================
# Conditional Edge Functions
# =============================================================================

def check_needs_more_validation(state: AgentState) -> Literal["validate", "critique"]:
    """Check if more validation experiments are needed."""
    evidence = state.get("evidence", [])
    successful = sum(1 for e in evidence if e.get("success", False))
    
    if successful < 1:
        return "validate"
    return "critique"


def check_needs_experimental_design(state: AgentState) -> Literal["experimental_design", "epistemic_gate"]:
    """Check if experimental design is needed."""
    uncertainty = state.get("scientific_uncertainty", {})
    avg = uncertainty.get("average", 0.5)
    
    if avg > 0.6:
        return "experimental_design"
    return "epistemic_gate"


def check_hitl_pending(state: AgentState) -> Literal["integrate", "wait_hitl"]:
    """Check if HITL decisions are pending."""
    pending = state.get("pending_hitl_decisions", [])
    if pending:
        return "wait_hitl"
    return "integrate"


def check_high_impact(state: AgentState) -> Literal["impact_gate", "steward"]:
    """Check if high-impact gate is needed."""
    # Simplified check - in production would compute impact score
    return "steward"


# =============================================================================
# Graph Builder
# =============================================================================

def build_v21_workflow() -> StateGraph:
    """
    Build the v2.1 LangGraph workflow.
    
    13-Step Pipeline:
        1. User Input
        2. Clarify
        3. Decompose
        ┌─────────────────┐
        │   (parallel)    │
        │ 4. Ground       │
        │ 5. Speculate    │
        └─────────────────┘
        6. Validate (BELIEF GATEKEEPER)
        7. Critique
        8. [Experimental Design if needed]
        9. Benchmark
        10. Uncertainty
        11. Meta-Critic
        9.5. Epistemic Gate (HITL)
        12. Integrate (dual outputs)
        10.5. Impact Gate (HITL)
        13. Ontology Steward
        END
    """
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("clarify", clarify_node)
    workflow.add_node("decompose", decompose_node)
    workflow.add_node("ground", ground_node)
    workflow.add_node("speculate", speculate_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("critique", critique_node)
    workflow.add_node("benchmark", benchmark_node)
    workflow.add_node("uncertainty", uncertainty_node)
    workflow.add_node("meta_critic", meta_critic_node)
    workflow.add_node("epistemic_gate", epistemic_gate_node)
    workflow.add_node("integrate", integrate_node)
    workflow.add_node("impact_gate", impact_gate_node)
    workflow.add_node("steward", steward_node)
    
    # Set entry point
    workflow.set_entry_point("clarify")
    
    # Linear edges (speculative lane)
    workflow.add_edge("clarify", "decompose")
    workflow.add_edge("decompose", "ground")
    workflow.add_edge("ground", "speculate")
    
    # Speculative → Grounded lane (via CodeAct)
    workflow.add_edge("speculate", "validate")
    
    # Grounded lane
    workflow.add_edge("validate", "critique")
    workflow.add_edge("critique", "benchmark")
    workflow.add_edge("benchmark", "uncertainty")
    workflow.add_edge("uncertainty", "meta_critic")
    workflow.add_edge("meta_critic", "epistemic_gate")
    workflow.add_edge("epistemic_gate", "integrate")
    
    # Final stages
    workflow.add_conditional_edges(
        "integrate",
        check_high_impact,
        {
            "impact_gate": "impact_gate",
            "steward": "steward",
        }
    )
    workflow.add_edge("impact_gate", "steward")
    workflow.add_edge("steward", END)
    
    return workflow


# Create compiled v2.1 workflow
memory_v21 = MemorySaver()
workflow_v21 = build_v21_workflow()
app_v21 = workflow_v21.compile(checkpointer=memory_v21)


async def run_v21_query(query: str, thread_id: str = "default") -> AgentState:
    """
    Run a query through the v2.1 workflow.
    
    Args:
        query: User's hypothesis to investigate
        thread_id: Thread ID for checkpointing
        
    Returns:
        Final agent state with dual outputs
    """
    initial_state = create_initial_state(query)
    cfg = {"configurable": {"thread_id": thread_id}}
    
    final_state = await app_v21.ainvoke(initial_state, cfg)
    return final_state


if __name__ == "__main__":
    import asyncio
    
    async def test_v21():
        result = await run_v21_query("Protein X inhibits pathway Y under condition Z")
        print(f"\n=== GROUNDED RESPONSE ===")
        print(result.get("grounded_response", {}).get("summary", "No grounded response"))
        print(f"\n=== SPECULATIVE ALTERNATIVES ===")
        for alt in result.get("speculative_alternatives", [])[:3]:
            print(f"- {alt.get('hypothesis', 'Unknown')}")
        print(f"\nScientific Uncertainty: {result.get('scientific_uncertainty', {})}")
    
    asyncio.run(test_v21())
