"""
Replay Capsule Verification — Pure function extracted from replay_cli.

Verifies a run capsule's integrity against the ledger:
    1. Manifest hash integrity
    2. Evidence primacy (ledger-anchored proof)
    3. Mutation linkage (Phase 16.8)

Returns a ReplayVerdictV1 (PASS/FAIL + reasons).
No DB writes — strictly read-only verification.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

if TYPE_CHECKING:
    from src.sdk.types import ReplayVerdictV1

logger = logging.getLogger(__name__)


def _verify_hash_integrity(
    capsule_id: str,
    capsule_data: dict,
) -> Tuple[bool, Dict[str, Any]]:
    """Recompute manifest hash and verify against stored hash."""
    from src.governance.fingerprinting import make_capsule_manifest_hash

    has_mutation_snapshot = capsule_data.get("_has_mutation_snapshot", True)
    has_tenant_attribution = "tenant_id" in capsule_data

    if not has_mutation_snapshot:
        manifest_version = "v1"
    elif has_tenant_attribution:
        manifest_version = "v3"
    else:
        manifest_version = "v2"

    manifest: Dict[str, Any] = {
        "session_id": capsule_data.get("session_id", ""),
        "query_hash": capsule_data.get("query_hash", ""),
        "scope_lock_id": capsule_data.get("scope_lock_id", ""),
        "intent_id": capsule_data.get("intent_id", ""),
        "proposal_id": capsule_data.get("proposal_id", ""),
        "evidence_ids": sorted(capsule_data.get("evidence_ids", [])),
    }
    if manifest_version in ("v2", "v3"):
        manifest["mutation_ids"] = sorted(capsule_data.get("mutation_ids") or [])
    if manifest_version == "v3":
        manifest["tenant_id"] = capsule_data.get("tenant_id", "")

    recomputed = make_capsule_manifest_hash(capsule_id, manifest, manifest_version)
    stored = capsule_data.get("capsule_hash", "")
    ok = recomputed == stored

    details: Dict[str, Any] = {
        "expected": stored,
        "computed": recomputed,
        "manifest_version": manifest_version,
    }
    return ok, details


def _verify_primacy(capsule_data: dict) -> Tuple[bool, str, Dict[str, Any]]:
    """Re-run ledger primacy verification for capsule evidence."""
    from src.agents.integrator_agent import integrator_agent

    return integrator_agent._verify_evidence_primacy(
        session_id=capsule_data.get("session_id", ""),
        evidence_ids=capsule_data.get("evidence_ids", []),
        expected_scope_lock_id=capsule_data.get("scope_lock_id"),
    )


def _verify_mutation_linkage(
    capsule_id: str,
    mutation_ids: List[str],
) -> Tuple[bool, Dict[str, Any]]:
    """Verify all manifest mutation_ids are linked to this capsule in the ledger.

    Batches TypeQL lookups (up to 50 per query) to avoid N+1.
    """
    if not mutation_ids:
        return True, {"verified_count": 0, "missing": []}

    try:
        from src.db.typedb_client import TypeDBConnection

        db = TypeDBConnection()
        if db._mock_mode:
            return True, {
                "verified_count": 0,
                "missing": list(mutation_ids),
                "skipped": "mock_mode",
            }

        def _esc(s: str) -> str:
            return (str(s) or "").replace("\\", "\\\\").replace('"', '\\"')

        seen: set[str] = set()
        chunk_size = 50
        for i in range(0, len(mutation_ids), chunk_size):
            chunk = mutation_ids[i : i + chunk_size]
            or_conditions = " or ".join(
                [f'{{ $mid == "{_esc(m)}"; }}' for m in chunk]
            )
            query = f"""
            match
                $cap isa run-capsule, has capsule-id "{_esc(capsule_id)}";
                $mut isa mutation-event, has mutation-id $mid;
                {or_conditions};
                (mutation-event: $mut, capsule: $cap) isa asserted-by;
            get $mid;
            """
            rows = db.query_fetch(query)
            for row in rows:
                seen.add(row.get("mid"))

        missing = sorted(set(mutation_ids) - seen)
        return len(missing) == 0, {"verified_count": len(seen), "missing": missing}
    except Exception as e:
        return False, {
            "verified_count": 0,
            "missing": list(mutation_ids),
            "error": str(e),
        }


def verify_capsule(capsule_id: str, capsule_data: dict) -> "ReplayVerdictV1":
    """
    Verify a run capsule against the ledger.

    Args:
        capsule_id:   The capsule identifier.
        capsule_data: Pre-fetched capsule manifest dict, including
                      ``_has_mutation_snapshot`` flag for backward compat.

    Returns:
        ReplayVerdictV1 with status PASS or FAIL and detailed reasons.
    """
    from src.sdk.types import ReplayVerdictV1

    reasons: List[str] = []
    details: Dict[str, Any] = {}

    # 1. Hash integrity
    hash_ok, hash_details = _verify_hash_integrity(capsule_id, capsule_data)
    details["hash_integrity"] = hash_details
    if not hash_ok:
        reasons.append(
            f"Manifest hash mismatch (expected {hash_details['expected'][:12]}…, "
            f"got {hash_details['computed'][:12]}…)"
        )

    # 2. Primacy verification
    primacy_ok, primacy_code, primacy_details = _verify_primacy(capsule_data)
    details["primacy"] = {"code": primacy_code, **primacy_details}
    if not primacy_ok:
        hold_reason = primacy_details.get("hold_reason", primacy_code)
        reasons.append(f"Primacy check failed: [{primacy_code}] {hold_reason}")

    # 3. Mutation linkage
    mutation_ids = capsule_data.get("mutation_ids") or []
    mutation_ok, mutation_details = _verify_mutation_linkage(capsule_id, mutation_ids)
    details["mutation_linkage"] = mutation_details
    if not mutation_ok:
        reasons.append(
            f"Mutation linkage failed: {mutation_details.get('missing', [])}"
        )

    overall = hash_ok and primacy_ok and mutation_ok
    return ReplayVerdictV1(
        status="PASS" if overall else "FAIL",
        reasons=reasons,
        details=details,
    )
