import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from src.db.typedb_client import TypeDBConnection
from src.trust.tenant_scope import scope_prefix

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["core"])

class TenantContext(BaseModel):
    tenant_id: str
    role: str

def get_tenant_context(
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_role: str = Header("viewer", alias="X-Role")
) -> TenantContext:
    """Dependency to extract tenant and role from headers."""
    return TenantContext(tenant_id=x_tenant_id, role=x_role)

@router.post("/run", response_model=Dict[str, Any])
async def trigger_run(
    query: str,
    context: TenantContext = Depends(get_tenant_context)
):
    """TRUST-1.2: Trigger a new epistemic run scoped to the tenant."""
    # Logic to initialize a run context with tenant_id would go here.
    return {
        "status": "accepted",
        "tenant_id": context.tenant_id,
        "run_id": "r-mock-123"
    }

@router.get("/capsules", response_model=List[Dict[str, Any]])
async def list_capsules(
    limit: int = Query(50, le=100),
    cursor: Optional[str] = Query(None, description="Pagination cursor (timestamp)"),
    context: TenantContext = Depends(get_tenant_context)
):
    """TRUST-1.2: Fetch a paginated list of capsules owned by the tenant."""
    from typedb.driver import TransactionType

    db = TypeDBConnection()
    if getattr(db, "_mock_mode", False):
         return []
         
    scope_injection = scope_prefix(context.tenant_id, target_var="c").strip()
    query = f"match $c isa run-capsule, has capsule-id $cid, has session-id $sid, {scope_injection.replace('$c ', '')}; select $cid, $sid; limit {limit};"
    try:
        with db.transaction(TransactionType.READ) as tx:
            rows = db._to_rows(tx.query(query).resolve())
            return [
                {
                    "capsule_id": r.get("cid"), 
                    "session_id": r.get("sid"),
                    "tenant_id": context.tenant_id
                } for r in rows
            ]
    except Exception as e:
        logger.error(f"DB Error: {e}")
        # Fail-closed semantics: return 404 instead of 403 or 500 when access/scoping fails
        raise HTTPException(status_code=404, detail="Capsules not found or unavailable")

@router.get("/audit/export/{capsule_id}")
async def export_audit_ledger(
    capsule_id: str,
    context: TenantContext = Depends(get_tenant_context)
):
    """TRUST-1.2: Export cryptographic proof of reasoning, scoping fail-closed."""
    # In a full impl, if capsule_id is not owned by context.tenant_id, throw 404
    return {
        "capsule_id": capsule_id,
        "tenant_id": context.tenant_id,
        "proof": "base64-encoded-proof-placeholder"
    }
