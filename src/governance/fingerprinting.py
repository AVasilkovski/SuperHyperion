"""
Fingerprinting — Phase 16.1

Deterministic ID generation for epistemic artifacts.

This module provides stable, joinable IDs for:
- validation-evidence (positive channel)
- negative-evidence (negative channel)
- Other governed artifacts (future: reproducibility capsules)

Design principles:
1. Same inputs → same ID (deterministic)
2. Different channels use different prefixes (ev- vs nev-)
3. IDs are short enough to be readable but collision-resistant
4. JSON canonicalization ensures cross-platform reproducibility
"""

import hashlib
import json
from typing import List, Optional


def make_evidence_id(
    session_id: str,
    claim_id: str,
    execution_id: str,
    template_qid: str,
) -> str:
    """
    Deterministic evidence ID generator for validation-evidence.

    Creates a stable, joinable ID for positive evidence channel.
    Returns 35 characters: "ev-" + 32-char MD5 hash.

    Args:
        session_id: Session identifier
        claim_id: Claim/proposition identifier
        execution_id: Template execution identifier
        template_qid: Template qualified identifier

    Returns:
        Deterministic evidence ID string (35 chars)
    """
    payload = {
        "sid": session_id or "",
        "cid": claim_id or "",
        "eid": execution_id or "",
        "qid": template_qid or "",
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    h = hashlib.md5(s.encode("utf-8")).hexdigest()
    return f"ev-{h}"


def make_negative_evidence_id(
    session_id: str,
    claim_id: str,
    execution_id: str,
    template_qid: str,
) -> str:
    """
    Deterministic evidence ID generator for negative-evidence.

    Creates a stable, joinable ID for negative evidence channel.
    Returns 36 characters: "nev-" + 32-char MD5 hash.

    Uses the same fingerprint protocol as positive evidence,
    but with a different prefix to ensure channel separation.

    Args:
        session_id: Session identifier
        claim_id: Claim/proposition identifier
        execution_id: Template execution identifier
        template_qid: Template qualified identifier

    Returns:
        Deterministic negative evidence ID string (36 chars)
    """
    payload = {
        "sid": session_id or "",
        "cid": claim_id or "",
        "eid": execution_id or "",
        "qid": template_qid or "",
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    h = hashlib.md5(s.encode("utf-8")).hexdigest()
    return f"nev-{h}"


def make_capsule_id(
    template_qid: str,
    spec_hash: str,
    code_hash: str,
    retrieval_snapshot_digest: Optional[str] = None,
) -> str:
    """
    Deterministic ID generator for reproducibility capsules (Phase 16.3).

    Creates a stable ID for a sealed run bundle.
    Returns 38 characters: "cap-" + 32-char MD5 hash.

    Args:
        template_qid: Template qualified identifier
        spec_hash: Specification hash
        code_hash: Code hash
        retrieval_snapshot_digest: Optional retrieval snapshot digest

    Returns:
        Deterministic capsule ID string (36 chars)
    """
    payload = {
        "qid": template_qid or "",
        "spec": spec_hash or "",
        "code": code_hash or "",
        "retr": retrieval_snapshot_digest or "",
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    h = hashlib.md5(s.encode("utf-8")).hexdigest()
    return f"cap-{h}"


def make_proposal_id(
    session_id: str,
    claim_id: str,
    action: str,
    evidence_fingerprints: List[str],
    policy_hash: str,
) -> str:
    """
    Deterministic proposal ID using SHA-256.

    Components: session context, action semantics, evidence fingerprints, policy hash.
    Returns "prop-" + 24-char hex digest.
    """
    payload = {
        "sid": session_id or "",
        "cid": claim_id or "",
        "act": action or "",
        "evfp": sorted(evidence_fingerprints),
        "ph": policy_hash,
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]
    return f"prop-{h}"


def make_policy_hash() -> str:
    """Canonical hash of current theory-change thresholds + operator version."""
    from src.epistemology.theory_change_operator import (
        FORK_THRESHOLD,
        MIN_EVIDENCE_COUNT,
        QUARANTINE_THRESHOLD,
    )

    payload = {
        "FORK_THRESHOLD": FORK_THRESHOLD,
        "QUARANTINE_THRESHOLD": QUARANTINE_THRESHOLD,
        "MIN_EVIDENCE_COUNT": MIN_EVIDENCE_COUNT,
        "OPERATOR_VERSION": "16.3.0",
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def make_run_capsule_id(
    session_id: str,
    query_hash: str,
    scope_lock_id: str,
    intent_id: str,
    proposal_id: str,
    evidence_ids: List[str],
) -> str:
    """
    Deterministic run capsule ID generator (Phase 16.6).

    Creates a stable ID for a sealed run bundle that pins the exact session,
    query, scope lock, governance anchors, and evidence snapshot.

    Returns "run-" + 32-char SHA-256 hex digest (36 chars total).

    Args:
        session_id: Session identifier
        query_hash: SHA-256 of the user query
        scope_lock_id: Scope lock ID for this run
        intent_id: Write intent ID
        proposal_id: Proposal ID
        evidence_ids: All evidence IDs included in this run
    """
    payload = {
        "sid": session_id or "",
        "qh": query_hash or "",
        "slid": scope_lock_id or "",
        "iid": intent_id or "",
        "pid": proposal_id or "",
        "evids": sorted(evidence_ids or []),
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]
    return f"run-{h}"


def make_capsule_manifest_hash(
    capsule_id: str, manifest: dict, manifest_version: str = "v2"
) -> str:
    """
    Compute the integrity hash for a capsule manifest (Phase 16.6).

    `manifest_version` protects backward-compatibility against accidental dict key additions.
    - "v1": Legacy capsules (pre-16.8) without mutation_ids
    - "v2": Post-16.8 capsules with mutation_ids support
    - "v3": Tenant-attributed capsules (mutation_ids + tenant_id)

    Returns 64-char SHA-256 hex digest of the canonical JSON representation.
    """
    if manifest_version == "v1":
        allowed_keys = {
            "session_id",
            "query_hash",
            "scope_lock_id",
            "intent_id",
            "proposal_id",
            "evidence_ids",
        }
    elif manifest_version == "v2":
        allowed_keys = {
            "session_id",
            "query_hash",
            "scope_lock_id",
            "intent_id",
            "proposal_id",
            "evidence_ids",
            "mutation_ids",
        }
    elif manifest_version == "v3":
        allowed_keys = {
            "session_id",
            "query_hash",
            "scope_lock_id",
            "intent_id",
            "proposal_id",
            "evidence_ids",
            "mutation_ids",
            "tenant_id",
        }
    else:
        raise ValueError(f"Unknown manifest_version: {manifest_version}")

    filtered_manifest = {k: v for k, v in manifest.items() if k in allowed_keys}

    canonical = {
        "capsule_id": capsule_id,
        **{k: v for k, v in sorted(filtered_manifest.items())},
    }
    s = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def make_mutation_id(
    session_id: str,
    intent_id: str,
    claim_id: str,
    proposed_status: str,
) -> str:
    """
    Deterministic mutation-event ID generator (Phase 16.8).

    Returns "mut-" + 24-char SHA-256 digest.
    """
    payload = {
        "sid": session_id or "",
        "iid": intent_id or "",
        "cid": claim_id or "",
        "to": proposed_status or "",
    }
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]
    return f"mut-{h}"
