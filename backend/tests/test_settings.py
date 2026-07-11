from __future__ import annotations

from backend.config.settings import (
    agent_settings,
    clear_settings_caches,
    executor_settings,
    planner_settings,
    security_settings,
)


def test_planner_settings_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("LANGGRAPH_PLANNER_REPORT_TIMEOUT_SEC", raising=False)
    clear_settings_caches()
    assert planner_settings().report_timeout_sec == 240

    monkeypatch.setenv("LANGGRAPH_PLANNER_REPORT_TIMEOUT_SEC", "321")
    monkeypatch.setenv("LANGGRAPH_PLANNER_AB_ENABLED", "true")
    clear_settings_caches()
    settings = planner_settings()
    assert settings.report_timeout_sec == 321
    assert settings.ab_enabled is True


def test_executor_settings_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", raising=False)
    clear_settings_caches()
    assert executor_settings().live_tools is False

    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "true")
    monkeypatch.setenv("LANGGRAPH_EXECUTION_PROGRESS_HEARTBEAT_SECONDS", "0.75")
    clear_settings_caches()
    settings = executor_settings()
    assert settings.live_tools is True
    assert settings.progress_heartbeat_seconds == 0.75


def test_agent_settings_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("AGENT_LLM_ANALYZE_ENABLED", raising=False)
    clear_settings_caches()
    assert agent_settings().llm_analyze_enabled is False

    monkeypatch.setenv("AGENT_LLM_ANALYZE_ENABLED", "yes")
    monkeypatch.setenv("LANGGRAPH_AGENT_TEMPERATURE", "0.35")
    clear_settings_caches()
    settings = agent_settings()
    assert settings.llm_analyze_enabled is True
    assert settings.temperature == 0.35


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
