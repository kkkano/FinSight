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
    def __init__(self, *, row=None, rows=None, rowcount=1):
        self._row = row
        self._rows = rows if rows is not None else ([row] if row is not None else [])
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return self._rows


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.row = None
        self.rows = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if sql.lstrip().upper().startswith("SELECT"):
            return FakeResult(row=self.row, rows=self.rows or None)
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
        "scenarios": [
            {"name": "延续", "probability": 60, "invalidation": "跌破止损"},
            {"name": "失败", "probability": 40, "invalidation": "突破目标"},
        ],
        "report_id": None,
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
    assert "scenarios JSONB" in schema_sql


def test_get_always_filters_by_prediction_id_and_user_id():
    engine = FakeEngine()
    engine.conn.row = _record()
    store = AgentPredictionStore(engine=engine)
    result = store.get("pred-1", user_id="alice")
    select_sql, params = [call for call in engine.conn.calls if call[0].lstrip().upper().startswith("SELECT")][-1]
    assert "id = CAST(:id AS uuid) AND user_id = :user_id" in select_sql
    assert params == {"id": "pred-1", "user_id": "alice"}
    assert result and result.user_id == "alice"


def test_latest_and_history_queries_are_tenant_agent_and_ticker_scoped():
    engine = FakeEngine()
    engine.conn.rows = [_record(id="00000000-0000-0000-0000-000000000001")]
    store = AgentPredictionStore(engine=engine)

    latest = store.latest_predictions(ticker="aapl", user_id="alice", limit_per_agent=1)
    latest_sql, latest_params = [
        call for call in engine.conn.calls if "ROW_NUMBER()" in call[0]
    ][-1]
    assert "user_id = :user_id AND symbol = :symbol" in latest_sql
    assert latest_params == {"user_id": "alice", "symbol": "AAPL", "limit_per_agent": 1}
    assert latest[0]["agent"] == "technical_agent"

    history = store.prediction_history(
        agent="technical_agent", ticker="AAPL", user_id="alice", limit=5,
    )
    history_sql, history_params = [
        call for call in engine.conn.calls if "agent = :agent" in call[0]
    ][-1]
    assert "user_id = :user_id AND agent = :agent AND symbol = :symbol" in history_sql
    assert history_params == {
        "user_id": "alice", "agent": "technical_agent", "symbol": "AAPL", "limit": 5,
    }
    assert history[0]["symbol"] == "AAPL"


def test_latest_and_history_reject_public_identity_without_querying():
    engine = FakeEngine()
    store = AgentPredictionStore(engine=engine)
    assert store.latest_predictions(ticker="AAPL", user_id="public") == []
    assert store.prediction_history(agent="technical_agent", ticker="AAPL", user_id="public") == []
    assert engine.conn.calls == []


def test_attach_report_is_tenant_scoped():
    engine = FakeEngine()
    store = AgentPredictionStore(engine=engine)
    assert store.attach_report(
        "00000000-0000-0000-0000-000000000001",
        user_id="alice",
        report_id="rpt-1",
    )
    update_sql, params = [call for call in engine.conn.calls if call[0].lstrip().upper().startswith("UPDATE")][-1]
    assert "id = CAST(:id AS uuid) AND user_id = :user_id" in update_sql
    assert params == {
        "report_id": "rpt-1",
        "id": "00000000-0000-0000-0000-000000000001",
        "user_id": "alice",
    }


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
