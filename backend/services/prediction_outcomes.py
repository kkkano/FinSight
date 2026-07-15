# -*- coding: utf-8 -*-
"""Prediction 的确定性 outcome 解析、PostgreSQL 归档与日更入口。"""
from __future__ import annotations

import os
import threading
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, text

from backend.agents.prediction_contract import AgentPrediction, PredictionDraft
from backend.agents.prediction_submit import _crossed_entry


TERMINAL_OUTCOMES = frozenset({"hit_target", "hit_stop", "held_range", "broke_range", "invalidated"})


class PredictionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_id: str
    user_id: str
    status: str
    resolved_at: str | None = None
    entry_time: str | None = None
    entry_price: float | None = None
    pct_since_anchor: float | None = None
    resolution_reason: str | None = None
    evaluated_through: str | None = None


def _number(bar: Mapping[str, Any], key: str) -> float:
    value = float(bar[key])
    if value <= 0:
        raise ValueError(f"行情 bar 的 {key} 必须为正数")
    return value


def _future_bars(prediction: PredictionDraft, bars: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in bars:
        if not isinstance(raw, Mapping):
            continue
        time_value = str(raw.get("time") or "").strip()
        if not time_value or time_value <= prediction.anchor.time:
            continue
        try:
            normalized.append({
                "time": time_value,
                "open": _number(raw, "open"),
                "high": _number(raw, "high"),
                "low": _number(raw, "low"),
                "close": _number(raw, "close"),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(normalized, key=lambda item: item["time"])


def resolve_prediction_outcome(
    prediction: AgentPrediction | PredictionDraft,
    bars: Iterable[Mapping[str, Any]],
    *,
    prediction_id: str | None = None,
    user_id: str | None = None,
) -> PredictionOutcome:
    """只读可信 OHLC，零 LLM；相同输入始终得到相同结果。"""
    future = _future_bars(prediction, bars)
    last = future[-1] if future else None
    pct = (
        round((float(last["close"]) / float(prediction.anchor.price) - 1.0) * 100.0, 8)
        if last is not None else None
    )
    base = {
        "prediction_id": str(prediction_id or getattr(prediction, "id", "") or "unknown"),
        "user_id": str(user_id or getattr(prediction, "user_id", "") or "unknown"),
        "pct_since_anchor": pct,
        "evaluated_through": str(last["time"]) if last else None,
    }

    if prediction.direction == "neutral":
        assert prediction.range_low is not None and prediction.range_high is not None
        for bar in future[:10]:
            close = float(bar["close"])
            if close < prediction.range_low or close > prediction.range_high:
                return PredictionOutcome(
                    **base,
                    status="broke_range",
                    resolved_at=str(bar["time"]),
                    resolution_reason="close_outside_range",
                )
        if len(future) >= 10:
            tenth = future[9]
            return PredictionOutcome(
                **{**base, "pct_since_anchor": round(
                    (float(tenth["close"]) / float(prediction.anchor.price) - 1.0) * 100.0, 8
                ), "evaluated_through": str(tenth["time"])},
                status="held_range",
                resolved_at=str(tenth["time"]),
                resolution_reason="ten_trading_days_held",
            )
        return PredictionOutcome(**base, status="open" if future else "waiting")

    assert prediction.invalidation_price is not None
    assert prediction.stop is not None and prediction.target1 is not None
    entered = False
    entry_time: str | None = None
    entry_price: float | None = None
    bars_after_entry = 0
    for bar in future:
        high, low = float(bar["high"]), float(bar["low"])
        time_value = str(bar["time"])
        if not entered:
            invalidated = (
                low <= prediction.invalidation_price
                if prediction.direction == "long"
                else high >= prediction.invalidation_price
            )
            touched, fill = _crossed_entry(prediction, bar)
            if invalidated:
                return PredictionOutcome(
                    **base,
                    status="invalidated",
                    resolved_at=time_value,
                    resolution_reason="invalidation_before_entry",
                )
            if not touched:
                continue
            entered = True
            entry_time = time_value
            entry_price = fill
        else:
            bars_after_entry += 1

        hit_stop = low <= prediction.stop if prediction.direction == "long" else high >= prediction.stop
        hit_target = high >= prediction.target1 if prediction.direction == "long" else low <= prediction.target1
        if hit_stop:
            return PredictionOutcome(
                **base,
                status="hit_stop",
                resolved_at=time_value,
                entry_time=entry_time,
                entry_price=entry_price,
                resolution_reason="same_bar_conservative" if hit_target else "stop_crossed",
            )
        if hit_target:
            return PredictionOutcome(
                **base,
                status="hit_target",
                resolved_at=time_value,
                entry_time=entry_time,
                entry_price=entry_price,
                resolution_reason="target1_crossed",
            )

    if not entered:
        return PredictionOutcome(**base, status="waiting")
    return PredictionOutcome(
        **base,
        status="open" if bars_after_entry else "triggered",
        entry_time=entry_time,
        entry_price=entry_price,
    )


class PredictionOutcomeStoreUnavailable(RuntimeError):
    pass


class PredictionOutcomeStore:
    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        if engine is None:
            normalized = str(dsn or "").strip()
            if not normalized.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("prediction outcome store 只允许 PostgreSQL DSN")
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
            from backend.services.agent_prediction_store import get_agent_prediction_store

            get_agent_prediction_store().ensure_schema()
            with self._engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS agent_prediction_outcomes ("
                    "prediction_id UUID NOT NULL, user_id TEXT NOT NULL, status TEXT NOT NULL, "
                    "resolved_at TIMESTAMPTZ NULL, entry_time TIMESTAMPTZ NULL, entry_price DOUBLE PRECISION NULL, "
                    "pct_since_anchor DOUBLE PRECISION NULL, resolution_reason TEXT NULL, "
                    "evaluated_through TIMESTAMPTZ NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                    "PRIMARY KEY(prediction_id, user_id), "
                    "FOREIGN KEY(prediction_id, user_id) REFERENCES agent_predictions(id, user_id))"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_agent_prediction_outcomes_owner_status "
                    "ON agent_prediction_outcomes(user_id, status, updated_at DESC)"
                ))
            self._schema_ready = True
        return True

    def upsert(self, outcome: PredictionOutcome) -> PredictionOutcome:
        self.ensure_schema()
        with self._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO agent_prediction_outcomes ("
                "prediction_id,user_id,status,resolved_at,entry_time,entry_price,pct_since_anchor,"
                "resolution_reason,evaluated_through,updated_at) VALUES ("
                "CAST(:prediction_id AS uuid),:user_id,:status,CAST(:resolved_at AS timestamptz),"
                "CAST(:entry_time AS timestamptz),:entry_price,:pct_since_anchor,:resolution_reason,"
                "CAST(:evaluated_through AS timestamptz),now()) "
                "ON CONFLICT(prediction_id,user_id) DO UPDATE SET "
                "status=CASE WHEN agent_prediction_outcomes.evaluated_through IS NULL "
                "OR excluded.evaluated_through >= agent_prediction_outcomes.evaluated_through "
                "THEN excluded.status ELSE agent_prediction_outcomes.status END,"
                "resolved_at=COALESCE(excluded.resolved_at,agent_prediction_outcomes.resolved_at),"
                "entry_time=COALESCE(excluded.entry_time,agent_prediction_outcomes.entry_time),"
                "entry_price=COALESCE(excluded.entry_price,agent_prediction_outcomes.entry_price),"
                "pct_since_anchor=CASE WHEN agent_prediction_outcomes.evaluated_through IS NULL "
                "OR excluded.evaluated_through >= agent_prediction_outcomes.evaluated_through "
                "THEN excluded.pct_since_anchor ELSE agent_prediction_outcomes.pct_since_anchor END,"
                "resolution_reason=COALESCE(excluded.resolution_reason,agent_prediction_outcomes.resolution_reason),"
                "evaluated_through=CASE WHEN excluded.evaluated_through IS NULL THEN agent_prediction_outcomes.evaluated_through "
                "WHEN agent_prediction_outcomes.evaluated_through IS NULL THEN excluded.evaluated_through "
                "ELSE GREATEST(agent_prediction_outcomes.evaluated_through,excluded.evaluated_through) END,updated_at=now()"
            ), outcome.model_dump())
        return outcome

    def pending_predictions(self, *, limit: int = 500) -> list[AgentPrediction]:
        self.ensure_schema()
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT p.* FROM agent_predictions p "
                "LEFT JOIN agent_prediction_outcomes o "
                "ON o.prediction_id=p.id AND o.user_id=p.user_id "
                "WHERE o.status IS NULL OR o.status NOT IN "
                "('hit_target','hit_stop','held_range','broke_range','invalidated') "
                "ORDER BY p.created_at ASC LIMIT :limit"
            ), {"limit": max(1, min(5000, int(limit)))}).mappings().all()
        from backend.services.agent_prediction_store import _prediction_from_row

        return [_prediction_from_row(row) for row in rows]

    def track_record(self, *, user_id: str, agent: str, days: int = 90) -> dict[str, Any]:
        normalized_user = str(user_id or "").strip()
        if not normalized_user or normalized_user == "public":
            return _empty_track_record()
        self.ensure_schema()
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT p.direction,o.status,COUNT(*) AS count,MAX(o.updated_at) AS latest "
                "FROM agent_prediction_outcomes o JOIN agent_predictions p "
                "ON p.id=o.prediction_id AND p.user_id=o.user_id "
                "WHERE o.user_id=:user_id AND p.agent=:agent "
                "AND p.created_at >= now() - (:days * interval '1 day') "
                "GROUP BY p.direction,o.status"
            ), {"user_id": normalized_user, "agent": str(agent), "days": max(1, int(days))}).mappings().all()
        return summarize_track_record(rows)


