"""内部调用与模型设置共用凭据验证，不能通过一层又被另一层拒绝。"""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api import security_gate as gate
from backend.config.settings import clear_settings_caches
from backend.services.model_selection import require_model_access


@pytest.mark.parametrize("valid", [True, False])
def test_internal_key_establishes_identity_without_user_jwt(monkeypatch, valid):
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_KEYS", "fixture-service-token")
    monkeypatch.setenv("SUPABASE_AUTH_REQUIRED", "true")
    monkeypatch.setattr(gate, "resolve_request_user", lambda _request: pytest.fail("不应再次要求用户 JWT"))
    clear_settings_caches()
    app = FastAPI()
    app.middleware("http")(gate.security_gate)

    @app.post('/api/execute')
    def execute(request: Request):
        return {"user_id": request.state.user_id, "model_user": require_model_access(request)["user_id"]}

    with TestClient(app) as client:
        response = client.post('/api/execute', headers={"X-API-Key": "fixture-service-token" if valid else "wrong"})
    assert response.status_code == (200 if valid else 401)
    if valid:
        assert response.json() == {"user_id": "internal", "model_user": "internal"}
