"""运行时配置的 typed settings 事实源。"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class _DomainSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)


class PlannerSettings(_DomainSettings):
    mode: str = Field("llm", validation_alias="LANGGRAPH_PLANNER_MODE")
    report_timeout_sec: int = Field(240, validation_alias="LANGGRAPH_PLANNER_REPORT_TIMEOUT_SEC")
    report_max_tokens: int = Field(6000, validation_alias="LANGGRAPH_PLANNER_REPORT_MAX_TOKENS")
    report_max_attempts: int = Field(3, validation_alias="LANGGRAPH_PLANNER_REPORT_MAX_ATTEMPTS")
    report_acquire_timeout_sec: int = Field(
        180, validation_alias="LANGGRAPH_PLANNER_REPORT_ACQUIRE_TIMEOUT_SEC"
    )
    chat_timeout_sec: int = Field(150, validation_alias="LANGGRAPH_PLANNER_CHAT_TIMEOUT_SEC")
    chat_max_tokens: int = Field(3000, validation_alias="LANGGRAPH_PLANNER_CHAT_MAX_TOKENS")
    chat_max_attempts: int = Field(2, validation_alias="LANGGRAPH_PLANNER_CHAT_MAX_ATTEMPTS")
    chat_acquire_timeout_sec: int = Field(
        120, validation_alias="LANGGRAPH_PLANNER_CHAT_ACQUIRE_TIMEOUT_SEC"
    )
    ab_enabled: bool = Field(False, validation_alias="LANGGRAPH_PLANNER_AB_ENABLED")
    ab_split: int = Field(50, validation_alias="LANGGRAPH_PLANNER_AB_SPLIT")
    ab_salt: str = Field("planner-ab-v1", validation_alias="LANGGRAPH_PLANNER_AB_SALT")
    temperature: float = Field(0.2, validation_alias="LANGGRAPH_PLANNER_TEMPERATURE")
    json_repair_attempts: int = Field(2, validation_alias="LANGGRAPH_PLANNER_JSON_REPAIR_ATTEMPTS")


class ExecutorSettings(_DomainSettings):
    live_tools: bool = Field(False, validation_alias="LANGGRAPH_EXECUTE_LIVE_TOOLS")
    progress_heartbeat_seconds: float = Field(
        2.5, validation_alias="LANGGRAPH_EXECUTION_PROGRESS_HEARTBEAT_SECONDS"
    )
    dag_executor: bool = Field(False, validation_alias="FINSIGHT_DAG_EXECUTOR")
    evidence_bus: bool = Field(False, validation_alias="FINSIGHT_EVIDENCE_BUS")
    research_ledger_enabled: bool = Field(True, validation_alias="RESEARCH_LEDGER_ENABLED")
    jina_enrich_evidence: bool = Field(True, validation_alias="JINA_ENRICH_EVIDENCE")
    agent_invoker_timeout_seconds: float = Field(
        180.0, validation_alias="LANGGRAPH_AGENT_INVOKER_TIMEOUT_SECONDS"
    )
    deep_search_agent_timeout_seconds: float | None = Field(
        None, validation_alias="LANGGRAPH_DEEP_SEARCH_AGENT_TIMEOUT_SECONDS"
    )
    agent_invoker_retry_attempts: int = Field(
        2, validation_alias="LANGGRAPH_AGENT_INVOKER_RETRY_ATTEMPTS"
    )


class AgentSettings(_DomainSettings):
    temperature: float = Field(0.2, validation_alias="LANGGRAPH_AGENT_TEMPERATURE")
    brief_enabled: bool = Field(False, validation_alias="FINSIGHT_AGENT_BRIEF")
    llm_analyze_enabled: bool = Field(False, validation_alias="AGENT_LLM_ANALYZE_ENABLED")
    llm_analyze_timeout_seconds: float = Field(
        8.0, validation_alias="AGENT_LLM_ANALYZE_TIMEOUT_SECONDS"
    )
    llm_analyze_call_timeout_seconds: float = Field(
        8.0, validation_alias="AGENT_LLM_ANALYZE_CALL_TIMEOUT_SECONDS"
    )
    base_max_reflections: int | None = Field(None, validation_alias="BASE_AGENT_MAX_REFLECTIONS")
    reflection_token_timeout_seconds: float = Field(
        12.0, validation_alias="BASE_AGENT_REFLECTION_TOKEN_TIMEOUT_SECONDS"
    )
    force_research_config: bool = Field(
        False, validation_alias="FINSIGHT_FORCE_AGENT_RESEARCH_CONFIG"
    )


class SecuritySettings(_DomainSettings):
    api_auth_enabled: bool = Field(False, validation_alias="API_AUTH_ENABLED")
    api_auth_keys: str = Field("", validation_alias="API_AUTH_KEYS")
    api_auth_key: str = Field("", validation_alias="API_AUTH_KEY")
    api_public_paths: str | None = Field(None, validation_alias="API_PUBLIC_PATHS")
    trust_proxy_headers: bool = Field(True, validation_alias="TRUST_PROXY_HEADERS")
    rate_limit_enabled: bool = Field(True, validation_alias="RATE_LIMIT_ENABLED")
    rate_limit_per_minute: int = Field(300, validation_alias="RATE_LIMIT_PER_MINUTE")
    rate_limit_window_seconds: int = Field(60, validation_alias="RATE_LIMIT_WINDOW_SECONDS")
    concurrency_limit_enabled: bool = Field(True, validation_alias="CONCURRENCY_LIMIT_ENABLED")
    generation_max_concurrent: int = Field(10, validation_alias="GENERATION_MAX_CONCURRENT")
    generation_max_concurrent_per_client: int = Field(
        2, validation_alias="GENERATION_MAX_CONCURRENT_PER_CLIENT"
    )
    supabase_url: str = Field("", validation_alias="SUPABASE_URL")
    vite_supabase_url: str = Field("", validation_alias="VITE_SUPABASE_URL")
    supabase_publishable_key: str = Field("", validation_alias="SUPABASE_PUBLISHABLE_KEY")
    vite_supabase_publishable_key: str = Field(
        "", validation_alias="VITE_SUPABASE_PUBLISHABLE_KEY"
    )
    rag_dev_auth_enabled: bool = Field(
        False, validation_alias="RAG_OBSERVABILITY_DEV_AUTH_ENABLED"
    )
    rag_dev_access_token: str = Field(
        "", validation_alias="RAG_OBSERVABILITY_DEV_ACCESS_TOKEN"
    )
    rag_dev_user_id: str = Field(
        "local-rag-inspector", validation_alias="RAG_OBSERVABILITY_DEV_USER_ID"
    )
    rag_dev_email: str = Field(
        "local-rag@example.com", validation_alias="RAG_OBSERVABILITY_DEV_EMAIL"
    )
    rag_auth_cache_seconds: int = Field(
        60, validation_alias="RAG_OBSERVABILITY_AUTH_CACHE_SECONDS"
    )


@lru_cache(maxsize=1)
def planner_settings() -> PlannerSettings:
    return PlannerSettings()


@lru_cache(maxsize=1)
def executor_settings() -> ExecutorSettings:
    return ExecutorSettings()


@lru_cache(maxsize=1)
def agent_settings() -> AgentSettings:
    return AgentSettings()


@lru_cache(maxsize=1)
def security_settings() -> SecuritySettings:
    return SecuritySettings()


def clear_settings_caches() -> None:
    planner_settings.cache_clear()
    executor_settings.cache_clear()
    agent_settings.cache_clear()
    security_settings.cache_clear()


__all__ = [
    "AgentSettings",
    "ExecutorSettings",
    "PlannerSettings",
    "SecuritySettings",
    "agent_settings",
    "clear_settings_caches",
    "executor_settings",
    "planner_settings",
    "security_settings",
]
