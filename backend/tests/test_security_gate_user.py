from __future__ import annotations

import time

import jwt
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api import security_gate as security_gate_module
from backend.config.settings import security_settings


SECRET = "security-gate-test-secret-at-least-32-bytes"


def _token(sub: str = "user-1") -> str:
    return jwt.encode(
        {
            "sub": sub,
            "email": f"{sub}@example.com",
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
        },
        SECRET,
        algorithm="HS256",
    )


def _app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(security_gate_module.security_gate)

    @app.get("/whoami")
    async def whoami(request: Request) -> dict[str, str]:
        return {
            "user_id": request.state.user_id,
            "email": request.state.user_email,
        }

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.fixture(autouse=True)
def _isolated_security_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    monkeypatch.delenv("SUPABASE_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    security_settings.cache_clear()
    monkeypatch.setattr(
        security_gate_module,
        "_rate_limiter",
        security_gate_module.SimpleRateLimiter(100, 60, enabled=False),
    )
    monkeypatch.setattr(
        security_gate_module,
        "_concurrency_limiter",
        security_gate_module.ConcurrencyLimiter(1, 1, enabled=False),
    )


def test_valid_supabase_user_is_exposed_to_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)

    with TestClient(_app()) as client:
        response = client.get("/whoami", headers={"Authorization": f"Bearer {_token()}"})

    assert response.status_code == 200
    assert response.json() == {"user_id": "user-1", "email": "user-1@example.com"}


def test_auth_required_rejects_anonymous_business_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_AUTH_REQUIRED", "true")

    with TestClient(_app()) as client:
        response = client.get("/whoami")

    assert response.status_code == 401
    assert response.json() == {"detail": "登录后才能使用，请先登录。"}


def test_auth_optional_assigns_public_user() -> None:
    with TestClient(_app()) as client:
        response = client.get("/whoami")

    assert response.status_code == 200
    assert response.json() == {"user_id": "public", "email": ""}


def test_auth_required_still_allows_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_AUTH_REQUIRED", "true")

    with TestClient(_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_authenticated_users_use_separate_rate_limit_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(
        security_gate_module,
        "_rate_limiter",
        security_gate_module.SimpleRateLimiter(1, 60, enabled=True),
    )

    with TestClient(_app()) as client:
        first = client.get("/whoami", headers={"Authorization": f"Bearer {_token('alice')}"})
        second = client.get("/whoami", headers={"Authorization": f"Bearer {_token('bob')}"})
        repeated = client.get("/whoami", headers={"Authorization": f"Bearer {_token('alice')}"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert repeated.status_code == 429
