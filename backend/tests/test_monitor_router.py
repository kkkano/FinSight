# -*- coding: utf-8 -*-
"""
工作台 Phase 1：monitor_router API 冒烟测试。

用 TestClient 走真实路由；通过 MONITOR_DB_PATH 环境变量 + 单例重置把
SQLite 落到 tmp_path，避免污染 data/monitor.db。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import monitor_router as mr
from backend.api.main import app
from backend.services import monitor_engine
from backend.services import monitor_store as ms
from backend.services.alert_scheduler import PriceSnapshot


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 单例重置 + 路径重定向到 tmp
    monkeypatch.setenv("MONITOR_DB_PATH", str(tmp_path / "monitor_router_test.db"))
    # Phase 1 路由冒烟：关闭 L2，避免扫描串联 agent/LLM 调用
    monkeypatch.setenv("MONITOR_L2_ENABLED", "false")
    monkeypatch.setattr(ms, "_STORE", None, raising=False)
    with TestClient(app) as c:
        yield c
    monkeypatch.setattr(ms, "_STORE", None, raising=False)


SESSION = "sess-router"


# ── targets CRUD ──────────────────────────────────────────────


def test_target_crud_flow(client):
    # 创建
    resp = client.post(
        "/api/monitor/targets",
        json={
            "session_id": SESSION,
            "type": "holding",
            "ticker": "TSLA",
            "config": {"price_move_pct": 6.0},
            "enabled": True,
        },
    )
    assert resp.status_code == 200, resp.text
    target_id = resp.json()["target"]["id"]

    # 列表
    resp = client.get(f"/api/monitor/targets?session_id={SESSION}")
    assert resp.status_code == 200
    targets = resp.json()["targets"]
    assert len(targets) == 1
    assert targets[0]["ticker"] == "TSLA"

    # 更新
    resp = client.patch(
        f"/api/monitor/targets/{target_id}?session_id={SESSION}",
        json={"config": {"price_move_pct": 9.0}, "enabled": False},
    )
    assert resp.status_code == 200
    resp = client.get(f"/api/monitor/targets?session_id={SESSION}")
    t = resp.json()["targets"][0]
    assert t["config"]["price_move_pct"] == 9.0
    assert t["enabled"] is False

    # 删除
    resp = client.delete(f"/api/monitor/targets/{target_id}?session_id={SESSION}")
    assert resp.status_code == 200
    resp = client.get(f"/api/monitor/targets?session_id={SESSION}")
    assert resp.json()["targets"] == []


def test_delete_missing_target_404(client):
    resp = client.delete(f"/api/monitor/targets/does-not-exist?session_id={SESSION}")
    assert resp.status_code == 404


# ── findings 列表 + 状态 ──────────────────────────────────────


def test_findings_list_and_status_update(client, monkeypatch):
    # 通过 scan 产生一条 finding：mock 持仓 + 价格异动
    monkeypatch.setattr(
        monitor_engine, "get_positions", lambda sid: [{"ticker": "TSLA", "shares": 10, "avg_cost": 200.0}]
    )
    monkeypatch.setattr(
        monitor_engine,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=180.0, change_percent=-6.0),
    )

    resp = client.post(f"/api/monitor/scan?session_id={SESSION}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1
    finding_id = body["findings"][0]["id"]

    # 列表
    resp = client.get(f"/api/monitor/findings?session_id={SESSION}")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1

    # 状态更新
    resp = client.patch(
        f"/api/monitor/findings/{finding_id}?session_id={SESSION}",
        json={"status": "viewed"},
    )
    assert resp.status_code == 200

    # status 过滤
    resp = client.get(f"/api/monitor/findings?session_id={SESSION}&status=viewed")
    assert resp.status_code == 200
    rows = resp.json()["findings"]
    assert any(r["id"] == finding_id and r["status"] == "viewed" for r in rows)


def test_patch_missing_finding_404(client):
    resp = client.patch(
        f"/api/monitor/findings/nope?session_id={SESSION}",
        json={"status": "viewed"},
    )
    assert resp.status_code == 404


def test_scan_empty_session_returns_zero(client, monkeypatch):
    monkeypatch.setattr(monitor_engine, "get_positions", lambda sid: [])
    resp = client.post(f"/api/monitor/scan?session_id=sess-nobody")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_missing_session_id_rejected(client):
    # session_id 为必填 query；缺失应 422
    resp = client.get("/api/monitor/findings")
    assert resp.status_code == 422


# ── Phase 3：config 校验 ──────────────────────────────────────


def test_create_target_rejects_out_of_range_config(client):
    """price_move_pct 超范围（>100）→ 422。"""
    resp = client.post(
        "/api/monitor/targets",
        json={
            "session_id": SESSION,
            "type": "holding",
            "ticker": "TSLA",
            "config": {"price_move_pct": 999.0},
        },
    )
    assert resp.status_code == 422
    assert "price_move_pct" in resp.json()["detail"]


def test_create_target_rejects_unknown_config_key(client):
    """未知 config key → 422（防垃圾数据）。"""
    resp = client.post(
        "/api/monitor/targets",
        json={
            "session_id": SESSION,
            "type": "holding",
            "ticker": "TSLA",
            "config": {"bogus_key": 1},
        },
    )
    assert resp.status_code == 422
    assert "bogus_key" in resp.json()["detail"]


def test_create_target_accepts_valid_custom_days(client):
    """earnings_near_days / macro_event_days 在范围内 → 创建成功。"""
    resp = client.post(
        "/api/monitor/targets",
        json={
            "session_id": SESSION,
            "type": "holding",
            "ticker": "AAPL",
            "config": {"earnings_near_days": 7, "macro_event_days": 10},
        },
    )
    assert resp.status_code == 200, resp.text


def test_patch_target_rejects_out_of_range_config(client):
    """更新时超范围 config → 422。"""
    resp = client.post(
        "/api/monitor/targets",
        json={"session_id": SESSION, "type": "holding", "ticker": "NVDA", "config": {}},
    )
    target_id = resp.json()["target"]["id"]

    resp = client.patch(
        f"/api/monitor/targets/{target_id}?session_id={SESSION}",
        json={"config": {"earnings_near_days": 99}},
    )
    assert resp.status_code == 422
    assert "earnings_near_days" in resp.json()["detail"]


# ── Phase 3：宏观日历聚合端点 ─────────────────────────────────


@pytest.fixture()
def clear_macro_cache():
    """每个 macro-calendar 测试前后清缓存，避免互相污染。"""
    mr._MACRO_CACHE.clear()
    yield
    mr._MACRO_CACHE.clear()


def _calendar_with(earnings_days=None, macro_days=None):
    """构造 get_event_calendar mock：earnings/macro 各放一个 N 天后事件。"""
    from datetime import datetime, timedelta, timezone

    def _cal(ticker, days_ahead=7):
        earnings_events = []
        macro_events = []
        if earnings_days is not None:
            d = (datetime.now(timezone.utc).date() + timedelta(days=earnings_days)).isoformat()
            earnings_events.append({"date": d, "title": "Earnings Date", "source": "yfinance_earnings_dates"})
        if macro_days is not None:
            d = (datetime.now(timezone.utc).date() + timedelta(days=macro_days)).isoformat()
            macro_events.append({"date": d, "title": "FOMC 利率决议", "source": "search_macro_calendar"})
        # 始终带一个 date=None 占位符，验证被过滤
        macro_events.append({"date": None, "title": "placeholder", "source": "macro_watchlist"})
        return {
            "ticker": ticker,
            "earnings_events": earnings_events,
            "dividend_events": [],
            "macro_events": macro_events,
            "error": None,
        }

    return _cal


def test_macro_calendar_aggregates_and_sorts(client, monkeypatch, clear_macro_cache):
    """财报(7天后)+宏观(3天后)聚合，按 days_until 升序，占位符过滤。"""
    monkeypatch.setattr(
        mr, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )
    monkeypatch.setattr(mr, "get_event_calendar", _calendar_with(earnings_days=7, macro_days=3))

    resp = client.get(f"/api/monitor/macro-calendar?session_id={SESSION}&days_ahead=14")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    events = body["events"]
    # 财报 + 宏观各一条，占位符(date=None)被过滤
    assert len(events) == 2
    # 升序：宏观 3 天在前，财报 7 天在后
    assert events[0]["days_until"] == 3
    assert events[0]["kind"] == "macro"
    assert events[0]["ticker"] is None
    assert events[1]["days_until"] == 7
    assert events[1]["kind"] == "earnings"
    assert events[1]["ticker"] == "AAPL"


def test_macro_calendar_filters_out_of_window(client, monkeypatch, clear_macro_cache):
    """超出 days_ahead 窗口的事件被过滤。"""
    monkeypatch.setattr(
        mr, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )
    # 财报 20 天后，days_ahead=14 → 应被过滤
    monkeypatch.setattr(mr, "get_event_calendar", _calendar_with(earnings_days=20, macro_days=None))

    resp = client.get(f"/api/monitor/macro-calendar?session_id={SESSION}&days_ahead=14")
    assert resp.status_code == 200
    assert resp.json()["events"] == []


def test_macro_calendar_cache_avoids_second_call(client, monkeypatch, clear_macro_cache):
    """第二次请求命中缓存，不再调 get_event_calendar。"""
    monkeypatch.setattr(
        mr, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )
    calls = {"n": 0}

    def counting_cal(ticker, days_ahead=7):
        calls["n"] += 1
        return _calendar_with(earnings_days=5, macro_days=None)(ticker, days_ahead)

    monkeypatch.setattr(mr, "get_event_calendar", counting_cal)

    r1 = client.get(f"/api/monitor/macro-calendar?session_id={SESSION}&days_ahead=14")
    assert r1.status_code == 200
    first_calls = calls["n"]
    assert first_calls > 0

    r2 = client.get(f"/api/monitor/macro-calendar?session_id={SESSION}&days_ahead=14")
    assert r2.status_code == 200
    # 命中缓存：调用次数不变
    assert calls["n"] == first_calls


def test_macro_calendar_external_failure_returns_empty(client, monkeypatch, clear_macro_cache):
    """外部 API 全挂 → 返回空列表，不报错。"""
    monkeypatch.setattr(
        mr, "get_positions", lambda sid: [{"ticker": "AAPL", "shares": 5, "avg_cost": 150.0}]
    )

    def boom(ticker, days_ahead=7):
        raise RuntimeError("external API down")

    monkeypatch.setattr(mr, "get_event_calendar", boom)

    resp = client.get(f"/api/monitor/macro-calendar?session_id={SESSION}&days_ahead=14")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["events"] == []


# ── Phase 3：通知设置 CRUD ────────────────────────────────────


def test_settings_get_default(client):
    """无记录时返回默认（空邮箱、关闭）。"""
    resp = client.get(f"/api/monitor/settings?session_id={SESSION}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["notify_email"] is None
    assert body["notify_enabled"] is False
    assert "smtp_configured" in body


def test_settings_upsert_and_get(client, monkeypatch):
    """SMTP 配置 + 合法邮箱 → 启用通知成功，回读一致。"""
    monkeypatch.setenv("SMTP_USER", "u@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")

    resp = client.put(
        "/api/monitor/settings",
        json={"session_id": SESSION, "notify_email": "owner@example.com", "notify_enabled": True},
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(f"/api/monitor/settings?session_id={SESSION}")
    body = resp.json()
    assert body["notify_email"] == "owner@example.com"
    assert body["notify_enabled"] is True
    assert body["smtp_configured"] is True


def test_settings_enable_without_smtp_rejected(client, monkeypatch):
    """SMTP 未配置时启用通知 → 422。"""
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    resp = client.put(
        "/api/monitor/settings",
        json={"session_id": SESSION, "notify_email": "owner@example.com", "notify_enabled": True},
    )
    assert resp.status_code == 422
    assert "SMTP" in resp.json()["detail"]


def test_settings_invalid_email_rejected(client, monkeypatch):
    """邮箱格式非法 → 422。"""
    monkeypatch.setenv("SMTP_USER", "u@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")

    resp = client.put(
        "/api/monitor/settings",
        json={"session_id": SESSION, "notify_email": "not-an-email", "notify_enabled": True},
    )
    assert resp.status_code == 422
    assert "邮箱" in resp.json()["detail"]
