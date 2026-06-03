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
from backend.services.session_price import SessionPriceSnapshot


def _session_snap_from_regular(ticker: str, session: str):
    """把 monitor_engine.fetch_price_snapshot 的 mock 结果适配成时段感知快照。

    测试只需 mock fetch_price_snapshot（常规价），价格规则用的
    fetch_session_aware_price_snapshot 会经此委托复用同一份 mock 数据。
    """
    snap = monitor_engine.fetch_price_snapshot(ticker)
    if snap is None:
        return None
    return SessionPriceSnapshot(
        ticker=ticker,
        price=snap.price,
        change_percent=snap.change_percent,
        market_session=session,
        price_basis="regular" if session == "regular" else "regular_fallback",
    )


@pytest.fixture()
def patched_env(tmp_path, monkeypatch):
    """注入临时 store + 默认的空持仓/价格 mock，返回 store 供断言。"""
    # Phase 1 测试：关闭 L2，避免触发 agent/LLM 调用（L2 串联另有专门测试覆盖）
    monkeypatch.setenv("MONITOR_L2_ENABLED", "false")

    store = MonitorStore(db_path=str(tmp_path / "monitor_engine_test.db"))
    monkeypatch.setattr(monitor_engine, "get_monitor_store", lambda: store)

    # 默认时段：盘中（避免落到 closed 跳过价格规则导致现有用例失真）
    monkeypatch.setattr(monitor_engine, "get_market_session", lambda *a, **k: "regular")

    # 默认：无持仓
    monkeypatch.setattr(monitor_engine, "get_positions", lambda sid: [])
    # 默认：价格无异动（常规价）
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=100.0, change_percent=0.5),
    )
    # 价格异动规则用时段感知价格：委托复用上面的 fetch_price_snapshot mock
    monkeypatch.setattr(
        monitor_engine, "fetch_session_aware_price_snapshot", _session_snap_from_regular
    )
    # 默认：舆情/日历数据源返回「无数据」，避免现有测试触发真实外部 API
    monkeypatch.setattr(
        monitor_engine,
        "get_news_sentiment_score",
        lambda ticker, limit=10: {"ticker": ticker, "score": None, "label": None, "article_count": 0, "error": "no data found."},
    )
    monkeypatch.setattr(
        monitor_engine,
        "get_event_calendar",
        lambda ticker, days_ahead=7: {"ticker": ticker, "earnings_events": [], "dividend_events": [], "macro_events": [], "error": "no_calendar_events"},
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


# ── 舆情突变 ──────────────────────────────────────────────────


def _trigger_type(findings: list[dict], trigger_type: str) -> list[dict]:
    return [f for f in findings if f["trigger_type"] == trigger_type]


def test_sentiment_shift_triggers_on_strong_negative(patched_env, monkeypatch):
    """平均分 -0.5（绝对值 > 0.35 阈值）触发 sentiment_shift。"""
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "get_news_sentiment_score",
        lambda ticker, limit=10: {
            "ticker": ticker, "score": -0.5, "label": "Bearish", "article_count": 8, "error": None,
        },
    )

    findings = _run("sess-a")
    sent = _trigger_type(findings, "sentiment_shift")
    assert len(sent) == 1
    f = sent[0]
    assert f["target"] == "AAPL"
    assert f["trigger_detail"]["score"] == -0.5
    assert "强负面" in f["title"]
    assert any(a["type"] == "full_report" for a in f["actions"])


def test_sentiment_shift_within_threshold_no_finding(patched_env, monkeypatch):
    """平均分 0.1（绝对值 < 0.35）不触发。"""
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "get_news_sentiment_score",
        lambda ticker, limit=10: {
            "ticker": ticker, "score": 0.1, "label": "Neutral", "article_count": 6, "error": None,
        },
    )
    assert _trigger_type(_run("sess-a"), "sentiment_shift") == []


def test_sentiment_shift_none_score_no_finding(patched_env, monkeypatch):
    """score 为 None（数据不可用）→ 跳过不触发（诚实原则）。"""
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "get_news_sentiment_score",
        lambda ticker, limit=10: {
            "ticker": ticker, "score": None, "label": None, "article_count": 0, "error": "rate limited",
        },
    )
    assert _trigger_type(_run("sess-a"), "sentiment_shift") == []


