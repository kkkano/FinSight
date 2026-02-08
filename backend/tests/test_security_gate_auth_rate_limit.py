from __future__ import annotations

from fastapi.testclient import TestClient


def test_security_gate_rejects_missing_api_key_when_enabled(monkeypatch):
    from backend.api import main

    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_KEYS", "release-key-1")
    monkeypatch.setattr(main, "_rate_limiter", main.SimpleRateLimiter(limit_per_window=100, window_seconds=60, enabled=False))

    with TestClient(main.app) as client:
        response = client.get("/api/user/profile", params={"user_id": "auth-check"})

    assert response.status_code == 401
    assert response.json().get("detail") == "Unauthorized"


def test_security_gate_returns_503_when_auth_enabled_without_keys(monkeypatch):
    from backend.api import main

    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.delenv("API_AUTH_KEYS", raising=False)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(main, "_rate_limiter", main.SimpleRateLimiter(limit_per_window=100, window_seconds=60, enabled=False))

    with TestClient(main.app) as client:
        response = client.get("/api/user/profile", params={"user_id": "auth-empty-keys"})

    assert response.status_code == 503
    assert "no keys configured" in str(response.json().get("detail", "")).lower()


def test_security_gate_allowlisted_path_bypasses_auth(monkeypatch):
    from backend.api import main

    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_KEYS", "release-key-1")
    monkeypatch.setattr(main, "_rate_limiter", main.SimpleRateLimiter(limit_per_window=100, window_seconds=60, enabled=False))

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_security_gate_dashboard_requires_auth_by_default(monkeypatch):
    from backend.api import main

    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_KEYS", "release-key-1")
    monkeypatch.delenv("API_PUBLIC_PATHS", raising=False)
    monkeypatch.setattr(main, "_rate_limiter", main.SimpleRateLimiter(limit_per_window=100, window_seconds=60, enabled=False))

    with TestClient(main.app) as client:
        response = client.get("/api/dashboard", params={"symbol": "AAPL"})

    assert response.status_code == 401
    assert response.json().get("detail") == "Unauthorized"


def test_allowlisted_paths_can_be_configured_via_env(monkeypatch):
    from backend.api import main

    monkeypatch.delenv("API_PUBLIC_PATHS", raising=False)
    assert main._is_allowlisted_path("/api/dashboard") is False

    monkeypatch.setenv("API_PUBLIC_PATHS", "/health,/api/dashboard")
    assert main._is_allowlisted_path("/api/dashboard") is True
    assert main._is_allowlisted_path("/api/dashboard/sub") is False


def test_security_gate_rate_limit_blocks_second_request(monkeypatch):
    from backend.api import main

    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    monkeypatch.setattr(main, "_rate_limiter", main.SimpleRateLimiter(limit_per_window=1, window_seconds=60, enabled=True))

    with TestClient(main.app) as client:
        first = client.get("/api/user/profile", params={"user_id": "rl-check"})
        second = client.get("/api/user/profile", params={"user_id": "rl-check"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json().get("detail") == "Rate limit exceeded"
    assert second.headers.get("Retry-After") is not None
