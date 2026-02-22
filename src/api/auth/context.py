"""
TRUST-1.2.1 Auth Context
Provides strict JWT validation and fail-closed isolation context.
"""

import logging
from typing import Any, Dict, Literal, Optional

import jwt
from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.config import config

logger = logging.getLogger(__name__)


class AuthContextV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    role: Literal["viewer", "operator", "admin"]
    subject: str
    issuer: Optional[str] = None
    issued_at: Optional[int] = None
    expires_at: Optional[int] = None
    auth_type: Literal["jwt", "header"]
    claims_subset: Dict[str, Any] = {}


def get_auth_context(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id"),
    x_role: Optional[str] = Header(default=None, alias="X-Role"),
) -> AuthContextV1:
    """Extract and validate the authentication context from JWT or fallback."""
    # 1. Try JWT validation if token is present
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer ") :]

        # Determine strictness dynamically
        if (
            not config.auth.jwt_secret
            and config.auth.env == "dev"
            and config.auth.allow_insecure_headers
        ):
            # Test mode handling where secret might not be properly populated but token is passed.
            pass  # we still try to parse below
        elif not config.auth.jwt_secret:
            logger.error("AUTH_JWT_SECRET is not configured.")
            raise HTTPException(status_code=500, detail="Configuration error")

        try:
            # We enforce HS256 algorithm securely
            options = {
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": bool(config.auth.jwt_issuer),
                "verify_aud": bool(config.auth.jwt_audience),
            }
            claims = jwt.decode(
                token,
                key=config.auth.jwt_secret,
                algorithms=["HS256"],
                issuer=config.auth.jwt_issuer,
                audience=config.auth.jwt_audience,
                options=options,
            )

            # Map claims to fields
            tenant_id = claims.get("tenant_id") or claims.get("tid")
            if not tenant_id:
                raise HTTPException(status_code=401, detail="JWT missing tenant identifier")

            role_str = claims.get("role", "viewer").lower()
            if role_str not in ("viewer", "operator", "admin"):
                role_str = "viewer"

            subject = claims.get("sub")
            if not subject:
                raise HTTPException(status_code=401, detail="JWT missing subject (sub)")

            whitelisted_claims = {
                k: v
                for k, v in claims.items()
                if k not in ("tenant_id", "tid", "role", "sub", "iss", "iat", "exp", "aud")
            }

            return AuthContextV1(
                tenant_id=tenant_id,
                role=role_str,
                subject=subject,
                issuer=claims.get("iss"),
                issued_at=claims.get("iat"),
                expires_at=claims.get("exp"),
                auth_type="jwt",
                claims_subset=whitelisted_claims,
            )

        except jwt.ExpiredSignatureError:
            logger.warning("Expired JWT token.")
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")

    # 2. Triple-gated header fallback check
    if not authorization:
        if config.auth.allow_insecure_headers and config.auth.env == "dev":
            if not x_tenant_id or not x_tenant_id.strip():
                raise HTTPException(status_code=401, detail="Missing authentication")

            role_str = (x_role or "viewer").strip().lower()
            if role_str not in ("viewer", "operator", "admin"):
                role_str = "viewer"

            return AuthContextV1(
                tenant_id=x_tenant_id.strip(),
                role=role_str,
                subject="dev-fallback-user",
                auth_type="header",
                claims_subset={},
            )

    # 3. Fail closed if not authenticated
    raise HTTPException(status_code=401, detail="Missing or invalid authentication")
