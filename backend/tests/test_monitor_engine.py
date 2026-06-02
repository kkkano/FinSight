# -*- coding: utf-8 -*-
"""
工作台 Phase 1：L1 规则扫描引擎测试。

策略：
- mock 价格快照 fetch_price_snapshot（monitor_engine 模块内引用）
- mock 持仓读取 get_positions
- 注入临时 MonitorStore（通过 monitor_engine 的全局单例 getter）
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services import monitor_engine
from backend.services.alert_scheduler import PriceSnapshot
from backend.services.monitor_store import MonitorStore


@pytest.fixture()
def patched_env(tmp_path, monkeypatch):
    """注入临时 store + 默认的空持仓/价格 mock，返回 store 供断言。"""
    # Phase 1 测试：关闭 L2，避免触发 agent/LLM 调用（L2 串联另有专门测试覆盖）
    monkeypatch.setenv("MONITOR_L2_ENABLED", "false")

    store = MonitorStore(db_path=str(tmp_path / "monitor_engine_test.db"))
    monkeypatch.setattr(monitor_engine, "get_monitor_store", lambda: store)

    # 默认：无持仓
    monkeypatch.setattr(monitor_engine, "get_positions", lambda sid: [])
    # 默认：价格无异动
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=100.0, change_percent=0.5),
    )
    return store


def _run(session_id: str) -> list[dict]:
    return asyncio.run(monitor_engine.run_l1_scan(session_id))


def _price_moves(findings: list[dict]) -> list[dict]:
    """仅取价格异动类 finding（单一持仓会同时触发集中度，需按类型隔离断言）。"""
    return [f for f in findings if f["trigger_type"] == "price_move"]


# ── 空 session ────────────────────────────────────────────────


def test_empty_session_returns_empty(patched_env):
    findings = _run("sess-empty")
    assert findings == []


# ── 价格异动 ──────────────────────────────────────────────────


def test_price_move_triggers_finding(patched_env, monkeypatch):
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "TSLA", "shares": 10, "avg_cost": 200.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=180.0, change_percent=-6.0),
    )

    findings = _run("sess-a")
    moves = _price_moves(findings)
    assert len(moves) == 1
    f = moves[0]
    assert f["target"] == "TSLA"
    assert f["trigger_detail"]["change_pct"] == -6.0
    # actions 至少包含全面体检
    assert any(a["type"] == "full_report" for a in f["actions"])
    # 已落库（含可能伴随的集中度告警）
    assert len(_price_moves(patched_env.list_findings("sess-a"))) == 1


def test_price_move_within_threshold_no_finding(patched_env, monkeypatch):
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=151.0, change_percent=2.0),
    )

    findings = _run("sess-a")
    assert _price_moves(findings) == []


def test_price_move_custom_threshold_from_target(patched_env, monkeypatch):
    """target.config.price_move_pct 覆盖默认阈值：阈值 10 时 -6% 不触发。"""
    import uuid
    from datetime import datetime, timezone

    patched_env.upsert_target(
        {
            "id": uuid.uuid4().hex,
            "session_id": "sess-a",
            "type": "holding",
            "ticker": "TSLA",
            "config": {"price_move_pct": 10.0},
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "TSLA", "shares": 10, "avg_cost": 200.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=188.0, change_percent=-6.0),
    )

    findings = _run("sess-a")
    assert _price_moves(findings) == []


def test_price_move_dedup_within_window(patched_env, monkeypatch):
    """同 target 4h 内第二次扫描不产生新 finding。"""
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "TSLA", "shares": 10, "avg_cost": 200.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=180.0, change_percent=-6.0),
    )

    first = _run("sess-a")
    assert len(_price_moves(first)) == 1
    second = _run("sess-a")
    # 4h 窗口内同 target 同类型不再重复产出
    assert _price_moves(second) == []
    # 落库的 price_move 仍为 1 条
    assert len(_price_moves(patched_env.list_findings("sess-a"))) == 1


def test_watchlist_target_triggers_even_without_holding(patched_env, monkeypatch):
    """非持仓的 watchlist target 也应被价格异动规则覆盖。"""
    import uuid
    from datetime import datetime, timezone

    patched_env.upsert_target(
        {
            "id": uuid.uuid4().hex,
            "session_id": "sess-a",
            "type": "watchlist",
            "ticker": "NVDA",
            "config": {},
            "enabled": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    monkeypatch.setattr(monitor_engine, "get_positions", lambda sid: [])
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=500.0, change_percent=-7.0),
    )

    findings = _run("sess-a")
    assert len(findings) == 1
    assert findings[0]["target"] == "NVDA"


# ── 集中度 ────────────────────────────────────────────────────


def test_concentration_triggers_finding(patched_env, monkeypatch):
    """单一持仓市值占比 > 80% 触发集中度 finding。"""
    # TSLA 占比 ~90%
    monkeypatch.setattr(
        monitor_engine,
        "get_positions",
        lambda sid: [
            {"ticker": "TSLA", "shares": 90, "avg_cost": 100.0},
            {"ticker": "AAPL", "shares": 10, "avg_cost": 100.0},
        ],
    )
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=100.0, change_percent=0.0),
    )

    findings = _run("sess-a")
    conc = [f for f in findings if f["trigger_type"] == "concentration"]
    assert len(conc) == 1
    assert conc[0]["target"] == "PORTFOLIO"
    assert conc[0]["trigger_detail"]["concentration_pct"] >= 80.0
    assert any(a["type"] == "rebalance" for a in conc[0]["actions"])


def test_concentration_below_threshold_no_finding(patched_env, monkeypatch):
    monkeypatch.setattr(
        monitor_engine,
        "get_positions",
        lambda sid: [
            {"ticker": "TSLA", "shares": 50, "avg_cost": 100.0},
            {"ticker": "AAPL", "shares": 50, "avg_cost": 100.0},
        ],
    )
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=100.0, change_percent=0.0),
    )

    findings = _run("sess-a")
    assert [f for f in findings if f["trigger_type"] == "concentration"] == []


# ── 调度入口 ──────────────────────────────────────────────────


def test_run_monitor_scan_cycle_smoke(patched_env, monkeypatch):
    """调度入口能跑通（无 session 时安全返回）。"""
    monkeypatch.setattr(monitor_engine, "list_session_ids", lambda: [])
    # 不应抛异常
    monitor_engine.run_monitor_scan_cycle()