def test_sentiment_rule_disabled_by_env(patched_env, monkeypatch):
    """MONITOR_SENTIMENT_RULE_ENABLED=false 时舆情规则整条跳过，不调数据源。"""
    monkeypatch.setenv("MONITOR_SENTIMENT_RULE_ENABLED", "false")
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )

    def boom(ticker, limit=10):
        raise AssertionError("get_news_sentiment_score should not be called when rule disabled")

    monkeypatch.setattr(monitor_engine, "get_news_sentiment_score", boom)
    assert _trigger_type(_run("sess-a"), "sentiment_shift") == []


# ── 财报临近 ──────────────────────────────────────────────────


def _earnings_calendar(days_from_now: int):
    """构造一个 earnings_events 含 N 天后财报日的 calendar 返回。"""
    from datetime import datetime, timedelta, timezone

    earnings_date = (datetime.now(timezone.utc).date() + timedelta(days=days_from_now)).isoformat()

    def _cal(ticker, days_ahead=7):
        return {
            "ticker": ticker,
            "earnings_events": [{"date": earnings_date, "title": "Earnings Date", "source": "yfinance_earnings_dates"}],
            "dividend_events": [],
            "macro_events": [],
            "error": None,
        }

    return _cal


def test_earnings_near_triggers_within_window(patched_env, monkeypatch):
    """财报 2 天后（<= 3 天窗口）触发 earnings_near。"""
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )
    monkeypatch.setattr(monitor_engine, "get_event_calendar", _earnings_calendar(2))

    findings = _run("sess-a")
    earn = _trigger_type(findings, "earnings_near")
    assert len(earn) == 1
    assert earn[0]["target"] == "AAPL"
    assert earn[0]["trigger_detail"]["days_until"] == 2


def test_earnings_near_outside_window_no_finding(patched_env, monkeypatch):
    """财报 5 天后（> 3 天窗口）不触发。"""
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )
    monkeypatch.setattr(monitor_engine, "get_event_calendar", _earnings_calendar(5))
    assert _trigger_type(_run("sess-a"), "earnings_near") == []


# ── 宏观事件 ──────────────────────────────────────────────────


def _macro_calendar(macro_events):
    def _cal(ticker, days_ahead=7):
        return {
            "ticker": ticker,
            "earnings_events": [],
            "dividend_events": [],
            "macro_events": macro_events,
            "error": None,
        }

    return _cal


def test_macro_event_triggers_within_window(patched_env, monkeypatch):
    """宏观事件 1 天后（<= 2 天）触发 macro_event（target=MACRO，单条聚合）。"""
    from datetime import datetime, timedelta, timezone

    event_date = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "get_event_calendar",
        _macro_calendar([{"date": event_date, "title": "CPI release", "source": "search_macro_calendar"}]),
    )

    findings = _run("sess-a")
    macro = _trigger_type(findings, "macro_event")
    assert len(macro) == 1
    assert macro[0]["target"] == "MACRO"
    assert macro[0]["trigger_detail"]["events"][0]["title"] == "CPI release"


def test_macro_event_placeholder_date_none_filtered(patched_env, monkeypatch):
    """date=None 的 macro_watchlist 占位符被过滤，不触发。"""
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "get_event_calendar",
        _macro_calendar([{"date": None, "title": "Monitor upcoming CPI release window", "source": "macro_watchlist"}]),
    )
    assert _trigger_type(_run("sess-a"), "macro_event") == []


# ── 交易时段感知调度 ──────────────────────────────────────────


def test_closed_session_skips_price_rule(patched_env, monkeypatch):
    """闭市时段：价格异动规则不执行（价格函数不应被调用），价格 finding 为空。"""
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "TSLA", "shares": 10, "avg_cost": 200.0}]
    )

    def boom(ticker, session):
        raise AssertionError("price fetch should not be called when market is closed")

    monkeypatch.setattr(monitor_engine, "fetch_session_aware_price_snapshot", boom)

    # 直接传 closed 时段
    findings = asyncio.run(monitor_engine.run_l1_scan("sess-a", market_session="closed"))
    assert _price_moves(findings) == []


