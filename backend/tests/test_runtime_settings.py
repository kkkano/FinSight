"""typed域、兼容预算、安全错误和存储启动合同；不接入真实模型/数据库。"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import AliasChoices

from backend.config import settings as module


@pytest.fixture(autouse=True)
def isolated_runtime_environment(monkeypatch, tmp_path):
    classes = [module.ExecutorSettings, module.SecuritySettings, module.RuntimeSettings, module.LimitsSettings,
               module.ProvidersSettings, module.StorageSettings, module.FeaturesSettings]
    for cls in classes:
        for field in cls.model_fields.values():
            alias = field.validation_alias
            names = alias.choices if isinstance(alias, AliasChoices) else [alias]
            for name in names:
                if isinstance(name, str):
                    monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FINSIGHT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("FINSIGHT_RUNTIME_QUOTA_DB", str(tmp_path / "quota.sqlite"))
    monkeypatch.setenv("FINSIGHT_ACTION_STORE", str(tmp_path / "actions.sqlite"))
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    module.clear_settings_caches()
    yield
    module.clear_settings_caches()


def test_legacy_environment_collection_keeps_effective_budgets_and_properties(monkeypatch):
    old = {"LANGGRAPH_EXECUTION_TIMEOUT_SECONDS": "71.5", "LANGGRAPH_EXECUTION_TIMEOUT_REPORT_SECONDS": "210",
           "LANGGRAPH_EXECUTE_LIVE_TOOLS": "yes", "LANGGRAPH_EXECUTION_PROGRESS_HEARTBEAT_SECONDS": "0.75",
           "LANGGRAPH_AGENT_INVOKER_TIMEOUT_SECONDS": "42", "LANGGRAPH_DEEP_SEARCH_AGENT_TIMEOUT_SECONDS": "84",
           "LANGGRAPH_AGENT_INVOKER_RETRY_ATTEMPTS": "3", "API_AUTH_ENABLED": "on",
           "API_AUTH_KEY": "fixture-internal-key", "RATE_LIMIT_PER_MINUTE": "17", "TRUST_PROXY_HEADERS": "false"}
    for key, value in old.items():
        monkeypatch.setenv(key, value)
    module.clear_settings_caches()
    executor, auth = module.executor_settings(), module.security_settings()
    assert (module.native_budget_seconds("chat"), module.native_budget_seconds("brief"),
            module.native_budget_seconds("investment_report")) == (71.5, 71.5, 210)
    assert (executor.live_tools, executor.progress_heartbeat_seconds, executor.agent_invoker_timeout_seconds,
            executor.deep_search_agent_timeout_seconds, executor.agent_invoker_retry_attempts) == (True, 0.75, 42, 84, 3)
    assert (auth.api_auth_enabled, auth.api_auth_key, auth.rate_limit_per_minute, auth.trust_proxy_headers) == (True, "fixture-internal-key", 17, False)
    assert module.auth_settings() is auth


def test_new_names_override_old_aliases_and_keep_report_brief_separate(monkeypatch):
    values = {"LANGGRAPH_EXECUTION_TIMEOUT_SECONDS": "100", "LANGGRAPH_EXECUTION_TIMEOUT_REPORT_SECONDS": "200",
              "LANGGRAPH_EXECUTION_TIMEOUT_BRIEF_SECONDS": "40", "FINSIGHT_RUN_TIMEOUT_SECONDS": "61",
              "FINSIGHT_RUN_TIMEOUT_REPORT_SECONDS": "211", "FINSIGHT_RUN_TIMEOUT_BRIEF_SECONDS": "31",
              "LANGGRAPH_EXECUTE_LIVE_TOOLS": "false", "FINSIGHT_EXECUTE_LIVE_TOOLS": "true"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    module.clear_settings_caches()
    assert [module.native_budget_seconds(entry) for entry in ["chat", "brief", "investment_report"]] == [61, 31, 211]
    assert module.executor_settings().live_tools is True


@pytest.mark.parametrize("value,expected", [("not-a-number", 180), ("-5", 1), ("0", 1)])
def test_legacy_budget_fallback_and_clamping_match_the_old_reader(monkeypatch, value, expected):
    monkeypatch.setenv("LANGGRAPH_EXECUTION_TIMEOUT_SECONDS", value)
    module.clear_settings_caches()
    assert module.native_budget_seconds("chat") == module.native_budget_seconds("brief") == expected


def test_invalid_new_timeout_is_a_startup_error_instead_of_a_silent_fallback(monkeypatch):
    monkeypatch.setenv("FINSIGHT_RUN_TIMEOUT_SECONDS", "invalid-timeout")
    monkeypatch.setenv("LANGGRAPH_EXECUTION_TIMEOUT_SECONDS", "73")
    module.clear_settings_caches()
    with pytest.raises(module.RuntimeConfigurationError) as captured:
        module.validate_startup_settings(check_storage=False)
    assert any(item["code"] == "float_parsing" for item in captured.value.issues)


def test_native_alias_does_not_change_prediction_or_monitor_budget(monkeypatch):
    monkeypatch.setenv("FINSIGHT_RUN_TIMEOUT_SECONDS", "999")
    monkeypatch.setenv("PREDICTION_RUN_TIMEOUT_SECONDS", "37")
    monkeypatch.setenv("MONITOR_COMMENT_TIMEOUT_SECONDS", "13")
    module.clear_settings_caches()
    assert module.native_budget_seconds("us20_forecast") == 60
    assert module.native_budget_seconds("prediction") == 37
    assert module.native_budget_seconds("monitor") == 13


def test_cache_clear_updates_all_domains_and_auth_keeps_a_single_object(monkeypatch):
    first = module.runtime_settings()
    providers = module.providers_settings()
    monkeypatch.setenv("FINSIGHT_RUN_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("FINSIGHT_AGENT_MODEL", "fixture-model")
    assert module.runtime_settings() is first and module.providers_settings() is providers
    module.clear_settings_caches()
    assert module.runtime_settings().timeout_seconds == 90
    assert module.providers_settings().agent_model == "fixture-model"
    assert module.auth_settings() is module.security_settings()


@pytest.mark.parametrize("retired_value", ["legacy", "agent2", "invalid-runtime"])
def test_retired_runtime_selector_is_not_a_settings_field(monkeypatch, retired_value):
    monkeypatch.setenv("FINSIGHT_RESEARCH_RUNTIME", retired_value)
    module.clear_settings_caches()
    runtime = module.validate_startup_settings(check_storage=False)["runtime"]
    assert "research_runtime" not in module.RuntimeSettings.model_fields
    assert "research_runtime" not in runtime.model_dump()
    assert module.native_budget_seconds("chat") == 180


def test_secrets_and_dsn_do_not_appear_in_settings_repr_or_serialization(monkeypatch):
    secret = "fixture-private-value-that-must-not-appear"
    for key in ["FINSIGHT_AGENT_API_KEY", "OPENAI_COMPATIBLE_API_KEY", "FINSIGHT_ANALYSIS_WORKER_TOKEN",
                "RAG_WORKER_TOKEN", "API_AUTH_KEYS", "SUPABASE_JWT_SECRET", "SUPABASE_PUBLISHABLE_KEY",
                "VITE_SUPABASE_PUBLISHABLE_KEY", "FINSIGHT_POSTGRES_DSN"]:
        monkeypatch.setenv(key, secret)
    module.clear_settings_caches()
    for value in [module.providers_settings(), module.security_settings(), module.storage_settings()]:
        assert secret not in repr(value) and secret not in value.model_dump_json()
        assert secret not in json.dumps(value.model_dump(), default=str)


def test_startup_validation_error_has_codes_without_echoing_sensitive_inputs(monkeypatch):
    secret = "fixture-secret-int-parsing-input"
    monkeypatch.setenv("FINSIGHT_AGENT_MAX_TURNS", secret)
    monkeypatch.setenv("FINSIGHT_AGENT_API_KEY", secret)
    module.clear_settings_caches()
    with pytest.raises(module.RuntimeConfigurationError) as captured:
        module.validate_startup_settings(check_storage=False)
    assert secret not in str(captured.value) and secret not in str(captured.value.issues)
    assert any(item["code"] == "int_parsing" for item in captured.value.issues)


def test_partial_provider_and_invalid_endpoint_are_explicit_startup_errors(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_MODEL", "fixture-model")
    monkeypatch.setenv("FINSIGHT_AGENT_API_BASE", "https://private:credential@example.invalid/v1")
    module.clear_settings_caches()
    with pytest.raises(module.RuntimeConfigurationError) as captured:
        module.validate_startup_settings(check_storage=False)
    codes = {item["code"] for item in captured.value.issues}
    assert {"provider_configuration_incomplete", "invalid_provider_base_url"}.issubset(codes)
    assert "credential" not in str(captured.value)


def test_conflicting_model_output_budget_is_rejected(monkeypatch):
    for key, value in {"FINSIGHT_AGENT_MODEL": "fixture-model", "FINSIGHT_AGENT_API_BASE": "https://example.invalid/v1",
                       "FINSIGHT_AGENT_API_KEY": "fixture-key", "FINSIGHT_AGENT_CONTEXT_WINDOW": "4096",
                       "FINSIGHT_AGENT_MAX_OUTPUT_TOKENS": "8192"}.items():
        monkeypatch.setenv(key, value)
    module.clear_settings_caches()
    with pytest.raises(module.RuntimeConfigurationError) as captured:
        module.validate_startup_settings(check_storage=False)
    assert any(item["code"] == "model_budget_conflict" for item in captured.value.issues)


def test_production_and_public_supabase_key_conflicts_fail_closed(monkeypatch):
    for key, value in {"APP_MODE": "production", "FINSIGHT_RUNTIME_PROFILE": "development",
                       "SUPABASE_PUBLISHABLE_KEY": "sb_secret_fixture-not-a-real-key"}.items():
        monkeypatch.setenv(key, value)
    module.clear_settings_caches()
    with pytest.raises(module.RuntimeConfigurationError) as captured:
        module.validate_startup_settings(check_storage=False)
    codes = {item["code"] for item in captured.value.issues}
    assert {"runtime_profile_conflict", "production_security_conflict", "secret_key_in_public_key_field"}.issubset(codes)
    assert "sb_secret_fixture" not in str(captured.value)


def test_existing_jwt_auth_and_legacy_postgres_configuration_remain_valid(monkeypatch):
    for key, value in {"APP_MODE": "production", "SUPABASE_AUTH_REQUIRED": "true",
                       "SUPABASE_JWT_SECRET": "fixture-jwt-secret", "LANGGRAPH_CHECKPOINT_POSTGRES_DSN": "postgresql://fixture.invalid/test",
                       "FINSIGHT_LLM_REQUIRED": "true", "STEPFUN_API_KEY": "fixture-step-key"}.items():
        monkeypatch.setenv(key, value)
    module.clear_settings_caches()
    domains = module.validate_startup_settings(check_storage=False)
    assert domains["storage"].core_postgres_configured is True
    assert domains["auth"].supabase_publishable_key == ""


def test_storage_probe_uses_temporary_directory_without_changing_existing_database(tmp_path, monkeypatch):
    quota = tmp_path / "quota.sqlite"
    quota.write_bytes(b"existing-database-marker")
    before = quota.read_bytes()
    domains = module.validate_startup_settings(check_storage=True)
    assert set(domains) == {"runtime", "limits", "providers", "storage", "features", "auth"}
    assert quota.read_bytes() == before
    assert not list(tmp_path.glob("finsight-write-probe-*"))


def test_storage_type_or_permission_failure_reports_only_the_configuration_field(tmp_path, monkeypatch):
    monkeypatch.setenv("FINSIGHT_RUNTIME_QUOTA_DB", str(tmp_path))
    module.clear_settings_caches()
    with pytest.raises(module.RuntimeConfigurationError) as captured:
        module.validate_startup_settings(check_storage=True)
    assert any(item["code"] == "storage_path_type_conflict" for item in captured.value.issues)
    monkeypatch.setenv("FINSIGHT_RUNTIME_QUOTA_DB", str(tmp_path / "valid.sqlite"))
    def denied(**_kwargs):
        raise PermissionError("private filesystem detail")
    monkeypatch.setattr(module.tempfile, "TemporaryFile", denied)
    module.clear_settings_caches()
    with pytest.raises(module.RuntimeConfigurationError) as captured:
        module.validate_startup_settings(check_storage=True)
    assert any(item["code"] == "storage_path_not_writable" for item in captured.value.issues)
    assert "private filesystem detail" not in str(captured.value)


def test_configured_native_model_uses_typed_provider_without_changing_user_priority(monkeypatch):
    from backend.agent_runtime.config import configured_model, model_budgets, resolve_model
    from backend.services import model_selection
    for key, value in {"FINSIGHT_AGENT_MODEL": "deepseek-v4.1-flash-1017", "FINSIGHT_AGENT_API_BASE": "https://system.invalid/v1/",
                       "FINSIGHT_AGENT_API_KEY": "fixture-system-key"}.items():
        monkeypatch.setenv(key, value)
    module.clear_settings_caches()
    configured = configured_model()
    assert (configured.context_window, configured.max_output) == model_budgets("deepseek-v4.1-flash-1017")
    selected = SimpleNamespace(source="custom", model="unknown-user-model", base_url="https://user.invalid/v1",
                               api_key="fixture-user-key", endpoint_name="chosen", effort="high")
    monkeypatch.setattr(model_selection, "current_model", lambda: selected)
    result = resolve_model()
    assert result.model == selected.model and result.api_key == selected.api_key and result.endpoint_name == "chosen"
    assert (result.context_window, result.max_output) == (32768, 8192)
    assert selected.api_key not in repr(result) and selected.api_key not in json.dumps(result.public_metadata())


def test_selected_system_model_keeps_explicit_runtime_budget_and_effort(monkeypatch):
    from backend.agent_runtime.config import resolve_model
    from backend.services import model_selection
    for key, value in {"FINSIGHT_AGENT_MODEL": "fixture-model", "FINSIGHT_AGENT_API_BASE": "https://system.invalid/v1",
                       "FINSIGHT_AGENT_API_KEY": "fixture-system-key", "FINSIGHT_AGENT_CONTEXT_WINDOW": "65536",
                       "FINSIGHT_AGENT_MAX_OUTPUT_TOKENS": "4096"}.items():
        monkeypatch.setenv(key, value)
    module.clear_settings_caches()
    selected = SimpleNamespace(source="system", model="fixture-model", base_url="https://system.invalid/v1/",
                               api_key="fixture-system-key", endpoint_name="selected-system", effort="low")
    monkeypatch.setattr(model_selection, "current_model", lambda: selected)
    result = resolve_model()
    assert (result.context_window, result.max_output, result.effort) == (65536, 4096, "low")


def test_configuration_import_does_not_load_private_dotenv(monkeypatch):
    import importlib.util
    import sys
    import dotenv
    from backend.agent_runtime import config
    called = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *_args, **_kwargs: called.append(True))
    spec = importlib.util.spec_from_file_location("runtime_config_import_fixture", config.__file__)
    imported = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, imported)
    spec.loader.exec_module(imported)
    assert called == []


def test_frozen_run_context_source_is_not_changed_by_budget_configuration(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "services/run_context.py"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setenv("FINSIGHT_RUN_TIMEOUT_SECONDS", "71")
    module.clear_settings_caches()
    assert module.native_budget_seconds("chat") == 71
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
