# -*- coding: utf-8 -*-
"""Agent prediction/outcome/cost 的真实 PostgreSQL 租户门禁。

默认测试集不要求本机 PostgreSQL；发布门禁显式设置
``FINSIGHT_POSTGRES_INTEGRATION_DSN`` 后执行。所有样本写入同一事务并在结束时回滚。
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from backend.agents.prediction_contract import AgentPrediction
from backend.services.agent_prediction_store import AgentPredictionStore
from backend.services.agent_run_archive import AgentRunArchive
from backend.services.prediction_outcomes import (
    PredictionOutcomeStore,
    resolve_prediction_outcome,
)


class _TransactionEngine:
    """让 store 的 begin/connect 共用外层事务，测试结束统一回滚。"""

    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def begin(self):
        yield self.connection

    @contextmanager
    def connect(self):
        yield self.connection


@pytest.fixture
def postgres_transaction(monkeypatch):
    dsn = os.getenv("FINSIGHT_POSTGRES_INTEGRATION_DSN", "").strip()
    if not dsn:
        pytest.skip("需要 FINSIGHT_POSTGRES_INTEGRATION_DSN 才运行真实 PostgreSQL 门禁")

    engine = create_engine(dsn, future=True, pool_pre_ping=True)
    schema_store = AgentPredictionStore(engine=engine)
    schema_store.ensure_schema()
    monkeypatch.setattr(
        "backend.services.agent_prediction_store.get_agent_prediction_store",
        lambda: schema_store,
    )
    PredictionOutcomeStore(engine=engine).ensure_schema()
    AgentRunArchive(engine=engine).ensure_schema()

    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield _TransactionEngine(connection)
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()


def _prediction(*, prediction_id: str, user_id: str, run_id: str) -> AgentPrediction:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    return AgentPrediction.model_validate({
        "id": prediction_id,
        "user_id": user_id,
        "run_id": run_id,
        "symbol": "AAPL",
        "agent": "technical_agent",
        "direction": "long",
        "confidence": 0.8,
        "thesis": "固定回放验证趋势延续",
        "anchor": {"timeframe": "1d", "time": "2026-07-10", "price": 100.0},
        "entry_type": "limit",
        "entry": 101.0,
        "stop": 96.0,
        "target1": 111.0,
        "invalidation_price": 95.0,
        "scenarios": [
            {"name": "延续", "probability": 60, "invalidation": "跌破止损"},
            {"name": "失败", "probability": 40, "invalidation": "突破目标"},
        ],
        "status": "waiting",
        "created_at": now,
        "updated_at": now,
    })


def test_prediction_outcome_run_cost_are_traceable_and_tenant_safe(
    postgres_transaction,
    monkeypatch,
):
    prediction_store = AgentPredictionStore(engine=postgres_transaction)
    monkeypatch.setattr(
        "backend.services.agent_prediction_store.get_agent_prediction_store",
        lambda: prediction_store,
    )
    outcome_store = PredictionOutcomeStore(engine=postgres_transaction)
    archive = AgentRunArchive(engine=postgres_transaction)

    prediction_id = str(uuid4())
    run_id = f"pg-gate-{uuid4()}"
    prediction = _prediction(
        prediction_id=prediction_id,
        user_id="pg-gate-alice",
        run_id=run_id,
    )
    prediction_store.create(prediction)

    assert prediction_store.get(prediction_id, user_id="pg-gate-alice") is not None
    assert prediction_store.get(prediction_id, user_id="pg-gate-bob") is None

    bars = [
        {"time": "2026-07-11", "open": 100, "high": 103, "low": 99, "close": 102},
        {"time": "2026-07-12", "open": 102, "high": 112, "low": 100, "close": 110},
    ]
    first = resolve_prediction_outcome(prediction, bars)
    second = resolve_prediction_outcome(prediction, list(reversed(bars)))
    assert first.model_dump_json() == second.model_dump_json()
    outcome_store.upsert(first)

    written = archive.archive_usage_summary(
        run_id=run_id,
        user_id="pg-gate-alice",
        summary={"usage_by_attribution": [{
            "agent": "technical_agent",
            "layer": "prediction_submit",
            "prediction_id": prediction_id,
            "model": "integration-test-model",
            "prompt": 100,
            "completion": 20,
            "calls": 1,
            "failed_calls": 0,
            "duration_ms": 12,
        }]},
    )
    assert written == 1

    row = postgres_transaction.connection.execute(text(
        "SELECT p.id,o.status,r.run_id,r.total_tokens,r.cost_usd "
        "FROM agent_predictions p "
        "JOIN agent_prediction_outcomes o ON o.prediction_id=p.id AND o.user_id=p.user_id "
        "JOIN agent_run_archive r ON r.prediction_id=p.id AND r.user_id=p.user_id "
        "WHERE p.id=CAST(:id AS uuid) AND p.user_id=:user_id"
    ), {"id": prediction_id, "user_id": "pg-gate-alice"}).mappings().one()
    assert row["status"] == "hit_target"
    assert row["run_id"] == run_id
    assert row["total_tokens"] == 120

    cross_user_count = postgres_transaction.connection.execute(text(
        "SELECT COUNT(*) FROM agent_predictions p "
        "JOIN agent_prediction_outcomes o ON o.prediction_id=p.id AND o.user_id=p.user_id "
        "WHERE p.id=CAST(:id AS uuid) AND p.user_id=:user_id"
    ), {"id": prediction_id, "user_id": "pg-gate-bob"}).scalar_one()
    assert cross_user_count == 0

    forged = first.model_copy(update={"user_id": "pg-gate-bob"})
    with pytest.raises(IntegrityError):
        with postgres_transaction.connection.begin_nested():
            outcome_store.upsert(forged)
