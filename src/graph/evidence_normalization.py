# src/graph/evidence_normalization.py
"""
Phase 16.4 — Evidence Schema Normalization

Single choke-point that maps ValidatorAgent evidence dicts into the
OntologySteward insert contract.

Non-destructive: preserves original keys (hypothesis_id, codeact_execution_id)
for traceability.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def normalize_validation_evidence(
    ev: Dict[str, Any],
    *,
    scope_lock_id: Optional[str] = None,
    template_qid_default: str = "codeact-v1@1.0",
) -> Dict[str, Any]:
    """
    Normalize ValidatorAgent evidence dict into OntologySteward insert contract.

    Canonical fields steward expects:
        - claim_id     (string)
        - execution_id (string)
        - template_qid (string)
        - scope_lock_id (string|None)

    Non-destructive: preserves original keys like hypothesis_id,
    codeact_execution_id.
    """
    out = dict(ev)  # non-destructive copy

    # claim_id ← hypothesis_id (if claim_id missing/empty)
    claim_id = out.get("claim_id") or out.get("claim-id") or out.get("proposition_id")
    if not claim_id:
        hyp = out.get("hypothesis_id")
        if hyp is not None:
            out["claim_id"] = str(hyp).strip()

    # execution_id ← str(codeact_execution_id) (if execution_id missing/empty)
    raw_exec = out.get("execution_id") or out.get("execution-id")
    if not raw_exec:
        codeact_exec = out.get("codeact_execution_id")
        if codeact_exec is not None:
            out["execution_id"] = str(codeact_exec).strip()

    # template_qid default
    template_qid = out.get("template_qid") or out.get("template-qid")
    if not template_qid:
        out["template_qid"] = template_qid_default

    # scope_lock_id from arg if missing
    if not out.get("scope_lock_id") and scope_lock_id is not None:
        out["scope_lock_id"] = scope_lock_id

    return out
