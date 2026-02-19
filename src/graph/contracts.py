"""Phase 16.8/OPS-1.1 workflow contract models (v1)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StewardWriteResultV1(BaseModel):
    """Per-intent durable write outcome emitted by OntologySteward."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    intent_id: str
    intent_type: str
    status: Literal["executed", "failed"]
    idempotency_key: str
    duration_ms: int = Field(ge=0)
    error: Optional[str] = None


class GovernanceSummaryV1(BaseModel):
    """Governance gate envelope consumed by integrate node."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    status: Literal["STAGED", "HOLD"]
    lane: Optional[str] = None
    session_id: Optional[str] = None
    persisted_evidence_ids: list[str] = Field(default_factory=list)
    intent_id: Optional[str] = None
    proposal_id: Optional[str] = None
    mutation_ids: list[str] = Field(default_factory=list)
    scope_lock_id: Optional[str] = None
    hold_code: Optional[str] = None
    hold_reason: Optional[str] = None
    gate_code: str
    failure_reason: Optional[str] = None
    duration_ms: int = Field(ge=0)
