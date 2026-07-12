# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.agents_router import AgentsRouterDeps, create_agents_router
from backend.services.agent_prediction_store import (
    AgentPredictionStore,
    PredictionStoreUnavailable,
    UnavailableAgentPredictionStore,
)


class FakeResult:
    def __init__(self, *, row=None, rowcount=1):
        self._row = row
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self._row


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.row = None

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if sql.lstrip().upper().startswith("SELECT"):
            return FakeResult(row=self.row)
        return FakeResult()


class FakeEngine:
    def __init__(self):
        self.conn = FakeConnection()

    @contextmanager
    def begin(self):
        yield self.conn

    @contextmanager
    def connect(self):
        yield self.conn


def _record(**overrides):
    base = {
        "id": "pred-1", "user_id": "alice", "run_id": "run-1", "symbol": "AAPL",
        "agent": "technical_agent", "direction": "long", "confidence": 0.8,
        "thesis": "趋势延续", "anchor_timeframe": "1d", "anchor_time": "2026-07-10", "anchor_price": 103.0,
        "entry_type": "limit", "entry": 104.0, "stop": 99.0, "target1": 114.0,
        "target2": None, "invalidation_price": 98.0, "range_low": None, "range_high": None,
        "status": "waiting", "created_at": datetime(2026, 7, 11, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 7, 11, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def test_store_schema_is_postgres_and_has_composite_tenant_constraint():
    engine = FakeEngine()
    store = AgentPredictionStore(engine=engine)
    assert store.ensure_schema()
    schema_sql = "\n".join(sql for sql, _ in engine.conn.calls)
    assert "agent_predictions" in schema_sql
    assert "UNIQUE(id, user_id)" in schema_sql
    assert "TIMESTAMPTZ" in schema_sql


def test_get_always_filters_by_prediction_id_and_user_id():
    engine = FakeEngine()
    engine.conn.row = _record()
    store = AgentPredictionStore(engine=engine)
    result = store.get("pred-1", user_id="alice")
    select_sql, params = [call for call in engine.conn.calls if call[0].lstrip().upper().startswith("SELECT")][-1]
    assert "id = :id AND user_id = :user_id" in select_sql
    assert params == {"id": "pred-1", "user_id": "alice"}
    assert result and result.user_id == "alice"


def test_store_fails_closed_without_postgres():
    store = UnavailableAgentPredictionStore("postgres dsn missing")
    with pytest.raises(PredictionStoreUnavailable):
        store.get("pred-1", user_id="alice")


def test_prediction_api_is_authenticated_tenant_scoped_and_fail_closed():
    records = {("pred-1", "alice"): _record()}

    class Store:
        def get(self, prediction_id, *, user_id):
            row = records.get((prediction_id, user_id))
            if row is None:
                return None
            from backend.agents.prediction_contract import AgentPrediction
            payload = dict(row)
            payload["anchor"] = {
                "timeframe": payload.pop("anchor_timeframe"),
                "time": payload.pop("anchor_time"),
                "price": payload.pop("anchor_price"),
            }
            return AgentPrediction.model_validate(payload)

    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "public")
        return await call_next(request)

    app.include_router(create_agents_router(AgentsRouterDeps(memory_service=None, get_prediction_store=lambda: Store())))
    client = TestClient(app)

    assert client.get("/api/agents/predictions/pred-1").status_code == 401
    assert client.get("/api/agents/predictions/pred-1", headers={"x-test-user": "bob"}).status_code == 404
    response = client.get("/api/agents/predictions/pred-1", headers={"x-test-user": "alice"})
    assert response.status_code == 200
    assert response.json()["prediction"]["symbol"] == "AAPL"
    assert response.json()["prediction"]["predictionId"] == "pred-1"
    assert "user_id" not in response.json()["prediction"]

    unavailable_app = FastAPI()

    @unavailable_app.middleware("http")
    async def authenticated(request: Request, call_next):
        request.state.user_id = "alice"
        return await call_next(request)

    unavailable_app.include_router(create_agents_router(AgentsRouterDeps(
        memory_service=None,
        get_prediction_store=lambda: UnavailableAgentPredictionStore("down"),
    )))
    assert TestClient(unavailable_app).get("/api/agents/predictions/pred-1").status_code == 503
