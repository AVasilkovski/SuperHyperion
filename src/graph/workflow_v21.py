"""
LangGraph v2.1 Workflow Definition

13-step scientific reasoning pipeline with dual-lane architecture.
Implements CodeAct as belief gatekeeper and HITL gates.
"""

import logging
from typing import Literal, Optional

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
    validator_agent,
)
from src.epistemic import EpistemicClassifierAgent
from src.graph.nodes.governance_gate import governance_gate_node
from src.graph.state import AgentState, NodeType, create_initial_state
from src.hitl import EpistemicApprovalGate, HighImpactWriteCheckpoint, audit_log

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

    # Phase 16.4: Normalize evidence dicts into steward insert contract
    from src.graph.evidence_normalization import normalize_validation_evidence
    raw_evidence = result.graph_context.get("evidence", [])
    scope_lock_id = result.graph_context.get("scope_lock_id")
    normalized = [
        normalize_validation_evidence(ev, scope_lock_id=scope_lock_id)
        for ev in raw_evidence
    ]
    state["evidence"] = normalized
    result.graph_context["evidence"] = normalized

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
    _classifier = EpistemicClassifierAgent()  # Reserved for future use

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
    """Step 12: Synthesize dual outputs (fail-closed on governance)."""
    logger.info("v2.1: Integrate Node")
    state["current_node"] = NodeType.INTEGRATE.value

    # Phase 16.4 D4: Fail-closed governance guard
    gov = state.get("governance")
    if not gov:
        msg = "HOLD: No governance artifacts. Pipeline incomplete (missing governance summary)."
        logger.warning(f"integrate_node: {msg}")
        state["response"] = msg
        state["grounded_response"] = {"summary": msg, "status": "HOLD"}
        state["speculative_alternatives"] = []
        return state

    if gov.get("status") == "HOLD":
        hold_code = gov.get("hold_code", "UNKNOWN")
        reason = gov.get("hold_reason", "unknown")
        msg = f"HOLD: [{hold_code}] {reason}"
        logger.warning(f"integrate_node: {msg}")
        state["response"] = msg
        state["grounded_response"] = {"summary": msg, "status": "HOLD", "hold_code": hold_code, "governance": gov}
        state["speculative_alternatives"] = []
        return state

    # Phase 16.5: Ledger primacy hard proof (blocks synthesis if evidence is unproven)
    gc = state.get("graph_context", {}) or {}
    # P1 Fix: Harden session_id source to prevent false HOLDs
    session_id = (
        gov.get("session_id") 
        or state.get("session_id") 
        or gc.get("session_id") 
        or "session-untracked"
    )
    evidence_ids = gov.get("persisted_evidence_ids", [])
    tenant_id = state.get("tenant_id") or gc.get("tenant_id") or "default"
    expected_scope = gov.get("scope_lock_id")

    # Derive expected claim IDs from the claims being synthesized
    atomic_claims = gc.get("atomic_claims", [])
    expected_claim_ids = {
        c.get("claim_id") for c in atomic_claims
        if c.get("claim_id")
    } or None  # None means "skip claim check" if no claims available

    primacy_ok, primacy_code, primacy_details = integrator_agent._verify_evidence_primacy(
        session_id=session_id,
        evidence_ids=evidence_ids,
        expected_scope_lock_id=expected_scope,
        expected_claim_ids=expected_claim_ids,
    )

    if not primacy_ok:
        hold_reason = primacy_details.get("hold_reason", f"Primacy check failed: {primacy_code}")
        msg = f"HOLD: [{primacy_code}] {hold_reason}"
        logger.warning(f"integrate_node: {msg}")
        state["response"] = msg
        state["grounded_response"] = {
            "summary": msg,
            "status": "HOLD",
            "hold_code": primacy_code,
            "details": primacy_details,
            "governance": gov,
        }
        state["speculative_alternatives"] = []
        return state

    logger.info(f"integrate_node: Primacy verified ({primacy_details.get('verified_count', 0)} evidence IDs)")

    # Phase 16.6: Build and persist run capsule (only after primacy proves evidence)
    run_capsule = None
    try:
        import hashlib as _hashlib
        import json as _json
        from datetime import datetime as _dt

        from src.governance.fingerprinting import make_capsule_manifest_hash, make_run_capsule_id

        user_query = state.get("original_query") or state.get("query") or ""
        query_hash = _hashlib.sha256(user_query.encode("utf-8")).hexdigest()[:32]

        capsule_id = make_run_capsule_id(
            session_id=session_id,
            query_hash=query_hash,
            scope_lock_id=expected_scope or "",
            intent_id=gov.get("intent_id") or "",
            proposal_id=gov.get("proposal_id") or "",
            evidence_ids=evidence_ids,
        )

        manifest = {
            "session_id": session_id,
            "tenant_id": tenant_id,
            "query_hash": query_hash,
            "scope_lock_id": expected_scope or "",
            "intent_id": gov.get("intent_id") or "",
            "proposal_id": gov.get("proposal_id") or "",
            "evidence_ids": sorted(evidence_ids),
            "mutation_ids": sorted(gov.get("mutation_ids") or []),
        }
        capsule_hash = make_capsule_manifest_hash(capsule_id, manifest, manifest_version="v3")

        run_capsule = {
            "capsule_id": capsule_id,
            "capsule_hash": capsule_hash,
            **manifest,
            "created_at": _dt.now().isoformat(),
        }

        # Attempt TypeDB persistence (graceful degradation)
        try:
            from src.db.typedb_client import TypeDBConnection
            db = TypeDBConnection()
            if not db._mock_mode:
                evidence_snapshot_json = _json.dumps(sorted(evidence_ids), separators=(",", ":"))
                mutation_snapshot_json = _json.dumps(sorted(gov.get("mutation_ids") or []), separators=(",", ":"))
                def _esc(s):
                    return (str(s) or "").replace("\\", "\\\\").replace('"', '\\"')

                insert_q = f'''
                insert
                    $cap isa run-capsule,
                        has capsule-id "{_esc(capsule_id)}",
                        has session-id "{_esc(session_id)}",
                        has query-hash "{_esc(query_hash)}",
                        has scope-lock-id "{_esc(expected_scope or "")}",
                        has intent-id "{_esc(gov.get("intent_id") or "")}",
                        has proposal-id "{_esc(gov.get("proposal_id") or "")}",
                        has evidence-snapshot "{_esc(evidence_snapshot_json)}",
                        has mutation-snapshot "{_esc(mutation_snapshot_json)}",
                        has capsule-hash "{_esc(capsule_hash)}";
                '''
                from src.db.capabilities import WriteCap
                db.query_insert(insert_q, cap=WriteCap._mint())
                logger.info(f"integrate_node: Run capsule persisted: {capsule_id}")

                mutation_events = state.get("graph_context", {}).get("mutation_events", []) or []
                for event in mutation_events:
                    claim_id = event.get("claim_id", "")
                    mutation_q = f"""
                    match
                        $cap isa run-capsule, has capsule-id "{_esc(capsule_id)}";
                        $prop isa proposition, has entity-id "{_esc(claim_id)}";
                    insert
                        $mut isa mutation-event,
                            has mutation-id "{_esc(event.get('mutation_id', ''))}",
                            has session-id "{_esc(event.get('session_id', session_id))}",
                            has intent-id "{_esc(event.get('intent_id', ''))}",
                            has proposal-id "{_esc(event.get('proposal_id', ''))}",
                            has claim-id "{_esc(claim_id)}",
                            has mutation-type "{_esc(event.get('mutation_type', 'unknown'))}",
                            has to-status "{_esc(event.get('to_status', ''))}";
                        (mutation-event: $mut, capsule: $cap) isa asserted-by;
                        (mutation-event: $mut, proposition: $prop) isa affects;
                    """
                    db.query_insert(mutation_q, cap=WriteCap._mint())
            else:
                logger.debug(f"integrate_node: [MOCK] Run capsule built: {capsule_id}")
        except Exception as e:
            logger.warning(f"integrate_node: Capsule persistence skipped (DB unavailable): {e}")

    except Exception as e:
        logger.warning(f"integrate_node: Capsule creation failed: {e}")

    from src.agents.base_agent import AgentContext
    context = AgentContext()
    context.graph_context = state.get("graph_context", {})
    context.graph_context["governance"] = gov  # Phase 16.4: inject for citations
    if run_capsule:
        context.graph_context["run_capsule"] = run_capsule
    context.response = state.get("response")

    result = await integrator_agent.run(context)

    state["grounded_response"] = result.graph_context.get("grounded_response")
    state["speculative_alternatives"] = result.graph_context.get("speculative_alternatives", [])
    state["response"] = result.response
    state["graph_context"] = result.graph_context
    if run_capsule:
        state["run_capsule"] = run_capsule
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
    workflow.add_node("impact_gate", impact_gate_node)
    workflow.add_node("steward", steward_node)
    workflow.add_node("governance_gate", governance_gate_node)  # Phase 16.4
    workflow.add_node("integrate", integrate_node)

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

    # Phase 16.4: Reordered final stages
    # steward persists BEFORE integrate synthesizes (ledger-citable)
    workflow.add_edge("epistemic_gate", "impact_gate")
    workflow.add_edge("impact_gate", "steward")
    workflow.add_edge("steward", "governance_gate")
    workflow.add_edge("governance_gate", "integrate")
    workflow.add_edge("integrate", END)

    return workflow


