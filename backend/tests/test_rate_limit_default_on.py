"""P0-7: HTTP 限流必须默认开启（公网产品防裸奔）"""


def test_rate_limiter_enabled_by_default(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    from backend.api.main import SimpleRateLimiter

    limiter = SimpleRateLimiter.from_env()
    assert limiter.enabled is True, "公网产品 HTTP 限流必须默认开启"


def test_rate_limiter_can_be_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    from backend.api.main import SimpleRateLimiter

    limiter = SimpleRateLimiter.from_env()
    assert limiter.enabled is False
