# -*- coding: utf-8 -*-
"""
工作台 Phase 1：MonitorStore 存储层测试。

覆盖：Finding/MonitorTarget CRUD、去重窗口、状态更新、30 天清理、session 隔离。
SQLite 路径统一走 tmp_path（不污染 data/monitor.db）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.services.monitor_store import MonitorStore


def _make_finding(session_id: str, target: str = "TSLA", trigger_type: str = "price_move", **overrides) -> dict:
    """构造一条最小 Finding 记录。"""
    base = {
        "id": uuid.uuid4().hex,
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "trigger_type": trigger_type,
        "trigger_detail": {"change_pct": -5.2, "threshold": 5.0, "price": 182.3},
        "title": f"{target} 单日下跌 5.2%",
        "summary": f"{target} 今日大幅下跌，建议关注。",
        "agent_analysis": None,
        "actions": [{"type": "full_report", "label": "全面体检", "ticker": target}],
        "status": "new",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def store(tmp_path) -> MonitorStore:
    return MonitorStore(db_path=str(tmp_path / "monitor_test.db"))


# ── Finding CRUD ──────────────────────────────────────────────


def test_insert_and_list_finding(store: MonitorStore):
    f = _make_finding("sess-a")
    store.insert_finding(f)

    rows = store.list_findings("sess-a")
    assert len(rows) == 1
    got = rows[0]
    assert got["id"] == f["id"]
    assert got["target"] == "TSLA"
    assert got["trigger_type"] == "price_move"
    # JSON 字段应回填为 dict / list
    assert isinstance(got["trigger_detail"], dict)
    assert got["trigger_detail"]["change_pct"] == -5.2
    assert isinstance(got["actions"], list)
    assert got["actions"][0]["type"] == "full_report"
    assert got["agent_analysis"] is None
    assert got["status"] == "new"


def test_list_findings_order_desc(store: MonitorStore):
    older = _make_finding("sess-a", created_at="2026-01-01T00:00:00+00:00")
    newer = _make_finding("sess-a", created_at="2026-06-01T00:00:00+00:00")
    store.insert_finding(older)
    store.insert_finding(newer)

    rows = store.list_findings("sess-a")
    assert [r["id"] for r in rows] == [newer["id"], older["id"]]


def test_list_findings_status_filter_and_limit(store: MonitorStore):
    store.insert_finding(_make_finding("sess-a", status="new"))
    store.insert_finding(_make_finding("sess-a", status="viewed"))
    store.insert_finding(_make_finding("sess-a", status="new"))

    new_rows = store.list_findings("sess-a", status="new")
    assert len(new_rows) == 2
    assert all(r["status"] == "new" for r in new_rows)

    limited = store.list_findings("sess-a", limit=1)
    assert len(limited) == 1


def test_update_finding_status(store: MonitorStore):
    f = _make_finding("sess-a")
    store.insert_finding(f)

    ok = store.update_finding_status("sess-a", f["id"], "viewed")
    assert ok is True
    assert store.list_findings("sess-a")[0]["status"] == "viewed"

    # 不存在的 finding -> False
    assert store.update_finding_status("sess-a", "nope", "acted") is False


def test_session_isolation_findings(store: MonitorStore):
    store.insert_finding(_make_finding("sess-a"))
    store.insert_finding(_make_finding("sess-b"))

    assert len(store.list_findings("sess-a")) == 1
    assert len(store.list_findings("sess-b")) == 1
    # A 改不到 B 的记录
    b_id = store.list_findings("sess-b")[0]["id"]
    assert store.update_finding_status("sess-a", b_id, "viewed") is False


# ── 去重窗口 ──────────────────────────────────────────────────


def test_has_recent_finding_within_window(store: MonitorStore):
    f = _make_finding("sess-a", target="TSLA", trigger_type="price_move")
    store.insert_finding(f)

    assert store.has_recent_finding("sess-a", "TSLA", "price_move", within_hours=4) is True
    # 不同标的 / 不同类型 -> False
    assert store.has_recent_finding("sess-a", "AAPL", "price_move", within_hours=4) is False
    assert store.has_recent_finding("sess-a", "TSLA", "concentration", within_hours=4) is False
    # 不同 session -> False
    assert store.has_recent_finding("sess-b", "TSLA", "price_move", within_hours=4) is False


def test_has_recent_finding_outside_window(store: MonitorStore):
    stale = datetime.now(timezone.utc) - timedelta(hours=6)
    f = _make_finding("sess-a", target="TSLA", created_at=stale.isoformat())
    store.insert_finding(f)

    # 6 小时前的记录在 4 小时窗口外
    assert store.has_recent_finding("sess-a", "TSLA", "price_move", within_hours=4) is False


# ── 清理 ──────────────────────────────────────────────────────


def test_cleanup_old_findings(store: MonitorStore):
    old = datetime.now(timezone.utc) - timedelta(days=40)
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    store.insert_finding(_make_finding("sess-a", created_at=old.isoformat()))
    store.insert_finding(_make_finding("sess-a", created_at=recent.isoformat()))

    deleted = store.cleanup_old_findings(days=30)
    assert deleted == 1
    rows = store.list_findings("sess-a")
    assert len(rows) == 1


# ── MonitorTarget CRUD ───────────────────────────────────────


def _make_target(session_id: str, **overrides) -> dict:
    base = {
        "id": uuid.uuid4().hex,
        "session_id": session_id,
        "type": "holding",
        "ticker": "TSLA",
        "config": {"price_move_pct": 6.0},
        "enabled": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


def test_upsert_and_list_targets(store: MonitorStore):
    t = _make_target("sess-a")
    store.upsert_target(t)

    rows = store.list_targets("sess-a")
    assert len(rows) == 1
    got = rows[0]
    assert got["ticker"] == "TSLA"
    assert got["type"] == "holding"
    assert isinstance(got["config"], dict)
    assert got["config"]["price_move_pct"] == 6.0
    assert got["enabled"] is True


def test_upsert_target_update_existing(store: MonitorStore):
    t = _make_target("sess-a")
    store.upsert_target(t)
    # 同 id 再 upsert -> 更新而非新增
    t2 = {**t, "config": {"price_move_pct": 9.0}, "enabled": False}
    store.upsert_target(t2)

    rows = store.list_targets("sess-a")
    assert len(rows) == 1
    assert rows[0]["config"]["price_move_pct"] == 9.0
    assert rows[0]["enabled"] is False


def test_delete_target(store: MonitorStore):
    t = _make_target("sess-a")
    store.upsert_target(t)

    assert store.delete_target("sess-a", t["id"]) is True
    assert store.list_targets("sess-a") == []
    # 重复删除 -> False
    assert store.delete_target("sess-a", t["id"]) is False


def test_session_isolation_targets(store: MonitorStore):
    ta = _make_target("sess-a", ticker="TSLA")
    tb = _make_target("sess-b", ticker="AAPL")
    store.upsert_target(ta)
    store.upsert_target(tb)

    assert len(store.list_targets("sess-a")) == 1
    assert store.list_targets("sess-a")[0]["ticker"] == "TSLA"
    # A 删不到 B 的 target
    assert store.delete_target("sess-a", tb["id"]) is False


def test_target_portfolio_level_null_ticker(store: MonitorStore):
    t = _make_target("sess-a", id="pf-1", type="custom", ticker=None, config={"concentration_pct": 80.0})
    store.upsert_target(t)
    rows = store.list_targets("sess-a")
    assert rows[0]["ticker"] is None
    assert rows[0]["config"]["concentration_pct"] == 80.0
