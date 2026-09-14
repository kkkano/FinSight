from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest

from backend.services.agent_prediction_store import (
    AgentPredictionStore,
    PredictionStoreUnavailable,
    UnavailableAgentPredictionStore,
)


class _Result:
    def __init__(self, *, row=None, rows=None, rowcount=1):
        self.row = row
        self.rows = rows if rows is not None else ([row] if row is not None else [])
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows


class _Connection:
    def __init__(self):
        self.calls = []
        self.row = None
        self.rows = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if sql.lstrip().upper().startswith("SELECT"):
            return _Result(row=self.row, rows=self.rows or None)
        return _Result()


class _Engine:
    def __init__(self):
        self.connection = _Connection()
        self.begin_calls = 0

    @contextmanager
    def begin(self):
        self.begin_calls += 1
        yield self.connection

    @contextmanager
    def connect(self):
        yield self.connection


def _record(**overrides):
    record = {
        "id": "00000000-0000-0000-0000-000000000001",
        "user_id": "alice",
        "run_id": "00000000-0000-0000-0000-000000000002",
        "symbol": "AAPL",
        "agent": "prediction_analyst",
        "direction": "long",
        "confidence": 0.8,
        "thesis": "trend continuation",
        "anchor_timeframe": "1d",
        "anchor_time": "2026-07-10",
        "anchor_price": 103.0,
        "entry_type": "limit",
        "entry": 104.0,
        "stop": 99.0,
        "target1": 114.0,
        "target2": None,
        "invalidation_price": 98.0,
        "range_low": None,
        "range_high": None,
        "scenarios": [
            {"name": "continuation", "probability": 60, "invalidation": "break stop"},
            {"name": "failure", "probability": 40, "invalidation": "break target"},
        ],
        "report_id": None,
        "status": "waiting",
        "created_at": datetime(2026, 7, 11, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 7, 11, tzinfo=timezone.utc),
    }
    record.update(overrides)
    return record


def test_store_constructor_runs_no_schema_ddl():
    engine = _Engine()
    store = AgentPredictionStore(engine=engine)
    assert not hasattr(store, "ensure_schema")
    assert engine.connection.calls == []


def test_prediction_reads_are_tenant_and_symbol_scoped():
    engine = _Engine()
    engine.connection.row = _record(id=UUID("00000000-0000-0000-0000-000000000001"))
    store = AgentPredictionStore(engine=engine)

    prediction = store.get("pred-1", user_id="alice")
    sql, params = engine.connection.calls[-1]
    assert prediction and prediction.user_id == "alice"
    assert "id = CAST(:id AS uuid) AND user_id = :user_id" in sql
    assert params == {"id": "pred-1", "user_id": "alice"}

    engine.connection.calls.clear()
    latest = store.get_latest(user_id="alice", symbol="aapl")
    sql, params = engine.connection.calls[-1]
    assert latest and latest.symbol == "AAPL"
    assert "user_id = :user_id AND symbol = :symbol" in sql
    assert params == {"user_id": "alice", "symbol": "AAPL"}


def test_public_history_fails_closed_without_querying():
    engine = _Engine()
    store = AgentPredictionStore(engine=engine)
    assert store.latest_predictions(ticker="AAPL", user_id="public") == []
    assert store.prediction_history(agent="prediction_analyst", ticker="AAPL", user_id="public") == []
    assert engine.connection.calls == []


def test_attach_report_is_tenant_scoped():
    engine = _Engine()
    store = AgentPredictionStore(engine=engine)
    assert store.attach_report(
        "00000000-0000-0000-0000-000000000001",
        user_id="alice",
        report_id="rpt-1",
    )
    sql, params = engine.connection.calls[-1]
    assert "id = CAST(:id AS uuid) AND user_id = :user_id" in sql
    assert params["user_id"] == "alice"


def test_store_fails_closed_without_postgres():
    store = UnavailableAgentPredictionStore("postgres dsn missing")
    with pytest.raises(PredictionStoreUnavailable):
        store.get("pred-1", user_id="alice")
