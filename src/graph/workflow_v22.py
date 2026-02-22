"""
LangGraph v2.2 Workflow Definition

Implements v2.2 mandatory changes:
- retrieval_gate after ground (ground-only loop)
- verify/propose split (ValidatorAgent.A and .B)
- staged write intents (steward-only execution)
- monotonic step_index tracing
"""

import logging
import time

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agents import (
    benchmark_agent,
    clarifier_agent,
    decomposer_agent,
    grounding_agent,
    integrator_agent,
    meta_critic_agent,
    ontology_steward,
    socratic_agent,
    speculative_agent,
    uncertainty_agent,
)
from src.agents.propose_agent import propose_agent
from src.agents.retrieval_gate import retrieval_gate
from src.agents.verify_agent import verify_agent
from src.graph.state import AgentState, NodeType, create_initial_state
from src.hitl import EpistemicApprovalGate, HighImpactWriteCheckpoint, audit_log

logger = logging.getLogger(__name__)


# =============================================================================
# Trace Wrapper (Monotonic step_index)
# =============================================================================


def traced_node(node_name: str, phase: str = "execute"):
    """Decorator to enforce monotonic step_index and trace logging."""

    def decorator(fn):
        async def wrapped(state: AgentState) -> AgentState:
            # Increment step_index
            state["step_index"] = state.get("step_index", 0) + 1

            # Log trace
            if "traces" not in state:
                state["traces"] = []

            state["traces"].append(
                {
                    "step_index": state["step_index"],
                    "node": node_name,
                    "phase": phase,
                    "timestamp": time.time(),
                }
            )

            # Execute node
            return await fn(state)

        return wrapped

    return decorator


# =============================================================================
# v2.2 Node Functions
# =============================================================================


@traced_node("clarify", "speculative")
async def clarify_node(state: AgentState) -> AgentState:
    """Step 1: Clarify hypothesis into testable form."""
    logger.info("v2.2: Clarify Node")
    state["current_node"] = NodeType.CLARIFY.value
    state["epistemic_mode"] = "speculative"

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.messages = state["messages"]
    context.graph_context = state.get("graph_context", {})

    result = await clarifier_agent.run(context)
    state["graph_context"] = result.graph_context
    return state


@traced_node("decompose", "speculative")
async def decompose_node(state: AgentState) -> AgentState:
    """Step 2: Decompose hypothesis into atomic claims."""
    logger.info("v2.2: Decompose Node")
    state["current_node"] = NodeType.DECOMPOSE.value

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    context.current_hypothesis = (
        state["graph_context"]
        .get("clarified_hypothesis", {})
        .get("clarified_hypothesis", state["query"])
    )

    result = await decomposer_agent.run(context)
    state["graph_context"] = result.graph_context
    state["atomic_claims"] = result.graph_context.get("atomic_claims", [])
    return state


@traced_node("ground", "grounded")
async def ground_node(state: AgentState) -> AgentState:
    """Step 3: Constraint-anchored grounding from TypeDB."""
    logger.info("v2.2: Grounding Node")
    state["current_node"] = NodeType.GROUND.value
    state["epistemic_mode"] = "grounded"

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.graph_context = state.get("graph_context", {})

    # Check for refinement hints from retrieval gate
    refinement = state.get("retrieval_refinement")
    if refinement:
        context.graph_context["retrieval_refinement"] = refinement

    result = await grounding_agent.run(context)
    state["grounded_context"] = result.graph_context.get("grounded_context", {})
    state["graph_context"] = result.graph_context
    return state


@traced_node("retrieval_gate", "quality_check")
async def retrieval_gate_node(state: AgentState) -> AgentState:
    """Step 3.5: Quality gate for retrieval (NEW in v2.2)."""
    logger.info("v2.2: Retrieval Gate Node")

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    context.graph_context["reground_attempts"] = state.get("reground_attempts", 0)

    result = await retrieval_gate.run(context)

    state["retrieval_grade"] = result.graph_context.get("retrieval_grade", {})
    state["retrieval_decision"] = result.graph_context.get("retrieval_decision", "speculate")
    state["retrieval_refinement"] = result.graph_context.get("retrieval_refinement")
    state["reground_attempts"] = result.graph_context.get("reground_attempts", 0)
    state["graph_context"] = result.graph_context
    return state


