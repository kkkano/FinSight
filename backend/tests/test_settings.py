from __future__ import annotations

from backend.config.settings import (
    clear_settings_caches,
    executor_settings,
    security_settings,
)


def test_executor_settings_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", raising=False)
    clear_settings_caches()
    defaults = executor_settings()
    assert defaults.live_tools is False

    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "true")
    monkeypatch.setenv("LANGGRAPH_EXECUTION_PROGRESS_HEARTBEAT_SECONDS", "0.75")
    clear_settings_caches()
    settings = executor_settings()
    assert settings.live_tools is True
    assert settings.progress_heartbeat_seconds == 0.75


def test_security_settings_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("API_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    clear_settings_caches()
    defaults = security_settings()
    assert defaults.api_auth_enabled is False
    assert defaults.rate_limit_enabled is True

    monkeypatch.setenv("API_AUTH_ENABLED", "on")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "17")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "false")
    clear_settings_caches()
    settings = security_settings()
    assert settings.api_auth_enabled is True
    assert settings.rate_limit_per_minute == 17
    assert settings.trust_proxy_headers is False
