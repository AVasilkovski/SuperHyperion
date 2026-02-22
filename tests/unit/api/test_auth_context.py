import jwt
import pytest
from fastapi import HTTPException

from src.api.auth.context import get_auth_context
from src.config import config


class MockRequest:
    pass


def test_auth_missing_token_fails_closed_401(monkeypatch):
    monkeypatch.setattr(config.auth, "allow_insecure_headers", False)
    monkeypatch.setattr(config.auth, "env", "prod")

    with pytest.raises(HTTPException) as exc:
        get_auth_context(
            MockRequest(), authorization=None, x_tenant_id="tenant-1", x_role="operator"
        )
    assert exc.value.status_code == 401
    assert "authentication" in str(exc.value.detail).lower()


def test_auth_invalid_token_fails_closed_401(monkeypatch):
    monkeypatch.setattr(config.auth, "jwt_secret", "secret")

    with pytest.raises(HTTPException) as exc:
        get_auth_context(MockRequest(), authorization="Bearer invalid.token.here")
    assert exc.value.status_code == 401
    assert "invalid token" in str(exc.value.detail).lower()


def test_auth_valid_token_threads_tenant_and_role(monkeypatch):
    monkeypatch.setattr(config.auth, "jwt_secret", "secret")
    monkeypatch.setattr(config.auth, "jwt_issuer", None)
    monkeypatch.setattr(config.auth, "jwt_audience", None)

    token = jwt.encode(
        {"tenant_id": "tenant-123", "role": "admin", "sub": "user-1", "custom_claim": "value"},
        "secret",
        algorithm="HS256",
    )

    auth_ctx = get_auth_context(MockRequest(), authorization=f"Bearer {token}")
    assert auth_ctx.tenant_id == "tenant-123"
    assert auth_ctx.role == "admin"
    assert auth_ctx.subject == "user-1"
    assert auth_ctx.auth_type == "jwt"
    assert auth_ctx.claims_subset == {"custom_claim": "value"}


def test_insecure_header_fallback_only_when_env_enabled_and_dev(monkeypatch):
    monkeypatch.setattr(config.auth, "allow_insecure_headers", True)
    monkeypatch.setattr(config.auth, "env", "dev")

    auth_ctx = get_auth_context(
        MockRequest(), authorization=None, x_tenant_id="tenant-123", x_role="operator"
    )
    assert auth_ctx.tenant_id == "tenant-123"
    assert auth_ctx.role == "operator"
    assert auth_ctx.auth_type == "header"

    # Negative test (env != dev)
    monkeypatch.setattr(config.auth, "env", "prod")
    with pytest.raises(HTTPException) as exc:
        get_auth_context(
            MockRequest(), authorization=None, x_tenant_id="tenant-123", x_role="operator"
        )
    assert exc.value.status_code == 401


def test_token_present_ignores_headers(monkeypatch):
    monkeypatch.setattr(config.auth, "jwt_secret", "secret")
    monkeypatch.setattr(config.auth, "jwt_issuer", None)
    monkeypatch.setattr(config.auth, "jwt_audience", None)
    monkeypatch.setattr(config.auth, "allow_insecure_headers", True)
    monkeypatch.setattr(config.auth, "env", "dev")

    token = jwt.encode(
        {"tenant_id": "tenant-jwt", "role": "admin", "sub": "user-jwt"}, "secret", algorithm="HS256"
    )

    auth_ctx = get_auth_context(
        MockRequest(), authorization=f"Bearer {token}", x_tenant_id="tenant-header", x_role="viewer"
    )
    assert auth_ctx.tenant_id == "tenant-jwt"
    assert auth_ctx.role == "admin"
    assert auth_ctx.auth_type == "jwt"
