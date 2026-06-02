# -*- coding: utf-8 -*-
"""test_agents_router — 验证 GET /api/agents 供前端 @agent 选择。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.agents_router import create_agents_router
from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_agents_router())
    return TestClient(app)


def test_list_agents_returns_all_candidates():
    resp = _client().get("/api/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True

    names = [item["name"] for item in data["items"]]
    # 覆盖 capability_registry 的全部候选 agent（单一数据源）
    assert set(names) == set(REPORT_AGENT_CANDIDATES)

    for item in data["items"]:
        assert item["display_name"], "每个 agent 必须有中文展示名"
        assert item["description"], "每个 agent 必须有描述"
        # insert_text 用 @{name} 触发，供前端插入输入框
        assert item["insert_text"] == f"@{item['name']} "


def test_list_agents_query_filters_by_display_name():
    resp = _client().get("/api/agents", params={"query": "宏观"})
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()["items"]]
    assert "macro_agent" in names
    assert "price_agent" not in names


def test_list_agents_respects_limit():
    resp = _client().get("/api/agents", params={"limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2
