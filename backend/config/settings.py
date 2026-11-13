"""运行时配置的 typed settings 事实源。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, ValidationError, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class _DomainSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, env_file=None,
                                      populate_by_name=True, hide_input_in_errors=True, allow_inf_nan=False)


class ExecutorSettings(_DomainSettings):
    live_tools: bool = Field(False, validation_alias=AliasChoices("FINSIGHT_EXECUTE_LIVE_TOOLS", "LANGGRAPH_EXECUTE_LIVE_TOOLS"))
    progress_heartbeat_seconds: float = Field(
        2.5, validation_alias=AliasChoices("FINSIGHT_EXECUTION_PROGRESS_HEARTBEAT_SECONDS", "LANGGRAPH_EXECUTION_PROGRESS_HEARTBEAT_SECONDS")
    )
    research_ledger_enabled: bool = Field(True, validation_alias="RESEARCH_LEDGER_ENABLED")
    jina_enrich_evidence: bool = Field(True, validation_alias="JINA_ENRICH_EVIDENCE")
    agent_invoker_timeout_seconds: float = Field(
        180.0, validation_alias=AliasChoices("FINSIGHT_AGENT_INVOKER_TIMEOUT_SECONDS", "LANGGRAPH_AGENT_INVOKER_TIMEOUT_SECONDS")
    )
    deep_search_agent_timeout_seconds: float | None = Field(
        None, validation_alias=AliasChoices("FINSIGHT_DEEP_SEARCH_AGENT_TIMEOUT_SECONDS", "LANGGRAPH_DEEP_SEARCH_AGENT_TIMEOUT_SECONDS")
    )
    agent_invoker_retry_attempts: int = Field(
        2, validation_alias=AliasChoices("FINSIGHT_AGENT_INVOKER_RETRY_ATTEMPTS", "LANGGRAPH_AGENT_INVOKER_RETRY_ATTEMPTS")
    )


class SecuritySettings(_DomainSettings):
    api_auth_enabled: bool = Field(False, validation_alias="API_AUTH_ENABLED")
    api_auth_keys: str = Field("", validation_alias="API_AUTH_KEYS", repr=False, exclude=True)
    api_auth_key: str = Field("", validation_alias="API_AUTH_KEY", repr=False, exclude=True)
    api_public_paths: str | None = Field(None, validation_alias="API_PUBLIC_PATHS")
    api_public_read_paths: str | None = Field(None, validation_alias="API_PUBLIC_READ_PATHS")
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
    supabase_auth_required: bool = Field(False, validation_alias="SUPABASE_AUTH_REQUIRED")
    vite_supabase_url: str = Field("", validation_alias="VITE_SUPABASE_URL")
    supabase_jwt_secret: str = Field("", validation_alias="SUPABASE_JWT_SECRET", repr=False, exclude=True)
    supabase_publishable_key: str = Field("", validation_alias="SUPABASE_PUBLISHABLE_KEY", repr=False, exclude=True)
    vite_supabase_publishable_key: str = Field(
        "", validation_alias="VITE_SUPABASE_PUBLISHABLE_KEY", repr=False, exclude=True
    )


class RuntimeSettings(_DomainSettings):
    """原生研究预算；旧名称只作为过渡输入，不影响US20显式预算。"""
    app_mode: str = Field("development", validation_alias="APP_MODE")
    profile: str = Field("", validation_alias="FINSIGHT_RUNTIME_PROFILE")
    timeout_seconds: float | None = Field(None, ge=1, validation_alias="FINSIGHT_RUN_TIMEOUT_SECONDS")
    report_timeout_seconds: float | None = Field(None, ge=1, validation_alias="FINSIGHT_RUN_TIMEOUT_REPORT_SECONDS")
    brief_timeout_seconds: float | None = Field(None, ge=1, validation_alias="FINSIGHT_RUN_TIMEOUT_BRIEF_SECONDS")
    legacy_timeout_seconds: float = Field(180, validation_alias="LANGGRAPH_EXECUTION_TIMEOUT_SECONDS")
    legacy_report_timeout_seconds: float = Field(300, validation_alias="LANGGRAPH_EXECUTION_TIMEOUT_REPORT_SECONDS")
    legacy_brief_timeout_seconds: float | None = Field(None, validation_alias="LANGGRAPH_EXECUTION_TIMEOUT_BRIEF_SECONDS")
    context_window: int | None = Field(None, validation_alias="FINSIGHT_AGENT_CONTEXT_WINDOW")
    max_output_tokens: int | None = Field(None, validation_alias="FINSIGHT_AGENT_MAX_OUTPUT_TOKENS")
    max_turns: int = Field(12, ge=1, le=20, validation_alias="FINSIGHT_AGENT_MAX_TURNS")
    token_budget: int = Field(160000, ge=1, validation_alias="FINSIGHT_AGENT_TOKEN_BUDGET")

    @field_validator("legacy_timeout_seconds", "legacy_report_timeout_seconds", "legacy_brief_timeout_seconds", mode="before")
    @classmethod
    def legacy_float(cls, value, info: ValidationInfo):
        defaults = {"legacy_timeout_seconds": 180.0, "legacy_report_timeout_seconds": 300.0,
                    "legacy_brief_timeout_seconds": None}
        if value is None:
            return defaults[info.field_name]
        try:
            parsed = float(value)
        except (ValueError, TypeError):
            return defaults[info.field_name]
        return max(1.0, parsed)

    @property
    def production(self) -> bool:
        return any(value.strip().lower() in {"prod", "production"} for value in (self.app_mode, self.profile))


class LimitsSettings(_DomainSettings):
    max_active_runs: int = Field(2, ge=1, validation_alias="FINSIGHT_AGENT_MAX_ACTIVE_RUNS")
    model_concurrency: int = Field(2, ge=1, validation_alias="FINSIGHT_AGENT_MODEL_CONCURRENCY")
    model_rpm: int = Field(30, ge=1, validation_alias="FINSIGHT_AGENT_RPM_LIMIT")
    model_tpm: int = Field(250000, ge=1, validation_alias="FINSIGHT_AGENT_TPM_LIMIT")
    min_request_interval_seconds: float = Field(0, ge=0, le=60, validation_alias="FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS")
    artifact_cache_max_mb: int = Field(512, ge=16, validation_alias="FINSIGHT_ARTIFACT_CACHE_MAX_MB")


class ProvidersSettings(_DomainSettings):
    agent_model: str = Field("", validation_alias="FINSIGHT_AGENT_MODEL")
    agent_api_base: str = Field("", validation_alias="FINSIGHT_AGENT_API_BASE", repr=False, exclude=True)
    agent_api_key: str = Field("", validation_alias="FINSIGHT_AGENT_API_KEY", repr=False, exclude=True)
    agent_stepfun_api_key: str = Field("", validation_alias="FINSIGHT_AGENT_STEPFUN_API_KEY", repr=False, exclude=True)
    agent_qwen_api_key: str = Field("", validation_alias="FINSIGHT_AGENT_QWEN_API_KEY", repr=False, exclude=True)
    primary_model: str = Field("", validation_alias="OPENAI_COMPATIBLE_MODEL")
    primary_api_base: str = Field("", validation_alias="OPENAI_COMPATIBLE_API_BASE", repr=False, exclude=True)
    primary_api_key: str = Field("", validation_alias="OPENAI_COMPATIBLE_API_KEY", repr=False, exclude=True)
    secondary_model: str = Field("", validation_alias="GEMINI_PROXY_MODEL")
    secondary_api_base: str = Field("", validation_alias="GEMINI_PROXY_API_BASE", repr=False, exclude=True)
    secondary_api_key: str = Field("", validation_alias="GEMINI_PROXY_API_KEY", repr=False, exclude=True)
    stepfun_api_key: str = Field("", validation_alias="STEPFUN_API_KEY", repr=False, exclude=True)
    analysis_worker_url: str = Field("", validation_alias="FINSIGHT_ANALYSIS_WORKER_URL", repr=False, exclude=True)
    analysis_worker_token: str = Field("", validation_alias="FINSIGHT_ANALYSIS_WORKER_TOKEN", repr=False, exclude=True)
    rag_worker_url: str = Field("", validation_alias="RAG_WORKER_URL", repr=False, exclude=True)
    rag_worker_token: str = Field("", validation_alias="RAG_WORKER_TOKEN", repr=False, exclude=True)
    embedding_api_key: str = Field("", validation_alias="RAG_EMBEDDING_API_KEY", repr=False, exclude=True)
    rerank_api_key: str = Field("", validation_alias="RAG_RERANK_API_KEY", repr=False, exclude=True)
    finnhub_api_key: str = Field("", validation_alias="FINNHUB_API_KEY", repr=False, exclude=True)
    twelve_data_api_key: str = Field("", validation_alias="TWELVE_DATA_API_KEY", repr=False, exclude=True)
    fred_api_key: str = Field("", validation_alias="FRED_API_KEY", repr=False, exclude=True)
    tavily_api_key: str = Field("", validation_alias="TAVILY_API_KEY", repr=False, exclude=True)
    exa_api_key: str = Field("", validation_alias="EXA_API_KEY", repr=False, exclude=True)


_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class StorageSettings(_DomainSettings):
    config_dir: Path | None = Field(None, validation_alias="FINSIGHT_CONFIG_DIR")
    quota_db: Path | None = Field(None, validation_alias="FINSIGHT_RUNTIME_QUOTA_DB")
    action_store: Path | None = Field(None, validation_alias="FINSIGHT_ACTION_STORE")
    artifact_dir: Path | None = Field(None, validation_alias="FINSIGHT_ARTIFACT_DIR")
    postgres_dsn: str = Field("", validation_alias="FINSIGHT_POSTGRES_DSN", repr=False, exclude=True)
    checkpoint_dsn: str = Field("", validation_alias="LANGGRAPH_CHECKPOINT_POSTGRES_DSN", repr=False, exclude=True)
    rag_postgres_dsn: str = Field("", validation_alias="RAG_V2_POSTGRES_DSN", repr=False, exclude=True)
    agent_prediction_postgres_dsn: str = Field("", validation_alias="AGENT_PREDICTION_POSTGRES_DSN", repr=False, exclude=True)

    @field_validator("config_dir", "quota_db", "action_store", "artifact_dir", mode="before")
    @classmethod
    def empty_path(cls, value):
        return None if value == "" else value

    def paths(self) -> dict[str, Path]:
        return {"config_dir": self.config_dir or _DATA_DIR,
                "quota_db": self.quota_db or _DATA_DIR / "runtime_quota.sqlite",
                "action_store": self.action_store or _DATA_DIR / "runtime_actions.sqlite",
                "artifact_dir": self.artifact_dir or _DATA_DIR / "agent_artifacts"}

    @property
    def core_postgres_configured(self) -> bool:
        return any(value.strip() for value in (self.postgres_dsn, self.agent_prediction_postgres_dsn,
                                               self.rag_postgres_dsn, self.checkpoint_dsn))


class FeaturesSettings(_DomainSettings):
    llm_required: bool = Field(False, validation_alias="FINSIGHT_LLM_REQUIRED")
    anonymous_generation: bool = Field(False, validation_alias="ALLOW_ANONYMOUS_GENERATION")
    prediction_generation: bool = Field(True, validation_alias="PREDICTION_GENERATION_ENABLED")
    prediction_outcomes: bool = Field(True, validation_alias="PREDICTION_OUTCOME_SCHEDULER_ENABLED")
    monitor_realtime: bool = Field(True, validation_alias="MONITOR_REALTIME_ENABLED")
    us20_enabled: bool = Field(False, validation_alias="PREDICTION_ENABLED")
    agent_vision: bool = Field(False, validation_alias="FINSIGHT_AGENT_VISION")


# 认证继续使用既有SecuritySettings对象，避免两个缓存产生不一致的认证事实。
AuthSettings = SecuritySettings


@lru_cache(maxsize=1)
def runtime_settings() -> RuntimeSettings:
    return RuntimeSettings()


@lru_cache(maxsize=1)
def limits_settings() -> LimitsSettings:
    return LimitsSettings()


@lru_cache(maxsize=1)
def providers_settings() -> ProvidersSettings:
    return ProvidersSettings()


@lru_cache(maxsize=1)
def storage_settings() -> StorageSettings:
    return StorageSettings()


@lru_cache(maxsize=1)
def features_settings() -> FeaturesSettings:
    return FeaturesSettings()


def auth_settings() -> AuthSettings:
    return security_settings()


def native_budget_seconds(entry: str) -> float:
    """API注入原生预算；预测/monitor仍使用冻结的既有预算入口。"""
    if entry == "us20_forecast":
        return 60.0
    if entry in {"prediction", "monitor"}:
        from backend.services.run_context import run_budget_seconds
        return run_budget_seconds(entry)
    settings = runtime_settings()
    if entry == "investment_report":
        return settings.report_timeout_seconds or settings.legacy_report_timeout_seconds
    if entry == "brief":
        return (settings.brief_timeout_seconds or settings.legacy_brief_timeout_seconds
                or settings.timeout_seconds or settings.legacy_timeout_seconds)
    return settings.timeout_seconds or settings.legacy_timeout_seconds


class RuntimeConfigurationError(ValueError):
    """错误只返回字段/代码，不携带原始输入、DSN或凭据。"""
    def __init__(self, issues: list[dict[str, str]]):
        self.issues = issues
        super().__init__("运行配置无效：" + "; ".join(item["field"] + ": " + item["code"] for item in issues))


def _storage_issues(settings: StorageSettings) -> list[dict[str, str]]:
    issues = []
    for name, path in settings.paths().items():
        resolved = path.resolve()
        is_file = name in {"quota_db", "action_store"}
        if resolved.exists() and (resolved.is_dir() if is_file else not resolved.is_dir()):
            issues.append({"field": name, "code": "storage_path_type_conflict"})
            continue
        directory = resolved.parent if is_file else resolved
        while not directory.exists() and directory != directory.parent:
            directory = directory.parent
        if not directory.is_dir():
            issues.append({"field": name, "code": "storage_parent_not_directory"})
            continue
        try:
            if is_file and resolved.exists():
                # 打开已存在文件但不写入，不碰SQLite内容。
                with resolved.open("ab"):
                    pass
            with tempfile.TemporaryFile(prefix="finsight-write-probe-", dir=directory) as probe:
                probe.write(b"probe")
                probe.flush()
        except OSError:
            issues.append({"field": name, "code": "storage_path_not_writable"})
    return issues


def validate_startup_settings(*, check_storage: bool = True) -> dict[str, _DomainSettings]:
    domains = {}
    issues = []
    for name, getter in {"runtime": runtime_settings, "limits": limits_settings, "providers": providers_settings,
                         "storage": storage_settings, "features": features_settings, "auth": auth_settings}.items():
        try:
            domains[name] = getter()
        except ValidationError as exc:
            issues.extend({"field": name + "." + ".".join(map(str, item["loc"])), "code": item["type"]}
                          for item in exc.errors(include_input=False, include_context=False))
    if issues:
        raise RuntimeConfigurationError(issues)
    runtime, limits, providers, storage, features, auth = (domains[name] for name in
        ("runtime", "limits", "providers", "storage", "features", "auth"))
    if {"app_mode", "profile"}.issubset(runtime.model_fields_set) and runtime.profile:
        modes = [value.strip().lower() in {"prod", "production"} for value in (runtime.app_mode, runtime.profile)]
        if modes[0] != modes[1]:
            issues.append({"field": "runtime.profile", "code": "runtime_profile_conflict"})
    groups = [("agent", providers.agent_model, providers.agent_api_base, providers.agent_api_key),
              ("primary", providers.primary_model, providers.primary_api_base, providers.primary_api_key),
              ("secondary", providers.secondary_model, providers.secondary_api_base, providers.secondary_api_key)]
    for name, model, base, key in groups:
        if any(value.strip() for value in (model, base, key)) and not all(value.strip() for value in (model, base, key)):
            issues.append({"field": "providers." + name, "code": "provider_configuration_incomplete"})
        if base:
            try:
                uri = urlsplit(base)
                valid = uri.scheme in {"http", "https"} and bool(uri.hostname) and not (uri.username or uri.password or uri.query or uri.fragment)
            except ValueError:
                valid = False
            if not valid:
                issues.append({"field": "providers." + name + "_api_base", "code": "invalid_provider_base_url"})
    if features.llm_required and not (providers.stepfun_api_key.strip() or any(all(value.strip() for value in group[1:]) for group in groups)):
        issues.append({"field": "providers", "code": "required_model_unconfigured"})
    if providers.agent_model.strip():
        from backend.agent_runtime.config import model_budgets
        window, output = model_budgets(providers.agent_model.strip())
        window = max(4096, runtime.context_window if runtime.context_window is not None else window)
        output = max(512, runtime.max_output_tokens if runtime.max_output_tokens is not None else output)
        if output >= window or output > runtime.token_budget:
            issues.append({"field": "runtime.max_output_tokens", "code": "model_budget_conflict"})
    if runtime.production:
        if features.anonymous_generation or not auth.supabase_auth_required or not auth.rate_limit_enabled:
            issues.append({"field": "auth", "code": "production_security_conflict"})
        if not storage.core_postgres_configured:
            issues.append({"field": "storage.postgres_dsn", "code": "production_storage_unconfigured"})
    if auth.api_auth_enabled and not (auth.api_auth_keys.strip() or auth.api_auth_key.strip()):
        issues.append({"field": "auth.api_auth_key", "code": "required_api_auth_key_missing"})
    if auth.supabase_auth_required and not (auth.supabase_jwt_secret.strip() or auth.supabase_url.strip() or auth.vite_supabase_url.strip()):
        issues.append({"field": "auth.supabase_url", "code": "required_auth_verifier_missing"})
    for name in ("supabase_publishable_key", "vite_supabase_publishable_key"):
        if getattr(auth, name).startswith("sb_secret_"):
            issues.append({"field": "auth." + name, "code": "secret_key_in_public_key_field"})
    for name in ("supabase_url", "vite_supabase_url"):
        url = getattr(auth, name)
        if not url:
            continue
        try:
            uri = urlsplit(url)
            valid = uri.scheme in {"http", "https"} and bool(uri.hostname) and not (uri.username or uri.password or uri.query or uri.fragment)
        except ValueError:
            valid = False
        if not valid:
            issues.append({"field": "auth." + name, "code": "invalid_auth_url"})
    if auth.supabase_url and auth.vite_supabase_url:
        try:
            hosts = [urlsplit(url).hostname or "" for url in (auth.supabase_url, auth.vite_supabase_url)]
            if all(host.endswith(".supabase.co") for host in hosts) and hosts[0] != hosts[1]:
                issues.append({"field": "auth.supabase_url", "code": "auth_project_conflict"})
        except ValueError:
            issues.append({"field": "auth.supabase_url", "code": "invalid_auth_url"})
    if check_storage and not issues:
        issues.extend(_storage_issues(storage))
    if issues:
        raise RuntimeConfigurationError(issues)
    return domains


@lru_cache(maxsize=1)
def executor_settings() -> ExecutorSettings:
    return ExecutorSettings()


@lru_cache(maxsize=1)
def security_settings() -> SecuritySettings:
    return SecuritySettings()


def clear_settings_caches() -> None:
    for getter in (executor_settings, security_settings, runtime_settings, limits_settings,
                   providers_settings, storage_settings, features_settings):
        getter.cache_clear()


__all__ = [
    "ExecutorSettings",
    "SecuritySettings",
    "clear_settings_caches",
    "executor_settings",
    "security_settings",
    "RuntimeSettings", "LimitsSettings", "ProvidersSettings", "StorageSettings", "FeaturesSettings", "AuthSettings",
    "runtime_settings", "limits_settings", "providers_settings", "storage_settings", "features_settings", "auth_settings",
    "native_budget_seconds", "validate_startup_settings", "RuntimeConfigurationError",
]
