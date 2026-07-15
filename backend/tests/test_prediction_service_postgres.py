# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from backend.agents.prediction_contract import AgentPrediction
from backend.services.database import normalize_sync_postgres_dsn
from backend.services.prediction_service import PredictionRunStore


TEST_DSN = os.getenv("FINSIGHT_TEST_POSTGRES_DSN", "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="需要显式配置隔离的 FINSIGHT_TEST_POSTGRES_DSN",
)


def _prediction(*, run_id: str, user_id: str, prediction_id: str) -> AgentPrediction:
    now = datetime.now(timezone.utc)
    return AgentPrediction.model_validate({
        "id": prediction_id,
        "user_id": user_id,
        "run_id": run_id,
        "symbol": "AAPL",
        "agent": "prediction_analyst",
        "direction": "long",
        "confidence": 0.8,
        "thesis": "真实 PostgreSQL 原子事务验收记录。",
        "anchor": {"timeframe": "1d", "time": "2026-07-15", "price": 100},
        "entry_type": "market",
        "entry": 100,
        "stop": 95,
        "target1": 110,
        "invalidation_price": 94,
        "scenarios": [
            {"name": "延续", "probability": 60, "invalidation": "跌破止损"},
            {"name": "回撤", "probability": 40, "invalidation": "突破目标"},
        ],
        "status": "waiting",
        "prompt_version": "postgres-integration-v1",
        "evidence_provider": "postgres-integration-fixture",
        "evidence_as_of": now,
        "source_type": "ai",
        "created_at": now,
        "updated_at": now,
    })


def _attempt() -> dict[str, object]:
    return {
        "attempt": 1,
        "provider": "postgres-integration-fixture",
        "model": "fixture-model",
        "status": "success",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "duration_ms": 20,
        "error_code": None,
    }


def _table_counts(conn, *, run_id: str) -> dict[str, int]:
    statements = {
        "agent_predictions": "SELECT count(*) FROM agent_predictions WHERE run_id=:run_id",
        "llm_usage": "SELECT count(*) FROM llm_usage WHERE run_id=:run_id",
        "agent_run_archive": "SELECT count(*) FROM agent_run_archive WHERE run_id=:run_id",
        "prediction_runs": "SELECT count(*) FROM prediction_runs WHERE id=CAST(:run_id AS uuid)",
    }
    return {
        table: int(conn.execute(text(statement), {"run_id": run_id}).scalar_one())
        for table, statement in statements.items()
    }


def _delete_run(engine, *, run_id: str, user_id: str) -> None:
    with engine.begin() as conn:
        params = {"run_id": run_id, "user_id": user_id}
        conn.execute(text("DELETE FROM llm_usage WHERE run_id=:run_id AND user_id=:user_id"), params)
        conn.execute(text("DELETE FROM agent_run_archive WHERE run_id=:run_id AND user_id=:user_id"), params)
        conn.execute(text(
            "DELETE FROM prediction_runs WHERE id=CAST(:run_id AS uuid) AND user_id=:user_id"
        ), params)
        conn.execute(text("DELETE FROM agent_predictions WHERE run_id=:run_id AND user_id=:user_id"), params)


def _claimed_run(store: PredictionRunStore, *, user_id: str):
    run, created = store.create_or_get_active(
        user_id=user_id,
        symbol="AAPL",
        timeframe="1d",
        prompt_version="postgres-integration-v1",
    )
    assert created is True
    claimed = store.claim(run.id)
    assert claimed is not None
    return claimed


def test_prediction_success_and_failure_are_atomic_on_real_postgres() -> None:
    engine = create_engine(normalize_sync_postgres_dsn(TEST_DSN))
    store = PredictionRunStore(engine=engine)
    success_user = f"wp3-success-{uuid4().hex}"
    rollback_user = f"wp3-rollback-{uuid4().hex}"
    success_run = _claimed_run(store, user_id=success_user)
    rollback_run = _claimed_run(store, user_id=rollback_user)
    success_prediction_id = str(uuid4())
    rollback_prediction_id = str(uuid4())
    trigger_suffix = rollback_run.id.replace("-", "")
    trigger_name = f"fail_prediction_run_{trigger_suffix}"
    function_name = f"{trigger_name}_fn"

    try:
        store.complete_success(
            success_run,
            _prediction(
                run_id=success_run.id,
                user_id=success_user,
                prediction_id=success_prediction_id,
            ),
            attempts=[_attempt()],
            latency_ms=25,
        )
        with engine.connect() as conn:
            assert _table_counts(conn, run_id=success_run.id) == {
                "agent_predictions": 1,
                "llm_usage": 1,
                "agent_run_archive": 1,
                "prediction_runs": 1,
            }
            status = conn.execute(
                text("SELECT status FROM prediction_runs WHERE id=CAST(:run_id AS uuid)"),
                {"run_id": success_run.id},
            ).scalar_one()
            assert status == "succeeded"

        with engine.begin() as conn:
            conn.execute(text(
                f"CREATE FUNCTION {function_name}() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN RAISE EXCEPTION 'forced atomic rollback'; END $$"
            ))
            conn.execute(text(
                f"CREATE TRIGGER {trigger_name} BEFORE UPDATE ON prediction_runs "
                f"FOR EACH ROW WHEN (OLD.id = '{rollback_run.id}'::uuid) "
                f"EXECUTE FUNCTION {function_name}()"
            ))

        with pytest.raises(DBAPIError, match="forced atomic rollback"):
            store.complete_success(
                rollback_run,
                _prediction(
                    run_id=rollback_run.id,
                    user_id=rollback_user,
                    prediction_id=rollback_prediction_id,
                ),
                attempts=[_attempt()],
                latency_ms=25,
            )

        with engine.connect() as conn:
            counts = _table_counts(conn, run_id=rollback_run.id)
            assert counts == {
                "agent_predictions": 0,
                "llm_usage": 0,
                "agent_run_archive": 0,
                "prediction_runs": 1,
            }
            status = conn.execute(
                text("SELECT status FROM prediction_runs WHERE id=CAST(:run_id AS uuid)"),
                {"run_id": rollback_run.id},
            ).scalar_one()
            assert status == "running"
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON prediction_runs"))
            conn.execute(text(f"DROP FUNCTION IF EXISTS {function_name}()"))
        _delete_run(engine, run_id=success_run.id, user_id=success_user)
        _delete_run(engine, run_id=rollback_run.id, user_id=rollback_user)
        engine.dispose()
