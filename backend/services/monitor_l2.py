# -*- coding: utf-8 -*-
"""
工作台 Phase 2：L2 agent 自动深析编排（有成本护栏）。

L1 规则引擎（monitor_engine）产出 Finding 后，对部分类型调用专家 agent 做深度分析，
把分析结果写回 Finding.agent_analysis。L2 有成本（要调 LLM/数据源），因此带三道护栏：

  1. 总开关 MONITOR_L2_ENABLED（默认 true）
  2. 熔断联动 REPORTS_GENERATION_ENABLED（P0-8，false 时 L2 全停）
  3. 单日预算 MONITOR_L2_DAILY_LIMIT（默认 20，0=禁用）

路由规则：
  - price_move    → TechnicalAgent（价格异动技术面）
  - concentration → RiskAgent（最大持仓的集中度风险）
  - 其他          → 不分析（返回 None）

诚实原则：agent 调用失败 / 无置信度时如实标注，禁止编造 confidence。

agent 调用严格遵循 agent_adapter 的标准模式（直接实例化 + research()），
不发明新的调用方式。
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ── 环境开关读取 ──────────────────────────────────────────────


def _env_truthy(name: str, default: str) -> bool:
    """统一布尔解析：false/0/off/no 视为关闭，其余为开。"""
    return str(os.getenv(name, default)).strip().lower() not in {"false", "0", "off", "no"}


def _reports_generation_enabled() -> bool:
    """P0-8 熔断联动：与 chat_router 同一开关，false 时 L2 暂停。"""
    return _env_truthy("REPORTS_GENERATION_ENABLED", "true")


def _daily_limit() -> int:
    """L2 单日自动调用上限；0 表示禁用 L2。非法值回退默认 20。"""
    raw = os.getenv("MONITOR_L2_DAILY_LIMIT", "20")
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return 20


# ── 成本护栏 ──────────────────────────────────────────────────


class L2Budget:
    """L2 单日调用预算（内存计数，按日期重置）。

    计数存内存：进程重启后清零会放宽限制，但单日上限本是防滥用兜底，可接受
    （保守方向是多限制而非少限制）。每次 can_spend / record_spend 都先检查跨日重置。
    """

    def __init__(self) -> None:
        self._date: date = datetime.now(timezone.utc).date()
        self._count: int = 0

    def _roll_over_if_needed(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._date:
            self._date = today
            self._count = 0

    def can_spend(self) -> bool:
        """当日是否还有预算（limit=0 时恒 False，等于禁用 L2）。"""
        self._roll_over_if_needed()
        limit = _daily_limit()
        if limit <= 0:
            return False
        return self._count < limit

    def record_spend(self) -> None:
        """记一次 L2 调用消耗。"""
        self._roll_over_if_needed()
        self._count += 1

    def remaining(self) -> int:
        """当日剩余预算（不小于 0）。"""
        self._roll_over_if_needed()
        return max(0, _daily_limit() - self._count)


# 进程级单例预算（monitor_engine 串联时复用）
_BUDGET: L2Budget | None = None


def get_l2_budget() -> L2Budget:
    """返回进程级 L2 预算单例。"""
    global _BUDGET
    if _BUDGET is None:
        _BUDGET = L2Budget()
    return _BUDGET


def l2_enabled() -> bool:
    """L2 总开关：MONITOR_L2_ENABLED + 熔断联动 + 预算非零。

    注意：这里只判断「L2 是否可用」（开关层面），单次是否还有预算由 budget.can_spend() 决定。
    """
    if not _env_truthy("MONITOR_L2_ENABLED", "true"):
        return False
    if not _reports_generation_enabled():
        return False
    if _daily_limit() <= 0:
        return False
    return True


# ── L2 深析编排 ───────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_agent(agent_kind: str):
    """按标准模式实例化 agent（technical / risk）。

    LLM 不可用时回退 llm=None（agent 内部以确定性逻辑兜底），不阻断 L2。
    实例化彻底失败时返回 None，由上层跳过该 Finding。
    """
    try:
        from backend.orchestration.cache import DataCache
        import backend.tools as tools_module
        from backend.agents.technical_agent import TechnicalAgent
        from backend.agents.risk_agent import RiskAgent
    except Exception:  # noqa: BLE001 - 依赖导入失败时 L2 整体跳过
        logger.warning("[MonitorL2] failed to import agent dependencies", exc_info=True)
        return None

    llm = None
    try:
        from backend.llm_config import create_llm

        llm = create_llm(temperature=0.2)
    except Exception:  # noqa: BLE001 - LLM 不可用时 agent 走确定性兜底
        logger.info("[MonitorL2] create_llm unavailable, agent runs in deterministic mode")
        llm = None

    cache = DataCache()
    if agent_kind == "technical":
        return TechnicalAgent(llm, cache, tools_module)
    if agent_kind == "risk":
        return RiskAgent(llm, cache, tools_module)
    return None


def _route(finding: dict) -> tuple[str, str, str, str] | None:
    """根据 trigger_type 决定路由。

    返回 (agent_kind, agent_name, query, ticker)；不支持的类型返回 None。
    """
    trigger_type = str(finding.get("trigger_type") or "")
    detail = finding.get("trigger_detail") or {}

    if trigger_type == "price_move":
        ticker = str(finding.get("target") or "").strip().upper()
        if not ticker:
            return None
        return ("technical", "technical_agent", f"{ticker} 价格异动技术面分析", ticker)

    if trigger_type == "concentration":
        # 集中度对触发的最大持仓 ticker 做风险评估
        ticker = str(detail.get("top_ticker") or "").strip().upper()
        if not ticker:
            return None
        return ("risk", "risk_agent", "持仓集中度风险评估", ticker)

    return None


async def run_l2_analysis(finding: dict) -> dict | None:
    """对一条 L1 Finding 做 L2 agent 深度分析。

    路由：price_move → TechnicalAgent；concentration → RiskAgent；其余 → None。
    失败处理：agent 调用异常 → logger.warning + 返回 None（不影响 Finding 本身）。

    返回 agent_analysis dict（诚实原则：confidence 可能为 None，原样透传不编造）。
    """
    route = _route(finding)
    if route is None:
        return None
    agent_kind, agent_name, query, ticker = route

    try:
        agent = _build_agent(agent_kind)
        if agent is None:
            logger.warning("[MonitorL2] agent unavailable for kind=%s", agent_kind)
            return None

        result = await agent.research(query, ticker)
        if result is None:
            logger.warning("[MonitorL2] agent %s returned empty result for %s", agent_name, ticker)
            return None

        # confidence 原样透传：诚实原则，agent 没给就保持 None，不补默认值
        confidence = getattr(result, "confidence", None)
        data_sources = getattr(result, "data_sources", None) or []
        summary = getattr(result, "summary", "") or ""

        return {
            "agent": agent_name,
            "summary": summary,
            "confidence": confidence,
            "data_sources": list(data_sources),
            "analyzed_at": _now_iso(),
        }
    except Exception as exc:  # noqa: BLE001 - L2 失败不影响 Finding
        logger.warning(
            "[MonitorL2] L2 analysis failed for finding=%s (%s): %s",
            finding.get("id"),
            agent_name,
            exc,
        )
        return None


__all__ = [
    "L2Budget",
    "get_l2_budget",
    "l2_enabled",
    "run_l2_analysis",
]