@traced_node("speculate", "speculative")
async def speculate_node(state: AgentState) -> AgentState:
    """Step 4: Generate speculative alternatives."""
    logger.info("v2.2: Speculative Node")
    state["current_node"] = NodeType.SPECULATE.value

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.graph_context = state.get("graph_context", {})

    result = await speculative_agent.run(context)
    state["speculative_context"] = result.graph_context.get("speculative_context", {})
    state["graph_context"] = result.graph_context
    return state


@traced_node("verify", "grounded")
async def verify_node(state: AgentState) -> AgentState:
    """Step 5: Verify claims via template execution (ValidatorAgent.A)."""
    logger.info("v2.2: Verify Node (BELIEF GATEKEEPER)")
    state["current_node"] = "verify"
    state["epistemic_mode"] = "grounded"

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.graph_context = state.get("graph_context", {})

    result = await verify_agent.run(context)

    state["evidence"] = result.graph_context.get("evidence", [])
    state["template_executions"] = result.graph_context.get("template_executions", [])
    state["verification_report"] = result.graph_context.get("verification_report", {})
    state["fragility_report"] = result.graph_context.get("fragility_report", {})
    state["contradictions"] = result.graph_context.get("contradictions", {})
    state["graph_context"] = result.graph_context
    return state


@traced_node("critique", "critical")
async def critique_node(state: AgentState) -> AgentState:
    """Step 6: Socratic critique."""
    logger.info("v2.2: Critique Node")
    state["current_node"] = NodeType.CRITIQUE.value

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    context.messages = state["messages"]

    result = await socratic_agent.run(context)
    state["critique"] = result.response
    state["graph_context"] = result.graph_context
    return state


@traced_node("benchmark", "evaluate")
async def benchmark_node(state: AgentState) -> AgentState:
    """Step 7: Score against ground truth."""
    logger.info("v2.2: Benchmark Node")
    state["current_node"] = NodeType.BENCHMARK.value

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.graph_context = state.get("graph_context", {})

    result = await benchmark_agent.run(context)
    state["graph_context"] = result.graph_context
    return state


@traced_node("uncertainty", "evaluate")
async def uncertainty_node(state: AgentState) -> AgentState:
    """Step 8: Compute scientific uncertainty."""
    logger.info("v2.2: Uncertainty Node")
    state["current_node"] = NodeType.UNCERTAINTY.value

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.graph_context = state.get("graph_context", {})

    result = await uncertainty_agent.run(context)

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


@traced_node("meta_critic", "meta")
async def meta_critic_node(state: AgentState) -> AgentState:
    """Step 9: Detect systemic bias and failure modes."""
    logger.info("v2.2: Meta-Critic Node")
    state["current_node"] = NodeType.META_CRITIC.value

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.graph_context = state.get("graph_context", {})

    result = await meta_critic_agent.run(context)

    # Ensure structured meta_critique output
    meta_critique = result.graph_context.get("meta_critique", {})
    if not isinstance(meta_critique, dict):
        meta_critique = {"severity": "low", "findings": [], "notes": str(meta_critique)}
    state["meta_critique"] = meta_critique
    state["graph_context"] = result.graph_context
    return state


@traced_node("propose", "propose")
async def propose_node(state: AgentState) -> AgentState:
    """Step 10: Generate epistemic proposals with cap enforcement (ValidatorAgent.B)."""
    logger.info("v2.2: Propose Node")
    state["current_node"] = "propose"

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    context.graph_context["meta_critique"] = state.get("meta_critique", {})
    context.graph_context["fragility_report"] = state.get("fragility_report", {})
    context.graph_context["contradictions"] = state.get("contradictions", {})
    context.graph_context["evidence"] = state.get("evidence", [])
    context.graph_context["verification_report"] = state.get("verification_report", {})

    result = await propose_agent.run(context)

    state["epistemic_update_proposal"] = result.graph_context.get("epistemic_update_proposal", [])
    state["write_intents"] = result.graph_context.get("write_intents", [])
    state["graph_context"] = result.graph_context
    return state


