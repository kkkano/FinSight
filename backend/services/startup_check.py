# -*- coding: utf-8 -*-
"""
启动配置自检 (P1-1 / P1-3)

启动时校验关键配置，缺失时显式告警，避免静默退化等到用户请求才暴雷：
- LLM endpoint（P1-3）：缺失则 Chat/报告核心功能不可用，chat_router 据此快速失败（503）
- 数据源 API key（P1-1）：缺失则对应数据源降级，启动日志显式列出
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# P1-1: 重要数据源 key（缺失会导致对应功能降级，但不致命）
IMPORTANT_DATA_SOURCE_KEYS: dict[str, str] = {
    "FINNHUB_API_KEY": "Finnhub 实时行情/新闻",
    "ALPHA_VANTAGE_API_KEY": "Alpha Vantage 行情/舆情分数",
    "TAVILY_API_KEY": "Tavily 深度搜索",
    "FMP_API_KEY": "FMP 财务数据",
    "FRED_API_KEY": "FRED 宏观数据",
    "EODHD_API_KEY": "EODHD 行情数据",
}


@dataclass
class StartupCheckResult:
    llm_available: bool
    llm_error: str | None = None
    missing_keys: list[str] = field(default_factory=list)
    configured_keys: list[str] = field(default_factory=list)
    # Stub/test profiles may intentionally run without a real provider. This
    # flag lets readiness distinguish an optional capability from a production
    # outage while preserving the detailed llm_available result.
    llm_required: bool = True
    profile: str = "development"


_startup_result: StartupCheckResult | None = None


def _reset_for_testing() -> None:
    global _startup_result
    _startup_result = None


def get_startup_result() -> StartupCheckResult | None:
    """返回最近一次启动检查结果（未检查过返回 None），供 health 接口等查询。"""
    return _startup_result


def is_llm_available() -> bool:
    """P1-3: chat_router 用于快速失败。未跑过检查时返回 True（不拦截）。"""
    if _startup_result is None:
        return True
    return _startup_result.llm_available


def _runtime_profile() -> str:
    configured = (
        str(os.getenv("FINSIGHT_RUNTIME_PROFILE") or "").strip().lower(),
        str(os.getenv("APP_MODE") or "").strip().lower(),
    )
    if any(value in {"prod", "production"} for value in configured):
        return "production"
    raw = configured[0] or configured[1] or "development"
    if raw in {"prod", "production"}:
        return "production"
    if raw in {"test", "testing", "ci"} or _env_truthy("FINSIGHT_TEST_PROFILE"):
        return "test"
    synth_mode = str(os.getenv("LANGGRAPH_SYNTHESIZE_MODE") or "").strip().lower()
    if synth_mode in {"stub", "dry_run", "off"} and not _env_truthy("LANGGRAPH_EXECUTE_LIVE_TOOLS"):
        return "stub"
    return raw or "development"


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def llm_required() -> bool:
    """Whether a real LLM endpoint is a hard runtime dependency."""
    if _runtime_profile() == "production":
        # Production is fail-closed. An environment override must never turn a
        # missing model into a healthy readiness result.
        return True
    explicit = os.getenv("FINSIGHT_LLM_REQUIRED")
    if explicit is not None:
        return _env_truthy("FINSIGHT_LLM_REQUIRED")
    # Production is the only implicit fail-closed profile. Local development,
    # CI and deterministic stub runs may intentionally exercise the graph
    # without provider credentials; callers still receive llm_available=False
    # for observability and can opt in to strict behavior explicitly.
    return _runtime_profile() == "production"


def _check_llm_endpoint() -> tuple[bool, str | None]:
    """P1-3: 验证至少有一个 LLM endpoint 可解析。"""
    try:
        from backend.llm_config import load_user_endpoints

        endpoints = load_user_endpoints()
        if endpoints:
            return True, None
        return False, "No LLM endpoint resolved"
    except ValueError as exc:
        return False, str(exc)
    except Exception as exc:  # 防御：配置解析崩溃也算不可用
        return False, f"LLM endpoint resolution failed: {exc}"


def _check_data_source_keys() -> tuple[list[str], list[str]]:
    """P1-1: 检查重要数据源 key 配置状态，返回 (已配置, 缺失)。"""
    missing: list[str] = []
    configured: list[str] = []
    for key in IMPORTANT_DATA_SOURCE_KEYS:
        value = os.getenv(key, "").strip().strip('"').strip()
        if value:
            configured.append(key)
        else:
            missing.append(key)
    return configured, missing


def run_startup_checks() -> StartupCheckResult:
    """启动时调用：校验 LLM endpoint + 数据源 key，输出显式告警日志。"""
    global _startup_result

    llm_available, llm_error = _check_llm_endpoint()
    configured, missing = _check_data_source_keys()
    required = llm_required()
    profile = _runtime_profile()

    if llm_available:
        logger.info("[StartupCheck] LLM endpoint: OK")
    elif not required:
        logger.warning(
            "[StartupCheck] LLM endpoint 未配置，但 profile=%s 允许无模型运行（仅确定性/stub 路径）",
            profile,
        )
    else:
        logger.error(
            "[StartupCheck] LLM endpoint 不可用: %s — Chat/报告请求将快速失败(503)而非等待超时",
            llm_error,
        )

    if configured:
        logger.info(
            "[StartupCheck] 已配置数据源 (%d/%d): %s",
            len(configured),
            len(IMPORTANT_DATA_SOURCE_KEYS),
            ", ".join(sorted(configured)),
        )
    for key in missing:
        logger.warning(
            "[StartupCheck] 缺少 %s（%s）— 对应数据源将降级或不可用",
            key,
            IMPORTANT_DATA_SOURCE_KEYS[key],
        )

    _startup_result = StartupCheckResult(
        llm_available=llm_available,
        llm_error=llm_error,
        missing_keys=missing,
        configured_keys=configured,
        llm_required=required,
        profile=profile,
    )
    return _startup_result
