"""
TRUST-1.0 SDK — Type Contracts

Enterprise-grade result envelopes for governed scientific reasoning runs.

Models:
    ReplayVerdictV1  — Replay verification outcome (PASS/FAIL + reasons)
    GovernedResultV1 — Full run result with governance, capsule, and replay data
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.graph.contracts import GovernanceSummaryV1


class ReplayVerdictV1(BaseModel):
    """Replay verification outcome for a run capsule."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    status: Literal["PASS", "FAIL"]
    reasons: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class GovernedResultV1(BaseModel):
    """
    Enterprise-grade result envelope from a governed run.

    Status semantics (fail-closed):
        COMMIT — governance passed, capsule sealed, response synthesized
        HOLD   — governance blocked or missing; no synthesized response
        ERROR  — unexpected runtime failure
    """

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"

    # --- Core outcome ---
    status: Literal["COMMIT", "HOLD", "ERROR"]
    response: str

    # --- Capsule & governance ---
    capsule_id: Optional[str] = None
    governance: Optional[GovernanceSummaryV1] = None

    # --- Evidence & mutations ---
    evidence_ids: List[str] = Field(default_factory=list)
    mutation_ids: List[str] = Field(default_factory=list)

    # --- Governance anchors ---
    intent_id: Optional[str] = None
    proposal_id: Optional[str] = None

    # --- HOLD diagnostics ---
    hold_code: Optional[str] = None
    hold_reason: Optional[str] = None

    # --- Replay ---
    replay_verdict: Optional[ReplayVerdictV1] = None

    # --- Tenant ---
    tenant_id: str = "default"

    def export_audit_bundle(self, out_dir: str) -> list[str]:
        """Write audit-friendly JSON files to *out_dir*.

        Delegates to :func:`src.sdk.export.export_audit_bundle`.
        Returns list of written file paths.
        """
        from src.sdk.export import export_audit_bundle

        return export_audit_bundle(self, out_dir)