def test_pre_market_price_move_title_and_detail(patched_env, monkeypatch):
    """盘前价格异动：title 含「盘前」，trigger_detail 含 market_session + price_basis。"""
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "NVDA", "shares": 10, "avg_cost": 100.0}]
    )

    def pre_snap(ticker, session):
        return SessionPriceSnapshot(
            ticker=ticker, price=120.0, change_percent=8.0,
            market_session="pre_market", price_basis="pre_market",
        )

    monkeypatch.setattr(monitor_engine, "fetch_session_aware_price_snapshot", pre_snap)

    findings = asyncio.run(monitor_engine.run_l1_scan("sess-a", market_session="pre_market"))
    moves = _price_moves(findings)
    assert len(moves) == 1
    f = moves[0]
    assert "盘前" in f["title"]
    assert f["trigger_detail"]["market_session"] == "pre_market"
    assert f["trigger_detail"]["price_basis"] == "pre_market"


def test_after_hours_price_move_title(patched_env, monkeypatch):
    """盘后价格异动：title 含「盘后」。"""
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 10, "avg_cost": 100.0}]
    )

    def post_snap(ticker, session):
        return SessionPriceSnapshot(
            ticker=ticker, price=80.0, change_percent=-9.0,
            market_session="after_hours", price_basis="post_market",
        )

    monkeypatch.setattr(monitor_engine, "fetch_session_aware_price_snapshot", post_snap)

    findings = asyncio.run(monitor_engine.run_l1_scan("sess-a", market_session="after_hours"))
    moves = _price_moves(findings)
    assert len(moves) == 1
    assert "盘后" in moves[0]["title"]


def test_regular_price_move_title_uses_single_day(patched_env, monkeypatch):
    """盘中价格异动：title 仍用「单日」（向后兼容文案）。"""
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "TSLA", "shares": 10, "avg_cost": 200.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=180.0, change_percent=-6.0),
    )

    findings = asyncio.run(monitor_engine.run_l1_scan("sess-a", market_session="regular"))
    moves = _price_moves(findings)
    assert len(moves) == 1
    assert "单日" in moves[0]["title"]
    assert moves[0]["trigger_detail"]["market_session"] == "regular"


# ── dispatcher 节流 ───────────────────────────────────────────


def test_dispatch_throttles_within_interval(monkeypatch):
    """距上次扫描不足时段间隔 → 本心跳跳过扫描。"""
    monkeypatch.setattr(monitor_engine, "get_market_session", lambda *a, **k: "regular")
    monkeypatch.setattr(monitor_engine, "get_scan_interval_minutes", lambda s: 15.0)

    called = {"n": 0}
    monkeypatch.setattr(
        monitor_engine, "run_monitor_scan_cycle", lambda market_session=None: called.__setitem__("n", called["n"] + 1)
    )

    # 模拟刚刚扫过（monotonic now）
    import time as _t
    monkeypatch.setattr(monitor_engine, "_last_scan_at", _t.monotonic())

    monitor_engine.run_monitor_dispatch_cycle()
    assert called["n"] == 0  # 间隔未到，跳过


def test_dispatch_scans_when_interval_elapsed(monkeypatch):
    """距上次扫描超过时段间隔 → 执行扫描并更新 _last_scan_at。"""
    monkeypatch.setattr(monitor_engine, "get_market_session", lambda *a, **k: "pre_market")
    monkeypatch.setattr(monitor_engine, "get_scan_interval_minutes", lambda s: 10.0)

    captured = {"session": None, "n": 0}

    def fake_cycle(market_session=None):
        captured["session"] = market_session
        captured["n"] += 1

    monkeypatch.setattr(monitor_engine, "run_monitor_scan_cycle", fake_cycle)

    # 上次扫描在 20 分钟前（超过 10 分钟间隔）
    import time as _t
    monkeypatch.setattr(monitor_engine, "_last_scan_at", _t.monotonic() - 20 * 60)

    monitor_engine.run_monitor_dispatch_cycle()
    assert captured["n"] == 1
    assert captured["session"] == "pre_market"  # 当前时段透传给扫描
    assert monitor_engine._last_scan_at is not None


def test_dispatch_first_run_scans(monkeypatch):
    """首次运行（_last_scan_at 为 None）→ 立即扫描。"""
    monkeypatch.setattr(monitor_engine, "get_market_session", lambda *a, **k: "regular")
    monkeypatch.setattr(monitor_engine, "get_scan_interval_minutes", lambda s: 15.0)
    monkeypatch.setattr(monitor_engine, "_last_scan_at", None)

    called = {"n": 0}
    monkeypatch.setattr(
        monitor_engine, "run_monitor_scan_cycle", lambda market_session=None: called.__setitem__("n", called["n"] + 1)
    )

    monitor_engine.run_monitor_dispatch_cycle()
    assert called["n"] == 1
