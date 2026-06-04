# -*- coding: utf-8 -*-
"""P1-1 / P1-3: 启动配置自检测试

P1-1: 启动时校验关键数据源 API key，缺失显式告警
P1-3: 启动时验证 LLM endpoint，不可用时 chat 请求快速失败（503）而非等待超时
"""

import pytest
from unittest.mock import patch

from backend.services import startup_check
from backend.services.startup_check import (
    StartupCheckResult,
    run_startup_checks,
    is_llm_available,
    get_startup_result,
    IMPORTANT_DATA_SOURCE_KEYS,
)


@pytest.fixture(autouse=True)
def _reset_state():
    """每个测试前后重置模块级状态，避免测试间污染"""
    startup_check._reset_for_testing()
    yield
    startup_check._reset_for_testing()


class TestLLMEndpointCheck:
    """P1-3: LLM endpoint 启动校验"""

    def test_llm_unavailable_when_no_endpoint_configured(self):
        with patch(
            "backend.llm_config.load_user_endpoints",
            side_effect=ValueError("No LLM endpoint configured"),
        ):
            result = run_startup_checks()

        assert result.llm_available is False
        assert result.llm_error is not None
        assert "No LLM endpoint" in result.llm_error

    def test_llm_available_when_endpoint_configured(self):
        fake_endpoint = object()
        with patch(
            "backend.llm_config.load_user_endpoints",
            return_value=[fake_endpoint],
        ):
            result = run_startup_checks()

        assert result.llm_available is True
        assert result.llm_error is None

    def test_llm_unavailable_when_resolution_crashes(self):
        """配置解析崩溃也算不可用（防御性）"""
        with patch(
            "backend.llm_config.load_user_endpoints",
            side_effect=RuntimeError("config file corrupted"),
        ):
            result = run_startup_checks()

        assert result.llm_available is False
        assert "config file corrupted" in result.llm_error


class TestDataSourceKeyCheck:
    """P1-1: 数据源 key 缺失告警"""

    def test_missing_keys_reported(self, monkeypatch):
        for key in IMPORTANT_DATA_SOURCE_KEYS:
            monkeypatch.delenv(key, raising=False)

        with patch("backend.llm_config.load_user_endpoints", return_value=[object()]):
            result = run_startup_checks()

        assert set(result.missing_keys) == set(IMPORTANT_DATA_SOURCE_KEYS)
        assert result.configured_keys == []

    def test_configured_keys_reported(self, monkeypatch):
        for key in IMPORTANT_DATA_SOURCE_KEYS:
            monkeypatch.setenv(key, "test-key-value")

        with patch("backend.llm_config.load_user_endpoints", return_value=[object()]):
            result = run_startup_checks()

        assert set(result.configured_keys) == set(IMPORTANT_DATA_SOURCE_KEYS)
        assert result.missing_keys == []

    def test_blank_value_counts_as_missing(self, monkeypatch):
        """空字符串/纯引号的 key 视为缺失"""
        keys = list(IMPORTANT_DATA_SOURCE_KEYS)
        monkeypatch.setenv(keys[0], "")
        monkeypatch.setenv(keys[1], '""')
        for key in keys[2:]:
            monkeypatch.delenv(key, raising=False)

        with patch("backend.llm_config.load_user_endpoints", return_value=[object()]):
            result = run_startup_checks()

        assert keys[0] in result.missing_keys
        assert keys[1] in result.missing_keys


class TestAgentLLMAnalyzeCheck:
    """P3: AGENT_LLM_ANALYZE_ENABLED 启动校验（关闭则 agent 退化成只列数据）"""

    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("AGENT_LLM_ANALYZE_ENABLED", raising=False)
        with patch("backend.llm_config.load_user_endpoints", return_value=[object()]):
            result = run_startup_checks()
        assert result.agent_llm_analyze_enabled is False

    def test_enabled_when_true(self, monkeypatch):
        monkeypatch.setenv("AGENT_LLM_ANALYZE_ENABLED", "true")
        with patch("backend.llm_config.load_user_endpoints", return_value=[object()]):
            result = run_startup_checks()
        assert result.agent_llm_analyze_enabled is True

    def test_enabled_accepts_truthy_variants(self, monkeypatch):
        for raw in ("1", "yes", "on", "TRUE", "On"):
            startup_check._reset_for_testing()
            monkeypatch.setenv("AGENT_LLM_ANALYZE_ENABLED", raw)
            with patch("backend.llm_config.load_user_endpoints", return_value=[object()]):
                result = run_startup_checks()
            assert result.agent_llm_analyze_enabled is True, raw

    def test_warning_logged_when_disabled(self, monkeypatch, caplog):
        import logging

        monkeypatch.setenv("AGENT_LLM_ANALYZE_ENABLED", "false")
        with patch("backend.llm_config.load_user_endpoints", return_value=[object()]):
            with caplog.at_level(logging.WARNING, logger="backend.services.startup_check"):
                run_startup_checks()
        assert any("AGENT_LLM_ANALYZE_ENABLED" in r.message for r in caplog.records)


class TestIsLLMAvailable:
    """P1-3: chat_router 快速失败依赖的状态查询"""

    def test_default_true_when_not_checked(self):
        """未跑过启动检查时不拦截（向后兼容：测试环境/旧部署）"""
        assert is_llm_available() is True

    def test_false_after_failed_check(self):
        with patch(
            "backend.llm_config.load_user_endpoints",
            side_effect=ValueError("no endpoint"),
        ):
            run_startup_checks()

        assert is_llm_available() is False

    def test_true_after_successful_check(self):
        with patch("backend.llm_config.load_user_endpoints", return_value=[object()]):
            run_startup_checks()

        assert is_llm_available() is True


class TestGetStartupResult:
    """启动检查结果可供外部查询（如 health 接口）"""

    def test_none_before_check(self):
        assert get_startup_result() is None

    def test_returns_result_after_check(self):
        with patch("backend.llm_config.load_user_endpoints", return_value=[object()]):
            run_startup_checks()

        result = get_startup_result()
        assert isinstance(result, StartupCheckResult)
        assert result.llm_available is True


class TestChatRouterFastFail:
    """P1-3: chat_router 在 LLM 不可用时立即 503，不让用户等超时"""

    def test_ensure_llm_available_raises_503_when_unavailable(self):
        from fastapi import HTTPException

        from backend.api.chat_router import _ensure_llm_available

        with patch(
            "backend.llm_config.load_user_endpoints",
            side_effect=ValueError("no endpoint"),
        ):
            run_startup_checks()

        with pytest.raises(HTTPException) as exc_info:
            _ensure_llm_available()
        assert exc_info.value.status_code == 503
        assert "LLM" in exc_info.value.detail

    def test_ensure_llm_available_passes_when_available(self):
        from backend.api.chat_router import _ensure_llm_available

        with patch("backend.llm_config.load_user_endpoints", return_value=[object()]):
            run_startup_checks()

        # 不抛异常即通过
        _ensure_llm_available()

    def test_ensure_llm_available_passes_when_never_checked(self):
        """向后兼容：测试环境没跑启动检查时不拦截"""
        from backend.api.chat_router import _ensure_llm_available

        _ensure_llm_available()
