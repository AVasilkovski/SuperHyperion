from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app

# Minimal integration test to exercise FastAPI routing explicitly

@pytest.fixture
def client():
    return TestClient(app)

def test_api_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"

def test_api_capsules_requires_tenant(client):
    # Tests that the dependency injection is correctly wired in the app
    response = client.get("/v1/capsules")
    assert response.status_code == 400
    assert "X-Tenant-Id" in response.json()["detail"]

def test_api_capsules_with_mocked_db(client):
    with patch("src.api.routes.v1_core.list_capsules_for_tenant") as mock_list:
        mock_list.return_value = ([], None)
    
        response = client.get(
            "/v1/capsules",
            headers={"X-Tenant-Id": "t-123", "X-Role": "operator"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == "t-123"
        assert data["items"] == []
        
        mock_list.assert_called_once_with(tenant_id="t-123", limit=50, cursor=None)
