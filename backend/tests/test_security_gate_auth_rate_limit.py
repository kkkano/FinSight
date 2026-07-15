from __future__ import annotations

from fastapi.testclient import TestClient


def test_security_gate_rejects_missing_api_key_when_enabled(monkeypatch):
    from backend.api import main

    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_KEYS", "release-key-1")
    import backend.api.security_gate as _sg; monkeypatch.setattr(_sg, "_rate_limiter", main.SimpleRateLimiter(limit_per_window=100, window_seconds=60, enabled=False))

    with TestClient(main.app) as client:
        response = client.get("/api/user/profile", params={"user_id": "auth-check"})

    assert response.status_code == 401
    assert response.json().get("detail") == "Unauthorized"


def test_security_gate_returns_503_when_auth_enabled_without_keys(monkeypatch):
    from backend.api import main

    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.delenv("API_AUTH_KEYS", raising=False)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    import backend.api.security_gate as _sg; monkeypatch.setattr(_sg, "_rate_limiter", main.SimpleRateLimiter(limit_per_window=100, window_seconds=60, enabled=False))

    with TestClient(main.app) as client:
        response = client.get("/api/user/profile", params={"user_id": "auth-empty-keys"})

    assert response.status_code == 503
    assert "no keys configured" in str(response.json().get("detail", "")).lower()


def test_security_gate_allowlisted_path_bypasses_auth(monkeypatch):
    from backend.api import main

    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_KEYS", "release-key-1")
    import backend.api.security_gate as _sg; monkeypatch.setattr(_sg, "_rate_limiter", main.SimpleRateLimiter(limit_per_window=100, window_seconds=60, enabled=False))

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_security_gate_dashboard_is_anonymous_read_only_by_default(monkeypatch):
    from backend.api import main

    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_AUTH_KEYS", "release-key-1")
    monkeypatch.delenv("API_PUBLIC_PATHS", raising=False)
    monkeypatch.delenv("API_PUBLIC_READ_PATHS", raising=False)
    from backend.config.settings import security_settings
    security_settings.cache_clear()
    import backend.api.security_gate as _sg; monkeypatch.setattr(_sg, "_rate_limiter", main.SimpleRateLimiter(limit_per_window=100, window_seconds=60, enabled=False))

    with TestClient(main.app) as client:
        read_response = client.get("/api/dashboard/not-a-route")
        write_response = client.post("/api/dashboard/not-a-route")

    assert read_response.status_code == 404
    assert write_response.status_code == 401
    assert write_response.json().get("detail") == "Unauthorized"


def test_allowlisted_paths_can_be_configured_via_env(monkeypatch):
    from backend.api import security_gate
    from backend.config.settings import security_settings

    monkeypatch.delenv("API_PUBLIC_PATHS", raising=False)
    security_settings.cache_clear()
    assert security_gate._is_allowlisted_path("/api/dashboard") is False

    monkeypatch.setenv("API_PUBLIC_PATHS", "/health,/api/dashboard")
    security_settings.cache_clear()
    assert security_gate._is_allowlisted_path("/api/dashboard") is True
    assert security_gate._is_allowlisted_path("/api/dashboard/sub") is False


def test_security_gate_rate_limit_blocks_second_request(monkeypatch):
    from backend.api import main

    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    import backend.api.security_gate as _sg; monkeypatch.setattr(_sg, "_rate_limiter", main.SimpleRateLimiter(limit_per_window=1, window_seconds=60, enabled=True))

    with TestClient(main.app) as client:
        first = client.get("/api/user/profile", params={"user_id": "rl-check"})
        second = client.get("/api/user/profile", params={"user_id": "rl-check"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json().get("detail") == "Rate limit exceeded"
    assert second.headers.get("Retry-After") is not None


# ---------------------------------------------------------------------------
# 2026-06-03 线上 CORS 事故回归测试
# ---------------------------------------------------------------------------


def test_rate_limited_response_carries_cors_headers(monkeypatch):
    """429 响应必须带 CORS 头——否则浏览器报 CORS 错误掩盖真实的限流提示。"""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://finsight-ai.chat")

    import importlib
    import backend.api.security_gate as security_gate_module
    import backend.api.main as main_module
    importlib.reload(security_gate_module)  # 限流器实例已迁 security_gate（WP3-T6），env 重读需重载新家
    importlib.reload(main_module)

    from fastapi.testclient import TestClient

    client = TestClient(main_module.app)
    origin = {"Origin": "https://finsight-ai.chat"}

    # 第一个请求通过，第二个触发限流
    client.get("/api/portfolio/summary?session_id=cors-test", headers=origin)
    resp = client.get("/api/portfolio/summary?session_id=cors-test", headers=origin)

    assert resp.status_code == 429
    # 关键断言：429 响应必须带 CORS 头（CORS middleware 在最外层）
    assert resp.headers.get("access-control-allow-origin"), (
        "429 response missing CORS headers — browser will mask it as a CORS error"
    )

    # 善后：reload 过的模块持有 1/min 限流器实例，会污染同会话后续 API 测试
    #（WP3-T6 后实例住 security_gate；此前该测试同样遗留污染，只是恰好无人踩中）。
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    importlib.reload(security_gate_module)
    importlib.reload(main_module)


def test_client_ip_resolution_prefers_cloudflare_header():
    """Cloudflare Tunnel 后面必须用 CF-Connecting-IP，否则全体用户共享限流桶。"""
    import backend.api.security_gate as security_gate_module
    from unittest.mock import MagicMock

    request = MagicMock()
    request.headers = {"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8, 9.9.9.9"}
    request.client.host = "172.18.0.5"  # docker 内部 IP

    assert security_gate_module._resolve_client_ip(request) == "1.2.3.4"

    # 无 CF 头时用 X-Forwarded-For 首个
    request.headers = {"X-Forwarded-For": "5.6.7.8, 9.9.9.9"}
    assert security_gate_module._resolve_client_ip(request) == "5.6.7.8"

    # 都没有时回退连接对端
    request.headers = {}
    assert security_gate_module._resolve_client_ip(request) == "172.18.0.5"
