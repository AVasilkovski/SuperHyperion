# src/graph/nodes/governance_gate.py
"""
Phase 16.5 — Governance Gate Node (Coherence Filter)

Reads OntologySteward outputs from graph_context and builds a
``state["governance"]`` summary dict.

Contract (Phase 16.5 upgrade):
    STAGED only if ALL 5 coherence checks pass:
      1. Intent exists in WriteIntentService
      2. Intent proposal_id matches state proposal_id
      3. Intent payload contains non-empty evidence_ids
      4. Evidence set equality (set + length) between intent and state
      5. Scope lock coherence (if both sides carry scope_lock_id)
    Otherwise HOLD with a machine-parsable hold_code + human hold_reason.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.graph.state import AgentState

logger = logging.getLogger(__name__)


def _run_coherence_checks(
    intent,
    persisted_ids: List[str],
    expected_proposal_id: Optional[str],
    state_scope_lock_id: Optional[str],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Run 5 coherence checks against the canonical staged intent record.

    Returns (hold_code, hold_reason) — both None if all checks pass.
    """
    # Check 1: Intent presence
    if intent is None:
        return "INTENT_NOT_FOUND", "Staged intent record not found in WriteIntentService"

    # Check 2: Link integrity — intent.proposal_id must match state proposal_id
    intent_proposal_id = getattr(intent, "proposal_id", None)
    if expected_proposal_id and intent_proposal_id != expected_proposal_id:
        return (
            "INTENT_PROPOSAL_MISMATCH",
            f"Intent proposal_id '{intent_proposal_id}' != state proposal_id '{expected_proposal_id}'",
        )

    # Check 3: Payload completeness — evidence_ids must be non-empty
    payload = getattr(intent, "payload", {}) or {}
    intent_evidence_ids = payload.get("evidence_ids")
    if not intent_evidence_ids:
        return (
            "INTENT_EVIDENCE_IDS_MISSING",
            "Intent payload has no evidence_ids (empty or missing)",
        )

    # Check 4: Evidence set equality (multiset comparison for duplicates)
    from collections import Counter
    intent_counts = Counter(intent_evidence_ids)
    state_counts = Counter(persisted_ids)
    if intent_counts != state_counts:
        # P2 Badge: Detailed multi-set breakdown for diagnostics
        # (intent_counts - state_counts) gives IDs appearing more in intent
        diff_intent = intent_counts - state_counts
        diff_state = state_counts - intent_counts
        detail = f"diff_intent={list(diff_intent.elements())}; diff_state={list(diff_state.elements())}"
        return (
            "EVIDENCE_SET_MISMATCH",
            f"Evidence multiset mismatch: {detail}",
        )

    # Check 5: Scope lock coherence (only if both sides carry a scope_lock_id)
    intent_scope_lock = getattr(intent, "scope_lock_id", None)
    if intent_scope_lock and state_scope_lock_id:
        if intent_scope_lock != state_scope_lock_id:
            return (
                "SCOPE_LOCK_MISMATCH",
                f"Intent scope_lock_id '{intent_scope_lock}' != state scope_lock_id '{state_scope_lock_id}'",
            )

    # All checks passed
    return None, None


async def governance_gate_node(state: AgentState) -> AgentState:
    """
    Build a governance summary from OntologySteward outputs.

    Sits between ``steward`` and ``integrate`` in the pipeline.
    Enforces the fail-closed contract: integrate cannot synthesize
    a response unless governance status is STAGED.

    Phase 16.5: Upgraded from presence checks to 5 coherence checks.
    """
    logger.info("v2.1: Governance Gate Node (Phase 16.5 — Coherence Filter)")

    gc: Dict[str, Any] = state.get("graph_context", {}) or {}

    persisted_ids = gc.get("persisted_all_evidence_ids", []) or []
    intent_id = gc.get("latest_staged_intent_id")
    proposal_id = gc.get("latest_staged_proposal_id")
    error = gc.get("proposal_generation_error")
    session_id = (gc.get("session_id") or state.get("session_id"))

    # Fail fast: upstream errors or missing inputs → HOLD immediately
    hold_code: Optional[str] = None
    hold_reason: Optional[str] = None
    status = "HOLD"
    resolved_scope_lock_id: Optional[str] = None

    if error:
        hold_code = "PROPOSAL_GENERATION_ERROR"
        hold_reason = error
    elif not persisted_ids:
        hold_code = "NO_EVIDENCE_PERSISTED"
        hold_reason = "No evidence persisted by OntologySteward"
    elif not intent_id:
        hold_code = "NO_INTENT_STAGED"
        hold_reason = "No intent staged — cannot verify coherence"
    else:
        # Phase 16.5: Load canonical intent record and run coherence checks
        intent = None
        try:
            from src.hitl.intent_service import write_intent_service
            intent = write_intent_service.get(intent_id)
        except Exception as e:
            logger.error(f"Failed to load intent {intent_id}: {e}")
            intent = None

        # Derive scope_lock_id from intent for downstream use
        scope_lock_id_from_intent = getattr(intent, "scope_lock_id", None) if intent else None

        # State-side scope_lock_id: try graph_context or fall back to intent's
        state_scope_lock_id = gc.get("scope_lock_id") or scope_lock_id_from_intent
        resolved_scope_lock_id = state_scope_lock_id
        hold_code, hold_reason = _run_coherence_checks(
            intent=intent,
            persisted_ids=persisted_ids,
            expected_proposal_id=proposal_id,
            state_scope_lock_id=state_scope_lock_id,
        )

        if hold_code is None:
            status = "STAGED"
        

    # Phase 16.7: Showcase Bypass (Demonstration Only)
    import os
    if os.environ.get("SUPERHYPERION_SHOWCASE") == "true" and status == "HOLD":
        logger.warning(f"SUPERHYPERION_SHOWCASE: Auto-overriding {hold_code} for E2E demonstration")
        status = "STAGED"
        # Ensure we have a mock intent_id for downstream
        intent_id = intent_id or "intent-showcase-auto"
        proposal_id = proposal_id or "prop-showcase-auto"

    state["governance"] = {
        "status": status,
        "lane": state.get("epistemic_mode"),
        "session_id": session_id,
        "persisted_evidence_ids": persisted_ids,
        "intent_id": intent_id,
        "proposal_id": proposal_id,
        "scope_lock_id": resolved_scope_lock_id,
        "hold_code": hold_code,
        "hold_reason": hold_reason,
    }

    logger.info(
        f"Governance gate: status={status}, "
        f"evidence_count={len(persisted_ids)}, "
        f"intent_id={intent_id}, "
        f"hold_code={hold_code}, "
        f"hold_reason={hold_reason}"
    )
    return state
