# -*- coding: utf-8 -*-
"""Agent prediction 的 PostgreSQL-only 租户隔离存储。"""
from __future__ import annotations

import os
import json
import threading
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text

from backend.agents.prediction_contract import AgentPrediction


class PredictionStoreUnavailable(RuntimeError):
    pass


class UnavailableAgentPredictionStore:
    def __init__(self, reason: str = "prediction postgres unavailable") -> None:
        self.reason = reason

    def ensure_schema(self) -> bool:
        return False

    def create(self, prediction: AgentPrediction) -> AgentPrediction:
        raise PredictionStoreUnavailable(self.reason)

    def get(self, prediction_id: str, *, user_id: str) -> AgentPrediction | None:
        raise PredictionStoreUnavailable(self.reason)

    def get_latest(self, *, user_id: str, symbol: str) -> AgentPrediction | None:
        raise PredictionStoreUnavailable(self.reason)

    def latest_predictions(self, *, ticker: str, user_id: str, limit_per_agent: int = 1) -> list[dict[str, Any]]:
        raise PredictionStoreUnavailable(self.reason)

    def prediction_history(self, *, agent: str, ticker: str, user_id: str, limit: int = 5) -> list[dict[str, Any]]:
        raise PredictionStoreUnavailable(self.reason)

    def attach_report(self, prediction_id: str, *, user_id: str, report_id: str) -> bool:
        raise PredictionStoreUnavailable(self.reason)


