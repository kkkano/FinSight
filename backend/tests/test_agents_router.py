# -*- coding: utf-8 -*-
"""test_agents_router — 验证 GET /api/agents 供前端 @agent 选择。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.agents_router import AgentsRouterDeps, create_agents_router
from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_agents_router(AgentsRouterDeps(memory_service=None)))
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
        assert len(item["glyph"]) == 1
        assert item["color_token"].startswith("t-")
        assert item["mandate"]
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


def test_list_agents_returns_tenant_scoped_track_record_and_cost():
    class Outcomes:
        def track_record(self, *, user_id, agent, days):
            assert user_id == "alice" and days == 90
            return {"sample_count": 5, "hit_rate": 0.8, "sample_state": "sufficient", "by_direction": {}}

    class Archive:
        def cost_summary(self, *, user_id, agent, days):
            assert user_id == "alice"
            return {"days": days, "tokens": days * 10, "cost_usd": 0.1, "run_count": 1, "call_count": 2, "failed_call_count": 0, "unscored_runs": 0}

    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = "alice"
        return await call_next(request)

    app.include_router(create_agents_router(AgentsRouterDeps(
        memory_service=None,
        get_outcome_store=lambda: Outcomes(),
        get_run_archive=lambda: Archive(),
    )))
    item = TestClient(app).get("/api/agents", params={"limit": 1}).json()["items"][0]
    assert item["track_record"]["hit_rate"] == 0.8
    assert item["cost_summary"]["days_7"]["tokens"] == 70


def test_public_agent_list_never_queries_private_aggregates():
    def forbidden():
        raise AssertionError("public request must not query tenant stores")

    app = FastAPI()
    app.include_router(create_agents_router(AgentsRouterDeps(
        memory_service=None, get_outcome_store=forbidden, get_run_archive=forbidden,
    )))
    item = TestClient(app).get("/api/agents", params={"limit": 1}).json()["items"][0]
    assert item["track_record"]["sample_state"] == "样本不足"
    assert item["cost_summary"]["days_30"]["tokens"] == 0