@traced_node("epistemic_gate", "hitl")
async def epistemic_gate_node(state: AgentState) -> AgentState:
    """Step 11: HITL gate for epistemic transitions."""
    logger.info("v2.2: Epistemic Gate Node (HITL)")

    gate = EpistemicApprovalGate()
    pending_decisions = []

    proposals = state.get("epistemic_update_proposal", [])

    for proposal in proposals:
        if proposal.get("requires_hitl", False):
            gate_context = {
                "claim_id": proposal.get("claim_id"),
                "current_status": proposal.get("current_status"),
                "proposed_status": proposal.get("final_proposed_status"),
                "confidence": proposal.get("confidence", 0.0),
                "evidence": state.get("evidence", []),
                "cap_reasons": proposal.get("cap_reasons", []),
            }

            pending = gate.create_pending_item(gate_context)
            pending_decisions.append(pending.to_dict())
            audit_log.log_gate_triggered(
                claim_id=proposal.get("claim_id", "unknown"),
                gate_type="epistemic",
                trigger_reason=f"Transition to {proposal.get('final_proposed_status')}",
            )

    state["pending_hitl_decisions"] = pending_decisions
    return state


@traced_node("integrate", "synthesize")
async def integrate_node(state: AgentState) -> AgentState:
    """Step 12: Synthesize dual outputs."""
    logger.info("v2.2: Integrate Node")
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


@traced_node("impact_gate", "hitl")
async def impact_gate_node(state: AgentState) -> AgentState:
    """Step 13: HITL gate for high-impact writes."""
    logger.info("v2.2: Impact Gate Node (HITL)")

    gate = HighImpactWriteCheckpoint()

    write_intents = state.get("write_intents", [])

    for intent in write_intents:
        impact_score = intent.get("impact_score", 0)

        if impact_score > 0.5:  # High impact threshold
            gate_context = {
                "intent_id": intent.get("intent_id"),
                "intent_type": intent.get("intent_type"),
                "impact_score": impact_score,
            }

            pending = gate.create_pending_item(gate_context)
            state.setdefault("pending_hitl_decisions", []).append(pending.to_dict())

    return state


@traced_node("steward", "persist")
async def steward_node(state: AgentState) -> AgentState:
    """Step 14: Execute staged write intents (OntologySteward only)."""
    logger.info("v2.2: Ontology Steward Node")
    state["current_node"] = NodeType.STEWARD.value

    # Only execute intents that passed gates
    write_intents = state.get("write_intents", [])
    pending_hitl = state.get("pending_hitl_decisions", [])
    pending_ids = {p.get("intent_id") for p in pending_hitl if not p.get("approved", False)}

    # Filter to approved intents only
    approved_intents = [
        intent
        for intent in write_intents
        if intent.get("intent_id") not in pending_ids or not intent.get("requires_hitl", False)
    ]

    from src.agents.base_agent import AgentContext

    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    context.graph_context["approved_write_intents"] = approved_intents

    result = await ontology_steward.run(context)
    state["graph_context"] = result.graph_context

    return state


# =============================================================================
# Routing Functions
# =============================================================================


def route_retrieval(state: AgentState) -> str:
    """Route based on retrieval gate decision."""
    decision = state.get("retrieval_decision", "speculate")
    return "reground" if decision == "reground" else "speculate"


def check_high_impact(state: AgentState) -> str:
    """Check if high-impact gate is needed."""
    write_intents = state.get("write_intents", [])
    high_impact = any(i.get("impact_score", 0) > 0.5 for i in write_intents)
    return "impact_gate" if high_impact else "steward"


# =============================================================================
# Graph Builder
# =============================================================================


