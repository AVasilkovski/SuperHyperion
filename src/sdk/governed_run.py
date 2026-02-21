"""
TRUST-1.0 SDK — GovernedRun Orchestrator

Single entry point for enterprise consumers to run governed scientific
reasoning queries and receive typed, auditable result envelopes.

Usage::

    from src.sdk import GovernedRun

    result = await GovernedRun.run("Protein X inhibits pathway Y")
    print(result.status)        # "COMMIT" | "HOLD" | "ERROR"
    print(result.capsule_id)    # deterministic run capsule ID
    result.export_audit_bundle("./audit_output")
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from src.sdk.types import GovernedResultV1

logger = logging.getLogger(__name__)


class GovernedRun:
    """Enterprise-grade entry point for governed scientific reasoning runs."""

    @staticmethod
    async def run(
        query: str,
        tenant_id: str = "default",
        session_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        mode: str = "grounded",
        **options: Any,
    ) -> "GovernedResultV1":
        """
        Execute a governed scientific reasoning run.

        Args:
            query:      User hypothesis / question to investigate.
            tenant_id:  Tenant identifier threaded through workflow/capsule metadata.
            session_id: Optional session ID override.
            thread_id:  LangGraph thread ID for checkpointing.
            mode:       Epistemic mode (reserved; currently always "grounded").
            **options:  Reserved for future configuration knobs.

        Returns:
            GovernedResultV1 with fail-closed status and full audit trail.
        """
        from src.sdk.types import GovernedResultV1

        tid = thread_id or f"trust-{uuid.uuid4().hex[:8]}"

        # --- 1. Execute the canonical workflow ---
        try:
            from src.graph.workflow_v21 import run_v21_query

            final_state = await run_v21_query(
                query,
                thread_id=tid,
                session_id=session_id,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.error("GovernedRun: workflow execution failed: %s", exc)
            return GovernedResultV1(
                status="ERROR",
                response=f"Workflow execution failed: {exc}",
                tenant_id=tenant_id,
            )

        # --- 2. Extract governance + capsule from final state ---
        return _build_result(final_state, tenant_id)


def _build_result(
    state: Dict[str, Any],
    tenant_id: str,
) -> "GovernedResultV1":
    """
    Derive GovernedResultV1 from final AgentState (fail-closed).

    Rules:
        - No governance           → HOLD
        - governance.status=HOLD  → HOLD (carry hold_code/hold_reason)
        - governance.status=STAGED but no capsule_id → HOLD (MISSING_CAPSULE)
        - governance.status=STAGED + capsule → COMMIT + replay verify
    """
    from src.graph.contracts import GovernanceSummaryV1
    from src.sdk.types import GovernedResultV1

    gov_raw = state.get("governance")
    capsule = state.get("run_capsule") or {}
    response_text = state.get("response") or ""

    # --- Parse governance ---
    gov: Optional[GovernanceSummaryV1] = None
    if gov_raw:
        try:
            gov = GovernanceSummaryV1(**gov_raw) if isinstance(gov_raw, dict) else gov_raw
        except Exception:
            gov = None

    # --- Fail-closed decision ---
    if not gov:
        return GovernedResultV1(
            status="HOLD",
            response=response_text or "HOLD: No governance artifacts present.",
            hold_code="NO_GOVERNANCE",
            hold_reason="Governance summary missing from pipeline output.",
            tenant_id=tenant_id,
        )

    if gov.status == "HOLD":
        return GovernedResultV1(
            status="HOLD",
            response=response_text or f"HOLD: [{gov.hold_code}] {gov.hold_reason}",
            governance=gov,
            evidence_ids=list(gov.persisted_evidence_ids),
            mutation_ids=list(gov.mutation_ids),
            intent_id=gov.intent_id,
            proposal_id=gov.proposal_id,
            hold_code=gov.hold_code,
            hold_reason=gov.hold_reason,
            tenant_id=tenant_id,
        )

    # Governance is STAGED
    capsule_id = capsule.get("capsule_id")
    if not capsule_id:
        return GovernedResultV1(
            status="HOLD",
            response=response_text or "HOLD: Governance staged but capsule missing.",
            governance=gov,
            evidence_ids=list(gov.persisted_evidence_ids),
            mutation_ids=list(gov.mutation_ids),
            intent_id=gov.intent_id,
            proposal_id=gov.proposal_id,
            hold_code="MISSING_CAPSULE",
            hold_reason="Governance status is STAGED but no run capsule was created.",
            tenant_id=tenant_id,
        )

    # --- COMMIT path: run replay verification ---
    replay_verdict = None
    try:
        from src.verification.replay_verify import verify_capsule

        capsule_data = {
            "session_id": capsule.get("session_id", ""),
            "query_hash": capsule.get("query_hash", ""),
            "tenant_id": capsule.get("tenant_id", tenant_id),
            "scope_lock_id": capsule.get("scope_lock_id", ""),
            "intent_id": capsule.get("intent_id", ""),
            "proposal_id": capsule.get("proposal_id", ""),
            "evidence_ids": capsule.get("evidence_ids", []),
            "mutation_ids": capsule.get("mutation_ids", []),
            "capsule_hash": capsule.get("capsule_hash", ""),
            "_has_mutation_snapshot": True,  # New capsules always have mutation support
        }
        replay_verdict = verify_capsule(capsule_id, capsule_data, tenant_id=tenant_id)
    except Exception as exc:
        logger.warning("GovernedRun: replay verification failed: %s", exc)

    return GovernedResultV1(
        status="COMMIT",
        response=response_text,
        capsule_id=capsule_id,
        governance=gov,
        evidence_ids=list(gov.persisted_evidence_ids),
        mutation_ids=list(gov.mutation_ids),
        intent_id=gov.intent_id,
        proposal_id=gov.proposal_id,
        replay_verdict=replay_verdict,
        tenant_id=tenant_id,
    )