def _empty_track_record() -> dict[str, Any]:
    return {
        "hits": 0, "misses": 0, "invalidated": 0, "sample_count": 0,
        "hit_rate": None, "sample_state": "样本不足", "latest_evaluated_at": None,
        "by_direction": {},
    }


def summarize_track_record(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    result = _empty_track_record()
    latest_values: list[str] = []
    for row in rows:
        direction = str(row.get("direction") or "unknown")
        status = str(row.get("status") or "")
        count = int(row.get("count") or 0)
        bucket = result["by_direction"].setdefault(
            direction, {"hits": 0, "misses": 0, "invalidated": 0, "sample_count": 0, "hit_rate": None}
        )
        if status in {"hit_target", "held_range"}:
            result["hits"] += count
            bucket["hits"] += count
        elif status in {"hit_stop", "broke_range"}:
            result["misses"] += count
            bucket["misses"] += count
        elif status == "invalidated":
            result["invalidated"] += count
            bucket["invalidated"] += count
        latest = row.get("latest")
        if latest:
            latest_values.append(str(latest))
    result["sample_count"] = result["hits"] + result["misses"]
    if result["sample_count"] >= 5:
        result["hit_rate"] = round(result["hits"] / result["sample_count"], 4)
        result["sample_state"] = "sufficient"
    for bucket in result["by_direction"].values():
        bucket["sample_count"] = bucket["hits"] + bucket["misses"]
        if bucket["sample_count"] >= 5:
            bucket["hit_rate"] = round(bucket["hits"] / bucket["sample_count"], 4)
    result["latest_evaluated_at"] = max(latest_values) if latest_values else None
    return result


def _resolve_dsn() -> str:
    return (
        os.getenv("AGENT_PREDICTION_POSTGRES_DSN")
        or os.getenv("RAG_V2_POSTGRES_DSN")
        or os.getenv("LANGGRAPH_CHECKPOINT_POSTGRES_DSN")
        or ""
    ).strip()


_store: PredictionOutcomeStore | None = None
_store_lock = threading.Lock()


def get_prediction_outcome_store() -> PredictionOutcomeStore:
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is None:
            dsn = _resolve_dsn()
            if not dsn:
                raise PredictionOutcomeStoreUnavailable("prediction outcome postgres unavailable")
            _store = PredictionOutcomeStore(dsn=dsn)
    return _store


def run_prediction_outcome_cycle() -> int:
    """日更调度入口；逐条读取真实 K 线，缺数据不判 miss。"""
    from backend.tools import get_stock_historical_data

    store = get_prediction_outcome_store()
    evaluated = 0
    for prediction in store.pending_predictions(limit=500):
        try:
            raw = get_stock_historical_data(prediction.symbol, period="1y", interval="1d")
            if not isinstance(raw, dict) or raw.get("quality") != "trusted" or raw.get("error_code"):
                continue
            if not raw.get("provider") or not raw.get("as_of"):
                continue
            bars = raw.get("kline_data") if isinstance(raw, dict) else None
            if not isinstance(bars, list) or not bars:
                continue
            outcome = resolve_prediction_outcome(prediction, bars)
            store.upsert(outcome)
            evaluated += 1
        except Exception:
            continue
    return evaluated


__all__ = [
    "PredictionOutcome", "PredictionOutcomeStore", "PredictionOutcomeStoreUnavailable",
    "TERMINAL_OUTCOMES", "get_prediction_outcome_store", "resolve_prediction_outcome",
    "run_prediction_outcome_cycle", "summarize_track_record",
]