# Create compiled v2.1 workflow
memory_v21 = MemorySaver()
workflow_v21 = build_v21_workflow()
app_v21 = workflow_v21.compile(checkpointer=memory_v21)


async def run_v21_query(
    query: str,
    thread_id: str = "default",
    session_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> AgentState:
    """
    Run a query through the v2.1 workflow.
    
    Args:
        query: User's hypothesis to investigate
        thread_id: Thread ID for checkpointing
        session_id: Optional session ID override
        tenant_id: Optional tenant ID for deterministic attribution
        
    Returns:
        Final agent state with dual outputs
    """
    initial_state = create_initial_state(
        query,
        session_id=session_id,
        tenant_id=tenant_id,
    )
    cfg = {"configurable": {"thread_id": thread_id}}

    final_state = await app_v21.ainvoke(initial_state, cfg)
    return final_state


if __name__ == "__main__":
    import asyncio

    async def test_v21():
        result = await run_v21_query("Protein X inhibits pathway Y under condition Z")
        print("\n=== GROUNDED RESPONSE ===")
        print(result.get("grounded_response", {}).get("summary", "No grounded response"))
        print("\n=== SPECULATIVE ALTERNATIVES ===")
        for alt in result.get("speculative_alternatives", [])[:3]:
            print(f"- {alt.get('hypothesis', 'Unknown')}")
        print(f"\nScientific Uncertainty: {result.get('scientific_uncertainty', {})}")

    asyncio.run(test_v21())
