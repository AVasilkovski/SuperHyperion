"""
TRUST-1.2 API Routes
"""

import logging
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.contracts.v1 import (
    AuditExportV1,
    CapsuleListItemV1,
    CapsuleListV1,
    RoleEnum,
    RunRequestV1,
    RunResponseV1,
)
from src.api.deps import get_request_context, require_operator
from src.api.services.typedb_reads import (
    fetch_capsule_by_id_scoped,
    list_capsules_for_tenant,
)

# Defer importing GovernedRun and verify_capsule so they don't block startup or leak
# state implicitly at import time for API layer.

logger = logging.getLogger(__name__)

router = APIRouter(tags=["core"])


@router.post("/run", response_model=RunResponseV1)
async def trigger_run(
    request: RunRequestV1,
    context: Tuple[str, RoleEnum] = Depends(get_request_context),
):
    """TRUST-1.2: Trigger a new epistemic run scoped to the tenant."""
    tenant_id, role = context

    # Enforce operator/admin role
    require_operator(role)

    # Local import
    from src.sdk.governed_run import GovernedRun

    try:
        # Pydantic validates payload, GovernedRun handles the rest
        result = await GovernedRun.run(
            query=request.query,
            tenant_id=tenant_id,
            session_id=request.session_id,
            thread_id=request.thread_id,
            mode=request.mode,
            **request.options,
        )
        return RunResponseV1(contract_version="v1", result=result)

    except Exception as e:
        logger.error(f"GovernedRun failed for tenant {tenant_id}: {e}")
        # Return 500 error but do not leak secrets
        raise HTTPException(
            status_code=500,
            detail={"error_code": "RUN_ERROR", "message": "Unexpected execution failure"},
        )


@router.get("/capsules", response_model=CapsuleListV1)
async def list_capsules(
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None, description="Pagination cursor"),
    context: Tuple[str, RoleEnum] = Depends(get_request_context),
):
    """TRUST-1.2: Fetch a paginated list of capsules owned by the tenant."""
    tenant_id, role = context
    # Viewers can access this endpoint

    items, next_cursor = list_capsules_for_tenant(
        tenant_id=tenant_id, limit=limit, cursor=cursor
    )

    capsule_items = []
    for row in items:
        # map db fields to model (TypeDB returns dict with '-' or '_' keys, typedb_reads handled translation to '_')
        capsule_items.append(CapsuleListItemV1(**row))

    return CapsuleListV1(
        contract_version="v1",
        tenant_id=tenant_id,
        items=capsule_items,
        next_cursor=next_cursor,
    )


@router.get("/audit/export", response_model=AuditExportV1)
async def export_audit_ledger(
    capsule_id: str = Query(..., description="The ID of the capsule to export"),
    context: Tuple[str, RoleEnum] = Depends(get_request_context),
):
    """TRUST-1.2: Export cryptographic proof of reasoning, scoping fail-closed."""
    tenant_id, role = context

    # 1. Fetch capsule scoped to tenant (returns None if not found or not owned)
    db_capsule = fetch_capsule_by_id_scoped(tenant_id, capsule_id)
    if not db_capsule:
        raise HTTPException(
            status_code=404, detail="Capsule not found or unavailable."
        )

    # 2. Run deterministic verification on the capsule
    from src.verification.replay_verify import verify_capsule

    try:
        # We explicitly thread `tenant_id` to `verify_capsule` for defense-in-depth.
        # verify_capsule signature is verify_capsule(capsule_id, capsule_data, *, tenant_id=None)
        verdict = verify_capsule(capsule_id, capsule_data=db_capsule, tenant_id=tenant_id)
    except Exception as e:
        logger.error(f"Replay verification failed: {e}")
        raise HTTPException(
            status_code=500, detail="Audit verification failed to execute."
        )

    # 3. Construct the clean capsule manifest
    # We use db_capsule but make sure to only include allowed keys, e.g., the canonical manifest
    manifest_keys = [
        "capsule_id",
        "session_id",
        "query_hash",
        "scope_lock_id",
        "intent_id",
        "proposal_id",
        "created_at",
        "manifest_version",
    ]
    capsule_manifest = {
        k: db_capsule[k] for k in manifest_keys if k in db_capsule and db_capsule[k]
    }

    # If it was missing manifest_version in DB, supply a default
    if "manifest_version" not in capsule_manifest:
        capsule_manifest["manifest_version"] = "v2"

    return AuditExportV1(
        contract_version="v1",
        tenant_id=tenant_id,
        capsule_manifest=capsule_manifest,
        replay_verdict=verdict,
    )
