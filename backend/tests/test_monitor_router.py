# -*- coding: utf-8 -*-
"""
工作台 Phase 1：monitor_router API 冒烟测试。

用 TestClient 走真实路由；通过 MONITOR_DB_PATH 环境变量 + 单例重置把
SQLite 落到 tmp_path，避免污染 data/monitor.db。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import monitor_engine
from backend.services import monitor_store as ms
from backend.services.alert_scheduler import PriceSnapshot


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 单例重置 + 路径重定向到 tmp
    monkeypatch.setenv("MONITOR_DB_PATH", str(tmp_path / "monitor_router_test.db"))
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
