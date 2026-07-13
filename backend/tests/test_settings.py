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
    monkeypatch.delenv("FINSIGHT_DAG_EXECUTOR", raising=False)
    monkeypatch.delenv("FINSIGHT_EVIDENCE_BUS", raising=False)
    clear_settings_caches()
    defaults = executor_settings()
    assert defaults.live_tools is False
    assert defaults.dag_executor is True
    assert defaults.evidence_bus is True

    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "true")
    monkeypatch.setenv("LANGGRAPH_EXECUTION_PROGRESS_HEARTBEAT_SECONDS", "0.75")
    clear_settings_caches()
    settings = executor_settings()
    assert settings.live_tools is True
    assert settings.progress_heartbeat_seconds == 0.75

    monkeypatch.setenv("FINSIGHT_DAG_EXECUTOR", "false")
    monkeypatch.setenv("FINSIGHT_EVIDENCE_BUS", "off")
    clear_settings_caches()
    rollback = executor_settings()
    assert rollback.dag_executor is False
    assert rollback.evidence_bus is False


def test_agent_settings_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("AGENT_LLM_ANALYZE_ENABLED", raising=False)
    monkeypatch.delenv("FINSIGHT_AGENT_BRIEF", raising=False)
    clear_settings_caches()
    defaults = agent_settings()
    assert defaults.llm_analyze_enabled is False
    assert defaults.brief_enabled is True

    monkeypatch.setenv("AGENT_LLM_ANALYZE_ENABLED", "yes")
    monkeypatch.setenv("LANGGRAPH_AGENT_TEMPERATURE", "0.35")
    clear_settings_caches()
    settings = agent_settings()
    assert settings.llm_analyze_enabled is True
    assert settings.temperature == 0.35

    monkeypatch.setenv("FINSIGHT_AGENT_BRIEF", "false")
    clear_settings_caches()
    assert agent_settings().brief_enabled is False


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