class AgentPredictionStore:
    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        if engine is None:
            normalized = str(dsn or "").strip()
            if not normalized.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("agent prediction store 只允许 PostgreSQL DSN")
            engine = create_engine(normalized, future=True, pool_pre_ping=True)
        self._engine = engine
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def ensure_schema(self) -> bool:
        if self._schema_ready:
            return True
        with self._schema_lock:
            if self._schema_ready:
                return True
            with self._engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS agent_predictions ("
                    "id UUID NOT NULL, user_id TEXT NOT NULL, run_id TEXT NOT NULL, "
                    "symbol TEXT NOT NULL, agent TEXT NOT NULL, direction TEXT NOT NULL, "
                    "confidence DOUBLE PRECISION NOT NULL, thesis TEXT NOT NULL, "
                    "anchor_timeframe TEXT NOT NULL, anchor_time TEXT NOT NULL, anchor_price DOUBLE PRECISION NOT NULL, "
                    "entry_type TEXT NULL, entry DOUBLE PRECISION NULL, stop DOUBLE PRECISION NULL, "
                    "target1 DOUBLE PRECISION NULL, target2 DOUBLE PRECISION NULL, invalidation_price DOUBLE PRECISION NULL, "
                    "range_low DOUBLE PRECISION NULL, range_high DOUBLE PRECISION NULL, scenarios JSONB NOT NULL, "
                    "report_id TEXT NULL, status TEXT NOT NULL, "
                    "created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, "
                    "PRIMARY KEY(id), UNIQUE(id, user_id))"
                ))
                conn.execute(text(
                    "DO $$ BEGIN "
                    "IF EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'agent_predictions' AND column_name = 'id' AND data_type = 'text') "
                    "THEN ALTER TABLE agent_predictions ALTER COLUMN id TYPE UUID USING id::uuid; "
                    "END IF; END $$"
                ))
                conn.execute(text(
                    "ALTER TABLE agent_predictions ADD COLUMN IF NOT EXISTS scenarios JSONB NOT NULL "
                    "DEFAULT jsonb_build_array("
                    "jsonb_build_object('name', '历史记录：原始情景未归档', 'probability', 50, "
                    "'invalidation', '该历史记录未包含结构化失效条件'), "
                    "jsonb_build_object('name', '历史记录：需重新评估', 'probability', 50, "
                    "'invalidation', '生成新预测后替代该历史记录'))"
                ))
                conn.execute(text(
                    "ALTER TABLE agent_predictions ALTER COLUMN scenarios DROP DEFAULT"
                ))
                conn.execute(text(
                    "ALTER TABLE agent_predictions ADD COLUMN IF NOT EXISTS report_id TEXT NULL"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_agent_predictions_user_created "
                    "ON agent_predictions(user_id, created_at DESC)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_agent_predictions_owner_ticker "
                    "ON agent_predictions(user_id, symbol, created_at DESC)"
                ))
            self._schema_ready = True
        return True

    def create(self, prediction: AgentPrediction) -> AgentPrediction:
        self.ensure_schema()
        data = prediction.model_dump(exclude={"anchor", "risk_reward"}) | {
            "anchor_timeframe": prediction.anchor.timeframe,
            "anchor_time": prediction.anchor.time,
            "anchor_price": prediction.anchor.price,
            "scenarios": json.dumps(
                [item.model_dump(mode="json") for item in prediction.scenarios],
                ensure_ascii=False,
            ),
        }
        columns = (
            "id, user_id, run_id, symbol, agent, direction, confidence, thesis, "
            "anchor_timeframe, anchor_time, anchor_price, entry_type, entry, stop, target1, target2, "
            "invalidation_price, range_low, range_high, scenarios, report_id, status, created_at, updated_at"
        )
        values = ", ".join(
            "CAST(:scenarios AS jsonb)" if name.strip() == "scenarios" else f":{name.strip()}"
            for name in columns.split(",")
        )
        with self._engine.begin() as conn:
            conn.execute(text(f"INSERT INTO agent_predictions ({columns}) VALUES ({values})"), data)
        return prediction

    def get(self, prediction_id: str, *, user_id: str) -> AgentPrediction | None:
        normalized_user = str(user_id or "").strip()
        if not normalized_user or normalized_user == "public":
            return None
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text("SELECT * FROM agent_predictions WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
                    {"id": str(prediction_id), "user_id": normalized_user},
                ).mappings().first()
            if row is None:
                return None
            return _prediction_from_row(row)
        except PredictionStoreUnavailable:
            raise
        except Exception as exc:
            raise PredictionStoreUnavailable("prediction store read unavailable") from exc

    def get_latest(self, *, user_id: str, symbol: str) -> AgentPrediction | None:
        normalized_user = str(user_id or "").strip()
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_user or normalized_user == "public" or not normalized_symbol:
            return None
        try:
            with self._engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT * FROM agent_predictions WHERE user_id = :user_id AND symbol = :symbol "
                    "ORDER BY created_at DESC LIMIT 1"
                ), {"user_id": normalized_user, "symbol": normalized_symbol}).mappings().first()
            if row is None:
                return None
            return _prediction_from_row(row)
        except PredictionStoreUnavailable:
            raise
        except Exception as exc:
            raise PredictionStoreUnavailable("prediction store read unavailable") from exc

    def latest_predictions(
        self,
        *,
        ticker: str,
        user_id: str,
        limit_per_agent: int = 1,
    ) -> list[dict[str, Any]]:
        normalized_user = str(user_id or "").strip()
        normalized_symbol = str(ticker or "").strip().upper()
        safe_limit = max(1, min(20, int(limit_per_agent)))
        if not normalized_user or normalized_user == "public" or not normalized_symbol:
            return []
        self.ensure_schema()
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT * FROM ("
                "SELECT agent_predictions.*, ROW_NUMBER() OVER (PARTITION BY agent ORDER BY created_at DESC) AS agent_rank "
                "FROM agent_predictions WHERE user_id = :user_id AND symbol = :symbol"
                ") ranked WHERE agent_rank <= :limit_per_agent ORDER BY created_at DESC"
            ), {
                "user_id": normalized_user,
                "symbol": normalized_symbol,
                "limit_per_agent": safe_limit,
            }).mappings().all()
        return [
            _prediction_from_row(row).model_dump(mode="json", exclude={"risk_reward"})
            for row in rows
        ]

    def prediction_history(
        self,
        *,
        agent: str,
        ticker: str,
        user_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        normalized_user = str(user_id or "").strip()
        normalized_agent = str(agent or "").strip()
        normalized_symbol = str(ticker or "").strip().upper()
        safe_limit = max(1, min(50, int(limit)))
        if not normalized_user or normalized_user == "public" or not normalized_agent or not normalized_symbol:
            return []
        self.ensure_schema()
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT * FROM agent_predictions "
                "WHERE user_id = :user_id AND agent = :agent AND symbol = :symbol "
                "ORDER BY created_at DESC LIMIT :limit"
            ), {
                "user_id": normalized_user,
                "agent": normalized_agent,
                "symbol": normalized_symbol,
                "limit": safe_limit,
            }).mappings().all()
        return [
            _prediction_from_row(row).model_dump(mode="json", exclude={"risk_reward"})
            for row in rows
        ]

    def attach_report(self, prediction_id: str, *, user_id: str, report_id: str) -> bool:
        normalized_user = str(user_id or "").strip()
        normalized_report = str(report_id or "").strip()
        if not normalized_user or normalized_user == "public" or not normalized_report:
            return False
        self.ensure_schema()
        with self._engine.begin() as conn:
            result = conn.execute(text(
                "UPDATE agent_predictions SET report_id = :report_id, updated_at = now() "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ), {
                "report_id": normalized_report,
                "id": str(prediction_id),
                "user_id": normalized_user,
            })
        return bool(getattr(result, "rowcount", 0))


