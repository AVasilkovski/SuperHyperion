"""
Tests for TRUST-1.2 API Core Endpoints
"""

from unittest.mock import AsyncMock, patch

import jwt
from fastapi.testclient import TestClient

from src.api.main import app
from src.config import config
from src.sdk.types import GovernedResultV1, ReplayVerdictV1

config.auth.jwt_secret = "test-secret"
config.auth.env = "prod"
config.auth.allow_insecure_headers = False

client = TestClient(app)

def create_test_token(tenant_id: str, role: str) -> dict:
    token = jwt.encode(
        {"tenant_id": tenant_id, "role": role, "sub": "test-user"},
        "test-secret",
        algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}

# Common Headers
H_VIEWER = create_test_token("t-123", "viewer")
H_OPERATOR = create_test_token("t-123", "operator")


# 1) test_api_run_requires_operator_role
def test_api_run_requires_operator_role():
    response = client.post("/v1/run", headers=H_VIEWER, json={"query": "test", "mode": "grounded"})
    assert response.status_code == 403
    assert "operator or admin" in response.json()["detail"]


# 2) test_api_run_requires_tenant_header_fail_closed
def test_api_run_requires_tenant_header_fail_closed():
    # Missing token completely
    response = client.post("/v1/run", headers={}, json={"query": "test", "mode": "grounded"})
    assert response.status_code == 401
    assert "authentication" in str(response.json()["detail"]).lower()


# 3) test_api_run_threads_tenant_id_to_governedrun
@patch("src.sdk.governed_run.GovernedRun.run", new_callable=AsyncMock)
def test_api_run_threads_tenant_id_to_governedrun(mock_run):
    # Setup mock return value
    mock_run.return_value = GovernedResultV1(
        status="COMMIT", response="Success", tenant_id="t-123"
    )

    req_data = {"query": "test query", "session_id": "s-123", "mode": "grounded"}
    response = client.post("/v1/run", headers=H_OPERATOR, json=req_data)

    assert response.status_code == 200
    
    mock_run.assert_called_once_with(
        query="test query",
        tenant_id="t-123",
        session_id="s-123",
        thread_id=None,
        mode="grounded"
    )
    
    res_data = response.json()
    assert res_data["contract_version"] == "v1"
    assert res_data["result"]["status"] == "COMMIT"


# 4) test_api_capsules_returns_404_on_tenant_mismatch
@patch("src.api.routes.v1_core.fetch_capsule_by_id_scoped")
def test_api_capsules_returns_404_on_tenant_mismatch(mock_fetch):
    # Mocking that the capsule is either not found or doesn't belong to tenant
    mock_fetch.return_value = None

    response = client.get("/v1/audit/export?capsule_id=cap-999", headers=H_VIEWER)
    
    assert response.status_code == 404
    mock_fetch.assert_called_once_with("t-123", "cap-999")
    # Crucial semantic check: it's not a 403 leak
    assert "Capsule not found" in response.json()["detail"]


# 5) test_api_capsules_pagination_contract
@patch("src.api.routes.v1_core.list_capsules_for_tenant")
def test_api_capsules_pagination_contract(mock_list):
    # Provide dummy typedb dictionary return types
    mock_items = [
        {
            "capsule_id": "cap-A",
            "session_id": "s-A",
            "created_at": "2026-02-22T00:00:01",
        },
        {
            "capsule_id": "cap-B",
            "session_id": "s-B",
            "created_at": "2026-02-22T00:00:00",
        },
    ]
    mock_list.return_value = (mock_items, "encoded-cursor-string")

    response = client.get("/v1/capsules?limit=2", headers=H_VIEWER)

    assert response.status_code == 200
    data = response.json()
    
    assert data["contract_version"] == "v1"
    assert data["tenant_id"] == "t-123"
    assert data["next_cursor"] == "encoded-cursor-string"
    assert len(data["items"]) == 2
    assert data["items"][0]["capsule_id"] == "cap-A"


# 6) test_api_audit_export_calls_verify_capsule_with_tenant
@patch("src.api.routes.v1_core.fetch_capsule_by_id_scoped")
@patch("src.verification.replay_verify.verify_capsule")
def test_api_audit_export_calls_verify_capsule_with_tenant(mock_verify, mock_fetch):
    # Mock capsule fetched from DB
    mock_fetch.return_value = {
        "capsule_id": "cap-777",
        "created_at": "2026-02-22T00:00:00",
        "manifest_version": "v2",
        "unknown_key": "should_be_stripped"
    }
    
    # Mock verify_capsule returning PASS
    mock_verify.return_value = ReplayVerdictV1(status="PASS", reasons=[])

    response = client.get("/v1/audit/export?capsule_id=cap-777", headers=H_VIEWER)
    
    assert response.status_code == 200
    data = response.json()
    
    mock_verify.assert_called_once_with("cap-777", capsule_data=mock_fetch.return_value, tenant_id="t-123")
    
    # Check that contract filtering worked
    assert "unknown_key" not in data["capsule_manifest"]
    assert data["capsule_manifest"]["capsule_id"] == "cap-777"
    assert data["replay_verdict"]["status"] == "PASS"

# 7) test_api_auth_fails_before_typedb
@patch("src.api.routes.v1_core.list_capsules_for_tenant")
def test_api_auth_fails_before_typedb(mock_list):
    # Mock to ensure it raises if called
    mock_list.side_effect = Exception("TypeDB should not be reached!")
    
    response = client.get("/v1/capsules", headers={})
    assert response.status_code == 401
    
    # Prove the DB read function was never invoked
    mock_list.assert_not_called()
