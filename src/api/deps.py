"""
TRUST-1.2 API Dependencies
Provides tenant isolation and strict role checks.
"""

from typing import Tuple

from fastapi import Header, HTTPException, Request

from src.api.contracts.v1 import RoleEnum


def get_tenant_id(
    x_tenant_id: str = Header(default=None, alias="X-Tenant-Id")
) -> str:
    """Extract tenant identifier dynamically. Fail-closed if missing."""
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(status_code=400, detail="Missing required X-Tenant-Id header")
    return x_tenant_id.strip()


def get_role(
    x_role: str = Header(default="", alias="X-Role")
) -> RoleEnum:
    """Extract and validate the caller role."""
    role_str = x_role.strip().lower()

    if not role_str:
        return RoleEnum.VIEWER

    try:
        return RoleEnum(role_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {role_str}")


def require_operator(role: RoleEnum) -> RoleEnum:
    """Enforce operator or admin role."""
    if role not in (RoleEnum.OPERATOR, RoleEnum.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Operation requires operator or admin privileges"
        )
    return role


def get_request_context(
    request: Request,
    tenant_id: str = Header(default=None, alias="X-Tenant-Id"),
    role: str = Header(default="", alias="X-Role")
) -> Tuple[str, RoleEnum]:
    """Provide a bundle of tenant_id and role."""
    _tenant = get_tenant_id(x_tenant_id=tenant_id)
    _role = get_role(x_role=role)
    return _tenant, _role