def _prediction_from_row(row: Any) -> AgentPrediction:
    payload = dict(row)
    payload.pop("agent_rank", None)
    if isinstance(payload.get("id"), UUID):
        payload["id"] = str(payload["id"])
    scenarios = payload.get("scenarios")
    if isinstance(scenarios, str):
        payload["scenarios"] = json.loads(scenarios)
    payload["anchor"] = {
        "timeframe": payload.pop("anchor_timeframe"),
        "time": payload.pop("anchor_time"),
        "price": payload.pop("anchor_price"),
    }
    return AgentPrediction.model_validate(payload)


def _resolve_dsn() -> str:
    return (
        os.getenv("AGENT_PREDICTION_POSTGRES_DSN")
        or os.getenv("RAG_V2_POSTGRES_DSN")
        or os.getenv("LANGGRAPH_CHECKPOINT_POSTGRES_DSN")
        or ""
    ).strip()


_store: AgentPredictionStore | UnavailableAgentPredictionStore | None = None
_store_lock = threading.Lock()


def get_agent_prediction_store() -> AgentPredictionStore | UnavailableAgentPredictionStore:
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is None:
            dsn = _resolve_dsn()
            try:
                _store = AgentPredictionStore(dsn=dsn) if dsn else UnavailableAgentPredictionStore()
            except Exception:
                _store = UnavailableAgentPredictionStore()
    return _store


def reset_agent_prediction_store_cache() -> None:
    global _store
    with _store_lock:
        _store = None


def record_prediction(
    *,
    prediction: AgentPrediction,
    user_id: str,
    run_id: str,
    report_id: str | None,
) -> UUID:
    """用服务端身份/运行信息归档已通过 submit_prediction 校验的观点。"""
    normalized_user = str(user_id or "").strip()
    normalized_run = str(run_id or "").strip()
    if not normalized_user or normalized_user == "public" or not normalized_run:
        raise ValueError("prediction 归档需要已鉴权用户和 run_id")
    trusted = prediction.model_copy(update={
        "user_id": normalized_user,
        "run_id": normalized_run,
        "report_id": str(report_id or "").strip() or None,
    })
    saved = get_agent_prediction_store().create(trusted)
    return UUID(str(saved.id))


def latest_predictions(*, ticker: str, user_id: str, limit_per_agent: int = 1) -> list[dict[str, Any]]:
    return get_agent_prediction_store().latest_predictions(
        ticker=ticker,
        user_id=user_id,
        limit_per_agent=limit_per_agent,
    )


def prediction_history(*, agent: str, ticker: str, user_id: str, limit: int = 5) -> list[dict[str, Any]]:
    return get_agent_prediction_store().prediction_history(
        agent=agent,
        ticker=ticker,
        user_id=user_id,
        limit=limit,
    )


__all__ = [
    "AgentPredictionStore", "PredictionStoreUnavailable", "UnavailableAgentPredictionStore",
    "get_agent_prediction_store", "latest_predictions", "prediction_history", "record_prediction",
    "reset_agent_prediction_store_cache",
]
