# -*- coding: utf-8 -*-
"""
工作台 Phase 2：L2 agent 深析编排测试。

覆盖：
- run_l2_analysis 路由（price_move→TechnicalAgent / concentration→RiskAgent）
- agent 调用失败时返回 None 不抛异常
- L2Budget：每日上限 / 超限拒绝 / 跨日重置
- l2_enabled：MONITOR_L2_ENABLED / REPORTS_GENERATION_ENABLED / DAILY_LIMIT=0 联动
- L1 扫描串联 L2：mock run_l2_analysis 验证 agent_analysis 写入 store

策略：mock agent 类（_build_agent）避免真实 LLM/网络调用。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services import monitor_engine, monitor_l2
from backend.services.monitor_store import MonitorStore


# ── 测试替身 ──────────────────────────────────────────────────


class _FakeAgentOutput:
    """模拟 AgentOutput 的最小子集。"""

    def __init__(self, summary: str, confidence, data_sources):
        self.summary = summary
        self.confidence = confidence
        self.data_sources = data_sources


class _FakeAgent:
    """记录 research() 入参的假 agent。"""

    def __init__(self, output=None, raises: bool = False):
        self._output = output
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    async def research(self, query: str, ticker: str):
        self.calls.append((query, ticker))
        if self._raises:
            raise RuntimeError("agent boom")
        return self._output


def _run(coro):
    return asyncio.run(coro)


def _price_move_finding() -> dict:
    return {
        "id": "f-price",
        "session_id": "sess-a",
        "target": "TSLA",
        "trigger_type": "price_move",
        "trigger_detail": {"change_pct": -6.0, "threshold": 5.0},
    }


def _concentration_finding() -> dict:
    return {
        "id": "f-conc",
        "session_id": "sess-a",
        "target": "PORTFOLIO",
        "trigger_type": "concentration",
        "trigger_detail": {"top_ticker": "NVDA", "concentration_pct": 90.0},
    }


# ── 路由 ──────────────────────────────────────────────────────


def test_route_price_move_uses_technical_agent(monkeypatch):
    captured = {}

    def fake_build(kind: str):
        captured["kind"] = kind
        return _FakeAgent(_FakeAgentOutput("技术面分析", 0.85, ["kline"]))

    monkeypatch.setattr(monitor_l2, "_build_agent", fake_build)

    result = _run(monitor_l2.run_l2_analysis(_price_move_finding()))
    assert captured["kind"] == "technical"
    assert result is not None
    assert result["agent"] == "technical_agent"
    assert result["summary"] == "技术面分析"
    assert result["confidence"] == 0.85
    assert result["data_sources"] == ["kline"]
    assert "analyzed_at" in result


def test_route_concentration_uses_risk_agent(monkeypatch):
    captured = {}
    agent = _FakeAgent(_FakeAgentOutput("风险评估", 0.75, ["risk_rule_engine"]))

    def fake_build(kind: str):
        captured["kind"] = kind
        return agent

    monkeypatch.setattr(monitor_l2, "_build_agent", fake_build)

    result = _run(monitor_l2.run_l2_analysis(_concentration_finding()))
    assert captured["kind"] == "risk"
    assert result is not None
    assert result["agent"] == "risk_agent"
    # query 固定，ticker 取触发的最大持仓
    assert agent.calls == [("持仓集中度风险评估", "NVDA")]


def test_route_sentiment_shift_uses_news_agent(monkeypatch):
    captured = {}
    agent = _FakeAgent(_FakeAgentOutput("舆情分析", 0.7, ["alpha_vantage"]))

    def fake_build(kind: str):
        captured["kind"] = kind
        return agent

    monkeypatch.setattr(monitor_l2, "_build_agent", fake_build)

    finding = {
        "id": "f-sent", "session_id": "sess-a", "target": "AAPL",
        "trigger_type": "sentiment_shift", "trigger_detail": {"score": -0.5},
    }
    result = _run(monitor_l2.run_l2_analysis(finding))
    assert captured["kind"] == "news"
    assert result is not None
    assert result["agent"] == "news_agent"
    assert agent.calls == [("AAPL 舆情分析", "AAPL")]


def test_route_earnings_near_uses_deep_search_agent(monkeypatch):
    captured = {}
    agent = _FakeAgent(_FakeAgentOutput("财报前瞻", 0.6, ["sec_filings"]))

    def fake_build(kind: str):
        captured["kind"] = kind
        return agent

    monkeypatch.setattr(monitor_l2, "_build_agent", fake_build)

    finding = {
        "id": "f-earn", "session_id": "sess-a", "target": "AAPL",
        "trigger_type": "earnings_near", "trigger_detail": {"earnings_date": "2026-06-05"},
    }
    result = _run(monitor_l2.run_l2_analysis(finding))
    assert captured["kind"] == "deep_search"
    assert result is not None
    assert result["agent"] == "deep_search_agent"
    assert agent.calls == [("AAPL 财报前瞻分析", "AAPL")]


def test_route_macro_event_uses_macro_agent(monkeypatch):
    captured = {}
    agent = _FakeAgent(_FakeAgentOutput("宏观影响", 0.65, ["macro_calendar"]))

    def fake_build(kind: str):
        captured["kind"] = kind
        return agent

    monkeypatch.setattr(monitor_l2, "_build_agent", fake_build)

    finding = {
        "id": "f-macro", "session_id": "sess-a", "target": "MACRO",
        "trigger_type": "macro_event", "trigger_detail": {"events": [{"date": "2026-06-04", "title": "CPI"}]},
    }
    result = _run(monitor_l2.run_l2_analysis(finding))
    assert captured["kind"] == "macro"
    assert result is not None
    assert result["agent"] == "macro_agent"
    # ticker 回退 SPY（detail 不带 ticker）
    assert agent.calls == [("近期宏观事件对市场的影响分析", "SPY")]


def test_unsupported_trigger_returns_none(monkeypatch):
    # 不应实例化任何 agent
    monkeypatch.setattr(
        monitor_l2, "_build_agent", lambda kind: pytest.fail("should not build agent")
    )
    finding = {"id": "f-x", "session_id": "s", "target": "X", "trigger_type": "unknown_kind", "trigger_detail": {}}
    assert _run(monitor_l2.run_l2_analysis(finding)) is None


def test_concentration_without_top_ticker_returns_none(monkeypatch):
    monkeypatch.setattr(
        monitor_l2, "_build_agent", lambda kind: pytest.fail("should not build agent")
    )
    finding = {
        "id": "f-conc2",
        "session_id": "s",
        "target": "PORTFOLIO",
        "trigger_type": "concentration",
        "trigger_detail": {},  # 缺 top_ticker
    }
    assert _run(monitor_l2.run_l2_analysis(finding)) is None


# ── 失败处理 ──────────────────────────────────────────────────


def test_agent_research_raises_returns_none(monkeypatch):
    monkeypatch.setattr(
        monitor_l2, "_build_agent", lambda kind: _FakeAgent(raises=True)
    )
    # 不抛异常，返回 None
    assert _run(monitor_l2.run_l2_analysis(_price_move_finding())) is None


def test_agent_build_returns_none_skips(monkeypatch):
    monkeypatch.setattr(monitor_l2, "_build_agent", lambda kind: None)
    assert _run(monitor_l2.run_l2_analysis(_price_move_finding())) is None


def test_confidence_none_passthrough(monkeypatch):
    """诚实原则：agent confidence 为 None 时原样透传，不编造数值。"""
    monkeypatch.setattr(
        monitor_l2,
        "_build_agent",
        lambda kind: _FakeAgent(_FakeAgentOutput("无置信度分析", None, ["src"])),
    )
    result = _run(monitor_l2.run_l2_analysis(_price_move_finding()))
    assert result is not None
    assert result["confidence"] is None


# ── 预算护栏 ──────────────────────────────────────────────────


def test_budget_daily_limit_enforced(monkeypatch):
    monkeypatch.setenv("MONITOR_L2_DAILY_LIMIT", "2")
    budget = monitor_l2.L2Budget()
    assert budget.remaining() == 2
    assert budget.can_spend() is True
    budget.record_spend()
    assert budget.remaining() == 1
    assert budget.can_spend() is True
    budget.record_spend()
    # 用尽
    assert budget.remaining() == 0
    assert budget.can_spend() is False


def test_budget_zero_limit_disables(monkeypatch):
    monkeypatch.setenv("MONITOR_L2_DAILY_LIMIT", "0")
    budget = monitor_l2.L2Budget()
    assert budget.can_spend() is False
    assert budget.remaining() == 0


def test_budget_rollover_resets_count(monkeypatch):
    """跨日重置：模拟日期变化后计数清零。"""
    import datetime as _dt

    monkeypatch.setenv("MONITOR_L2_DAILY_LIMIT", "1")
    budget = monitor_l2.L2Budget()
    budget.record_spend()
    assert budget.can_spend() is False

    # 把内部日期回拨一天 -> 触发 roll over
    budget._date = budget._date - _dt.timedelta(days=1)
    assert budget.can_spend() is True
    assert budget.remaining() == 1


# ── 总开关 ────────────────────────────────────────────────────


def test_l2_enabled_default_true(monkeypatch):
    monkeypatch.delenv("MONITOR_L2_ENABLED", raising=False)
    monkeypatch.delenv("REPORTS_GENERATION_ENABLED", raising=False)
    monkeypatch.delenv("MONITOR_L2_DAILY_LIMIT", raising=False)
    assert monitor_l2.l2_enabled() is True


def test_l2_disabled_by_flag(monkeypatch):
    monkeypatch.setenv("MONITOR_L2_ENABLED", "false")
    assert monitor_l2.l2_enabled() is False


def test_l2_disabled_by_circuit_breaker(monkeypatch):
    """REPORTS_GENERATION_ENABLED=false 时 L2 全部暂停（P0-8 联动）。"""
    monkeypatch.setenv("MONITOR_L2_ENABLED", "true")
    monkeypatch.setenv("REPORTS_GENERATION_ENABLED", "false")
    assert monitor_l2.l2_enabled() is False


def test_l2_disabled_by_zero_daily_limit(monkeypatch):
    monkeypatch.setenv("MONITOR_L2_ENABLED", "true")
    monkeypatch.delenv("REPORTS_GENERATION_ENABLED", raising=False)
    monkeypatch.setenv("MONITOR_L2_DAILY_LIMIT", "0")
    assert monitor_l2.l2_enabled() is False


# ── L1→L2 串联 ────────────────────────────────────────────────


def test_l1_scan_chains_l2_and_persists(tmp_path, monkeypatch):
    """mock run_l2_analysis，验证 L1 扫描后 agent_analysis 写入 store + 返回值。"""
    from backend.services.alert_scheduler import PriceSnapshot

    store = MonitorStore(db_path=str(tmp_path / "l2_chain_test.db"))
    monkeypatch.setattr(monitor_engine, "get_monitor_store", lambda: store)
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "TSLA", "shares": 10, "avg_cost": 200.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=180.0, change_percent=-6.0),
    )

    # 强制 L2 启用 + 充足预算
    monkeypatch.setenv("MONITOR_L2_ENABLED", "true")
    monkeypatch.delenv("REPORTS_GENERATION_ENABLED", raising=False)
    monkeypatch.setenv("MONITOR_L2_DAILY_LIMIT", "20")
    # 重置进程级预算单例，避免被其他测试污染
    monitor_l2._BUDGET = None

    fake_analysis = {
        "agent": "technical_agent",
        "summary": "深析结果",
        "confidence": 0.8,
        "data_sources": ["kline"],
        "analyzed_at": "2026-06-03T00:00:00+00:00",
    }

    async def fake_run_l2(finding):
        return fake_analysis if finding["trigger_type"] == "price_move" else None

    monkeypatch.setattr(monitor_engine, "run_l2_analysis", fake_run_l2)

    findings = _run(monitor_engine.run_l1_scan("sess-a"))
    moves = [f for f in findings if f["trigger_type"] == "price_move"]
    assert len(moves) == 1
    # 返回值里带上 agent_analysis
    assert moves[0]["agent_analysis"] == fake_analysis
    # 已落库
    persisted = [f for f in store.list_findings("sess-a") if f["trigger_type"] == "price_move"]
    assert persisted[0]["agent_analysis"] == fake_analysis


def test_l1_scan_skips_l2_when_disabled(tmp_path, monkeypatch):
    """L2 禁用时不调用 run_l2_analysis，agent_analysis 保持 None（Phase 1 行为）。"""
    from backend.services.alert_scheduler import PriceSnapshot

    store = MonitorStore(db_path=str(tmp_path / "l2_off_test.db"))
    monkeypatch.setattr(monitor_engine, "get_monitor_store", lambda: store)
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "TSLA", "shares": 10, "avg_cost": 200.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=180.0, change_percent=-6.0),
    )
    monkeypatch.setenv("MONITOR_L2_ENABLED", "false")

    def boom(finding):
        raise AssertionError("run_l2_analysis should not be called when L2 disabled")

    monkeypatch.setattr(monitor_engine, "run_l2_analysis", boom)

    findings = _run(monitor_engine.run_l1_scan("sess-a"))
    moves = [f for f in findings if f["trigger_type"] == "price_move"]
    assert len(moves) == 1
    assert moves[0]["agent_analysis"] is None
