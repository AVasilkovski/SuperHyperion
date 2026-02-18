"""
Govern and Stage Node — Phase 16.3 "Constitutional Spine"

Consolidates evidence, computes deterministic IDs, detects theory change
proposals, and stages write-intents BEFORE the Steward persists them.
"""

import logging
import time
from typing import Any, Dict, List

from src.agents.base_agent import AgentContext
from src.epistemology.evidence_roles import EvidenceRole, validate_evidence_role
from src.epistemology.theory_change_operator import (
    TheoryAction,
    compute_theory_change_action,
    generate_proposal,
    get_claim_id,
    get_evidence_entity_id,
)
from src.governance.fingerprinting import (
    make_evidence_id,
    make_negative_evidence_id,
    make_policy_hash,
    make_proposal_id,
)
from src.graph.state import AgentState, NodeType
from src.hitl.intent_service import write_intent_service

logger = logging.getLogger(__name__)


async def govern_and_stage_node(state: AgentState) -> AgentState:
    """
    The Constitutional Spine: Converts validation results into governance artifacts.
    
    1. Assigns deterministic IDs to evidence
    2. Groups evidence by claim
    3. Computes required theory change (REVISE/FORK/etc)
    4. Stages proposals as write-intents
    """
    logger.info("v2.1: Govern and Stage Node (Constitutional Spine)")
    state["current_node"] = NodeType.INTEGRATE.value # Temporarily hijacking for flow
    
    session_id = state.get("graph_context", {}).get("session_id", f"sess-{int(time.time())}")
    
    # 1. Harvest Evidence from state
    # Validator agent puts them in state["evidence"] for positive
    # and state["graph_context"]["negative_evidence"] for negative
    pos_evidence = state.get("evidence", [])
    neg_evidence = state.get("graph_context", {}).get("negative_evidence", [])
    
    # 2. Assign Deterministic IDs (Fingerprinting)
    sealed_pos = []
    for ev in pos_evidence:
        eid = make_evidence_id(
            session_id, 
            get_claim_id(ev), 
            ev.get("execution_id", "unknown"), 
            ev.get("template_qid", "unknown")
        )
        ev["eid"] = eid # Bind to state
        sealed_pos.append(ev)
        
    sealed_neg = []
    for ev in neg_evidence:
        rid = make_negative_evidence_id(
            session_id,
            get_claim_id(ev),
            ev.get("execution_id", "unknown"),
            ev.get("template_qid", "unknown")
        )
        ev["eid"] = rid
        sealed_neg.append(ev)
        
    # Update state with sealed IDs
    state["evidence"] = sealed_pos
    state["graph_context"]["negative_evidence"] = sealed_neg
    
    # 3. Aggregate for Theory Change Operator
    by_claim: Dict[str, List[tuple]] = {}
    
    # Process Positive
    for ev in sealed_pos:
        cid = get_claim_id(ev)
        if not cid: continue
        role = validate_evidence_role(ev.get("role") or "support")
        by_claim.setdefault(cid, []).append((ev, role, "validation"))
        
    # Process Negative
    for ev in sealed_neg:
        cid = get_claim_id(ev)
        if not cid: continue
        role = validate_evidence_role(ev.get("role") or "refute")
        by_claim.setdefault(cid, []).append((ev, role, "negative"))
        
    # 4. Generate Proposals
    policy_hash = make_policy_hash()
    staged_proposals = []
    
    for claim_id, triples in by_claim.items():
        action, metadata = compute_theory_change_action(claim_id, triples)
        
        if action == TheoryAction.HOLD:
            continue
            
        evidence_fps = sorted(
            f"{get_evidence_entity_id(ev)}:{role.value}:{channel}"
            for ev, role, channel in triples
        )
        
        proposal_id = make_proposal_id(
            session_id, claim_id, action.value, evidence_fps, policy_hash
        )
        
        proposal = generate_proposal(
            claim_id, triples,
            proposal_id=proposal_id,
            precomputed=(action, metadata),
        )
        
        # 5. Stage via Intent Service
        write_intent_service.stage(
            intent_type="stage_epistemic_proposal",
            payload=proposal.to_intent_payload(),
            lane="grounded",
            impact_score=proposal.conflict_score,
            proposal_id=proposal_id,
        )
        staged_proposals.append(proposal_id)
        
    state["graph_context"]["staged_proposals"] = staged_proposals
    return state
