# -*- coding: utf-8 -*-
"""Agent prediction 的 PostgreSQL-only 租户隔离存储。"""
from __future__ import annotations

import os
import threading
from typing import Any

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
                    "range_low DOUBLE PRECISION NULL, range_high DOUBLE PRECISION NULL, status TEXT NOT NULL, "
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
                    "CREATE INDEX IF NOT EXISTS idx_agent_predictions_user_created "
                    "ON agent_predictions(user_id, created_at DESC)"
                ))
            self._schema_ready = True
        return True

    def create(self, prediction: AgentPrediction) -> AgentPrediction:
        self.ensure_schema()
        data = prediction.model_dump(exclude={"anchor", "risk_reward"}) | {
            "anchor_timeframe": prediction.anchor.timeframe,
            "anchor_time": prediction.anchor.time,
            "anchor_price": prediction.anchor.price,
        }
        columns = (
            "id, user_id, run_id, symbol, agent, direction, confidence, thesis, "
            "anchor_timeframe, anchor_time, anchor_price, entry_type, entry, stop, target1, target2, "
            "invalidation_price, range_low, range_high, status, created_at, updated_at"
        )
        values = ", ".join(f":{name.strip()}" for name in columns.split(","))
        with self._engine.begin() as conn:
            conn.execute(text(f"INSERT INTO agent_predictions ({columns}) VALUES ({values})"), data)
        return prediction

    def get(self, prediction_id: str, *, user_id: str) -> AgentPrediction | None:
        normalized_user = str(user_id or "").strip()
        if not normalized_user or normalized_user == "public":
            return None
        self.ensure_schema()
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM agent_predictions WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
                {"id": str(prediction_id), "user_id": normalized_user},
            ).mappings().first()
        if row is None:
            return None
        payload = dict(row)
        payload["anchor"] = {
            "timeframe": payload.pop("anchor_timeframe"),
            "time": payload.pop("anchor_time"),
            "price": payload.pop("anchor_price"),
        }
        return AgentPrediction.model_validate(payload)

    def get_latest(self, *, user_id: str, symbol: str) -> AgentPrediction | None:
        normalized_user = str(user_id or "").strip()
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_user or normalized_user == "public" or not normalized_symbol:
            return None
        self.ensure_schema()
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT * FROM agent_predictions WHERE user_id = :user_id AND symbol = :symbol "
                "ORDER BY created_at DESC LIMIT 1"
            ), {"user_id": normalized_user, "symbol": normalized_symbol}).mappings().first()
        if row is None:
            return None
        payload = dict(row)
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


__all__ = [
    "AgentPredictionStore", "PredictionStoreUnavailable", "UnavailableAgentPredictionStore",
    "get_agent_prediction_store", "reset_agent_prediction_store_cache",
]