def build_v22_workflow() -> StateGraph:
    """
    Build the v2.2 LangGraph workflow.

    v2.2 Changes:
        - retrieval_gate after ground (ground-only loop)
        - verify/propose split
        - staged write intents
        - monotonic step_index tracing
    """
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("clarify", clarify_node)
    workflow.add_node("decompose", decompose_node)
    workflow.add_node("ground", ground_node)
    workflow.add_node("retrieval_gate", retrieval_gate_node)  # NEW
    workflow.add_node("speculate", speculate_node)
    workflow.add_node("verify", verify_node)  # NEW (replaces validate)
    workflow.add_node("critique", critique_node)
    workflow.add_node("benchmark", benchmark_node)
    workflow.add_node("uncertainty", uncertainty_node)
    workflow.add_node("meta_critic", meta_critic_node)
    workflow.add_node("propose", propose_node)  # NEW
    workflow.add_node("epistemic_gate", epistemic_gate_node)
    workflow.add_node("integrate", integrate_node)
    workflow.add_node("impact_gate", impact_gate_node)
    workflow.add_node("steward", steward_node)

    # Set entry point
    workflow.set_entry_point("clarify")

    # Edges: clarify -> decompose -> ground
    workflow.add_edge("clarify", "decompose")
    workflow.add_edge("decompose", "ground")

    # NEW: ground -> retrieval_gate with conditional loop
    workflow.add_edge("ground", "retrieval_gate")
    workflow.add_conditional_edges(
        "retrieval_gate",
        route_retrieval,
        {"reground": "ground", "speculate": "speculate"},
    )

    # Speculation then verification
    workflow.add_edge("speculate", "verify")

    # Grounded lane
    workflow.add_edge("verify", "critique")
    workflow.add_edge("critique", "benchmark")
    workflow.add_edge("benchmark", "uncertainty")
    workflow.add_edge("uncertainty", "meta_critic")

    # NEW: propose after meta_critic
    workflow.add_edge("meta_critic", "propose")
    workflow.add_edge("propose", "epistemic_gate")
    workflow.add_edge("epistemic_gate", "integrate")

    # Final stages
    workflow.add_conditional_edges(
        "integrate",
        check_high_impact,
        {"impact_gate": "impact_gate", "steward": "steward"},
    )
    workflow.add_edge("impact_gate", "steward")
    workflow.add_edge("steward", END)

    return workflow


# Create compiled v2.2 workflow
memory_v22 = MemorySaver()
workflow_v22 = build_v22_workflow()
app_v22 = workflow_v22.compile(checkpointer=memory_v22)


async def run_v22_query(query: str, thread_id: str = "default") -> AgentState:
    """
    Run a query through the v2.2 workflow.

    Args:
        query: User's hypothesis to investigate
        thread_id: Thread ID for checkpointing

    Returns:
        Final agent state with dual outputs
    """
    initial_state = create_initial_state(query)
    initial_state["step_index"] = 0
    initial_state["traces"] = []
    initial_state["write_intents"] = []

    cfg = {"configurable": {"thread_id": thread_id}}

    final_state = await app_v22.ainvoke(initial_state, cfg)
    return final_state


if __name__ == "__main__":
    import asyncio

    async def test_v22():
        result = await run_v22_query("Protein X inhibits pathway Y under condition Z")
        print("\n=== GROUNDED RESPONSE ===")
        print(result.get("grounded_response", {}).get("summary", "No grounded response"))
        print("\n=== EPISTEMIC PROPOSALS ===")
        for prop in result.get("epistemic_update_proposal", [])[:3]:
            print(
                f"- {prop.get('claim_id')}: {prop.get('final_proposed_status')} (caps: {prop.get('cap_reasons', [])})"
            )
        print("\n=== WRITE INTENTS ===")
        for intent in result.get("write_intents", [])[:3]:
            print(f"- {intent.get('intent_type')}: {intent.get('payload', {}).get('claim_id')}")
        print(f"\nStep count: {result.get('step_index', 0)}")

    asyncio.run(test_v22())
