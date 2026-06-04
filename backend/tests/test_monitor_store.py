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


# ── 默认数据目录路径锚定（CWD split-brain 修复回归）─────────────


def test_default_db_dir_anchored_to_repo_root_not_cwd(monkeypatch):
    """默认数据目录应基于 __file__ 锚定到仓库根/data，绝对路径、与启动 CWD 无关。

    回归曾出现的 split-brain（data/portfolio.db 与 backend/data/portfolio.db 两份）。
    """
    import importlib
    from pathlib import Path

    # 清掉环境变量覆盖，强制走默认锚定
    monkeypatch.delenv("FINSIGHT_DATA_DIR", raising=False)

    from backend.services import portfolio_store, monitor_store, cost_audit

    importlib.reload(portfolio_store)
    importlib.reload(monitor_store)
    importlib.reload(cost_audit)

    repo_root = Path(__file__).resolve().parents[2]  # backend/tests/ -> 仓库根
    expected_data = repo_root / "data"

    # 三个 store 默认目录都绝对、都锚定到同一个仓库根/data（单一真相源）
    assert monitor_store._DEFAULT_DB_DIR.is_absolute()
    assert monitor_store._DEFAULT_DB_DIR == expected_data
    assert portfolio_store._DB_DIR.is_absolute()
    assert portfolio_store._DB_DIR == expected_data
    assert cost_audit._DEFAULT_DB_DIR.is_absolute()
    assert cost_audit._DEFAULT_DB_DIR == expected_data


def test_env_override_still_respected(monkeypatch, tmp_path):
    """显式 FINSIGHT_DATA_DIR 仍优先于默认锚定（容器挂载 / 自定义路径不被破坏）。"""
    import importlib

    monkeypatch.setenv("FINSIGHT_DATA_DIR", str(tmp_path))
    from backend.services import monitor_store

    importlib.reload(monitor_store)
    try:
        assert monitor_store._DEFAULT_DB_DIR == tmp_path
    finally:
        monkeypatch.delenv("FINSIGHT_DATA_DIR", raising=False)
        importlib.reload(monitor_store)


# ── 通知冷却落库（重启 / 多 worker 不重发回归）─────────────────


def test_notify_cooldown_roundtrip(store: MonitorStore):
    """set/get 冷却时间戳 round-trip：写入后可读回 aware datetime。"""
    assert store.get_last_notified_at("sess-x") is None
    store.set_last_notified_at("sess-x")
    got = store.get_last_notified_at("sess-x")
    assert got is not None
    assert got.tzinfo is not None  # 必须是 aware（UTC），否则后续相减会抛 TypeError


def test_notify_cooldown_persists_to_new_instance(tmp_path):
    """同一 db 文件、新建 store 实例仍能读回冷却时间戳（模拟重启 / 多 worker）。"""
    db_file = str(tmp_path / "cooldown.db")
    s1 = MonitorStore(db_path=db_file)
    fixed = datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc)
    s1.set_last_notified_at("sess-x", fixed)

    s2 = MonitorStore(db_path=db_file)
    assert s2.get_last_notified_at("sess-x") == fixed


def test_notify_cooldown_upsert_overwrites(store: MonitorStore):
    """重复 set 覆盖为最新时间戳（同 session 单行）。"""
    t1 = datetime(2026, 6, 4, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 4, 11, 0, 0, tzinfo=timezone.utc)
    store.set_last_notified_at("sess-x", t1)
    store.set_last_notified_at("sess-x", t2)
    assert store.get_last_notified_at("sess-x") == t2
