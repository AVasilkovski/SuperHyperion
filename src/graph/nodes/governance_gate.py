# src/graph/nodes/governance_gate.py
"""
Phase 16.4 — Governance Gate Node

Reads OntologySteward outputs from graph_context and builds a
``state["governance"]`` summary dict.

Contract:
    STAGED only if (persisted evidence ids) AND (intent_id) AND (no error)
    Otherwise HOLD with a concrete hold_reason.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.graph.state import AgentState

logger = logging.getLogger(__name__)


async def governance_gate_node(state: AgentState) -> AgentState:
    """
    Build a governance summary from OntologySteward outputs.

    Sits between ``steward`` and ``integrate`` in the pipeline.
    Enforces the fail-closed contract: integrate cannot synthesize
    a response unless governance status is STAGED.
    """
    logger.info("v2.1: Governance Gate Node (Phase 16.4)")

    gc: Dict[str, Any] = state.get("graph_context", {}) or {}

    persisted_ids = gc.get("persisted_all_evidence_ids", []) or []
    intent_id = gc.get("latest_staged_intent_id")
    proposal_id = gc.get("latest_staged_proposal_id")
    error = gc.get("proposal_generation_error")

    # STAGED requires evidence + intent + no error
    status = "STAGED" if (persisted_ids and intent_id and not error) else "HOLD"

    hold_reason = None
    if status == "HOLD":
        if error:
            hold_reason = error
        elif not persisted_ids:
            hold_reason = "No evidence persisted"
        elif not intent_id:
            hold_reason = "No intent staged"
        else:
            hold_reason = "Unknown governance hold"

    state["governance"] = {
        "status": status,
        "lane": state.get("epistemic_mode"),
        "session_id": gc.get("session_id"),
        "persisted_evidence_ids": persisted_ids,
        "intent_id": intent_id,
        "proposal_id": proposal_id,
        "hold_reason": hold_reason,
    }

    logger.info(
        f"Governance gate: status={status}, "
        f"evidence_count={len(persisted_ids)}, "
        f"intent_id={intent_id}, "
        f"hold_reason={hold_reason}"
    )
    return state
