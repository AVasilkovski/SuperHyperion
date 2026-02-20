"""TRUST-1.0.1 Explainability summary overlay artifact."""

from __future__ import annotations

import os
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class HoldBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hold_code: Optional[str] = None
    hold_reason: Optional[str] = None


class SourceRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    governance_summary_file: str
    replay_verdict_file: Optional[str] = None
    capsule_manifest_file: Optional[str] = None


class GovernanceGateBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["STAGED", "HOLD"]
    gate_code: str
    duration_ms: int = Field(ge=0)
    failure_reason: Optional[str] = None


class CheckOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool


class PrimacyCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    code: str


class MutationLinkageCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    missing: list[str] = Field(default_factory=list)


class GovernanceChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hash_integrity: CheckOk
    primacy: PrimacyCheck
    mutation_linkage: MutationLinkageCheck


class EvidenceBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persisted_ids: list[str] = Field(default_factory=list)
    mutation_ids: list[str] = Field(default_factory=list)
    intent_id: Optional[str] = None
    proposal_id: Optional[str] = None


class LineageBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: Optional[str] = None
    scope_lock_id: Optional[str] = None
    query_hash: Optional[str] = None


class ExplainabilitySummaryV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    capsule_id: Optional[str] = None
    tenant_id: str
    status: Literal["COMMIT", "HOLD", "ERROR"]
    hold: HoldBlock
    source_refs: SourceRefs
    governance_gate: GovernanceGateBlock
    governance_checks: GovernanceChecks
    evidence: EvidenceBlock
    lineage: LineageBlock


def _load_if_path(value: Dict[str, Any] | str | None) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, str):
        import json

        with open(value, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return value


def build_explainability_summary(
    governance_summary: Dict[str, Any] | str,
    replay_verdict: Dict[str, Any] | str | None = None,
    capsule_manifest: Dict[str, Any] | str | None = None,
) -> ExplainabilitySummaryV1:
    governance = _load_if_path(governance_summary) or {}
    replay = _load_if_path(replay_verdict) or None
    manifest = _load_if_path(capsule_manifest) or None

    source_refs = governance.get("source_refs") or {}
    governance_file = source_refs.get("governance_summary_file")
    if not governance_file:
        governance_file = os.path.basename(str(governance_summary)) if isinstance(governance_summary, str) else "governance_summary.json"

    replay_file = source_refs.get("replay_verdict_file")
    if replay_file is None and isinstance(replay_verdict, str):
        replay_file = os.path.basename(replay_verdict)

    manifest_file = source_refs.get("capsule_manifest_file")
    if manifest_file is None and isinstance(capsule_manifest, str):
        manifest_file = os.path.basename(capsule_manifest)

    details = (replay or {}).get("details") or {}
    hash_details = details.get("hash_integrity") or {}
    primacy_details = details.get("primacy") or {}
    mutation_details = details.get("mutation_linkage") or {}

    hash_ok = bool(hash_details.get("expected") == hash_details.get("computed")) if hash_details else False
    primacy_code = str(primacy_details.get("code") or "UNKNOWN")
    primacy_ok = bool(primacy_code == "PASS")
    missing_mutations = sorted([str(x) for x in (mutation_details.get("missing") or [])])
    mutation_ok = bool(not missing_mutations and replay is not None and replay.get("status") == "PASS")

    persisted_ids = sorted([str(x) for x in (governance.get("persisted_evidence_ids") or [])])
    mutation_ids = sorted([str(x) for x in (governance.get("mutation_ids") or [])])

    capsule_id = (manifest or {}).get("capsule_id")
    tenant_id = (manifest or {}).get("tenant_id") or governance.get("tenant_id") or "default"

    status: Literal["COMMIT", "HOLD", "ERROR"]
    if governance.get("status") == "STAGED" and capsule_id:
        status = "COMMIT"
    elif governance.get("status") == "HOLD":
        status = "HOLD"
    else:
        status = "ERROR"

    return ExplainabilitySummaryV1(
        capsule_id=capsule_id,
        tenant_id=tenant_id,
        status=status,
        hold=HoldBlock(
            hold_code=governance.get("hold_code"),
            hold_reason=governance.get("hold_reason"),
        ),
        source_refs=SourceRefs(
            governance_summary_file=str(governance_file),
            replay_verdict_file=str(replay_file) if replay_file is not None else None,
            capsule_manifest_file=str(manifest_file) if manifest_file is not None else None,
        ),
        governance_gate=GovernanceGateBlock(
            status=governance.get("status", "HOLD"),
            gate_code=str(governance.get("gate_code") or "UNKNOWN"),
            duration_ms=int(governance.get("duration_ms") or 0),
            failure_reason=governance.get("failure_reason"),
        ),
        governance_checks=GovernanceChecks(
            hash_integrity=CheckOk(ok=hash_ok),
            primacy=PrimacyCheck(ok=primacy_ok, code=primacy_code),
            mutation_linkage=MutationLinkageCheck(ok=mutation_ok, missing=missing_mutations),
        ),
        evidence=EvidenceBlock(
            persisted_ids=persisted_ids,
            mutation_ids=mutation_ids,
            intent_id=governance.get("intent_id"),
            proposal_id=governance.get("proposal_id"),
        ),
        lineage=LineageBlock(
            session_id=governance.get("session_id"),
            scope_lock_id=governance.get("scope_lock_id"),
            query_hash=(manifest or {}).get("query_hash"),
        ),
    )
