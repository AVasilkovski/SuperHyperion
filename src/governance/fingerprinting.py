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
from typing import Optional


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
