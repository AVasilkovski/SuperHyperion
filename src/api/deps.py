"""
TRUST-1.2 API Dependencies
Provides tenant isolation and strict role checks.
"""

from typing import Tuple

from fastapi import Depends, HTTPException

from src.api.auth.context import AuthContextV1, get_auth_context
from src.api.contracts.v1 import RoleEnum


def get_tenant_id(
    auth: AuthContextV1 = Depends(get_auth_context)
) -> str:
    """Extract tenant identifier dynamically. Fail-closed if missing."""
    return auth.tenant_id


def get_role(
    auth: AuthContextV1 = Depends(get_auth_context)
) -> RoleEnum:
    """Extract and validate the caller role."""
    try:
        return RoleEnum(auth.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {auth.role}")


def verify_operator_role(auth: AuthContextV1 = Depends(get_auth_context)) -> RoleEnum:
    """Enforce operator or admin role."""
    role = get_role(auth)
    if role not in (RoleEnum.OPERATOR, RoleEnum.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Operation requires operator or admin privileges"
        )
    return role


def get_request_context(
    auth: AuthContextV1 = Depends(get_auth_context)
) -> Tuple[str, RoleEnum]:
    """Provide a bundle of tenant_id and role."""
    return auth.tenant_id, get_role(auth)
