# -*- coding: utf-8 -*-
"""Prediction 的确定性 outcome 解析、PostgreSQL 归档与日更入口。"""
from __future__ import annotations

import logging
import threading
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from backend.services.database import create_core_engine, resolve_core_postgres_dsn

from backend.agents.prediction_contract import AgentPrediction, PredictionDraft
from backend.agents.prediction_submit import _crossed_entry


TERMINAL_OUTCOMES = frozenset({"hit_target", "hit_stop", "held_range", "broke_range", "invalidated"})
OUTCOME_ALGORITHM_VERSION = "prediction-outcome-v1"
MARKET_DATA_UNAVAILABLE = "market_data_unavailable"

logger = logging.getLogger(__name__)


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
    market_provider: str | None = None
    market_as_of: str | None = None
    algorithm_version: str = OUTCOME_ALGORITHM_VERSION


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
    market_provider: str | None = None,
    market_as_of: str | None = None,
    algorithm_version: str = OUTCOME_ALGORITHM_VERSION,
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
        "market_provider": str(market_provider or "").strip() or None,
        "market_as_of": str(market_as_of or "").strip() or None,
        "algorithm_version": str(algorithm_version or OUTCOME_ALGORITHM_VERSION),
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
            engine = create_core_engine(dsn=dsn)
        self._engine = engine

    def upsert(self, outcome: PredictionOutcome) -> PredictionOutcome:
        with self._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO agent_prediction_outcomes ("
                "prediction_id,user_id,status,resolved_at,entry_time,entry_price,pct_since_anchor,"
                "resolution_reason,evaluated_through,market_provider,market_as_of,algorithm_version,updated_at) VALUES ("
                "CAST(:prediction_id AS uuid),:user_id,:status,CAST(:resolved_at AS timestamptz),"
                "CAST(:entry_time AS timestamptz),:entry_price,:pct_since_anchor,:resolution_reason,"
                "CAST(:evaluated_through AS timestamptz),:market_provider,CAST(:market_as_of AS timestamptz),"
                ":algorithm_version,now()) "
                "ON CONFLICT(prediction_id,user_id) DO UPDATE SET "
                "status=CASE WHEN agent_prediction_outcomes.status IN "
                "('hit_target','hit_stop','held_range','broke_range','invalidated') "
                "THEN agent_prediction_outcomes.status WHEN excluded.status='data_pending' "
                "THEN excluded.status WHEN agent_prediction_outcomes.evaluated_through IS NULL "
                "OR excluded.evaluated_through >= agent_prediction_outcomes.evaluated_through "
                "THEN excluded.status ELSE agent_prediction_outcomes.status END,"
                "resolved_at=COALESCE(excluded.resolved_at,agent_prediction_outcomes.resolved_at),"
                "entry_time=COALESCE(excluded.entry_time,agent_prediction_outcomes.entry_time),"
                "entry_price=COALESCE(excluded.entry_price,agent_prediction_outcomes.entry_price),"
                "pct_since_anchor=CASE WHEN agent_prediction_outcomes.evaluated_through IS NULL "
                "OR excluded.evaluated_through >= agent_prediction_outcomes.evaluated_through "
                "THEN excluded.pct_since_anchor ELSE agent_prediction_outcomes.pct_since_anchor END,"
                "resolution_reason=CASE WHEN agent_prediction_outcomes.status IN "
                "('hit_target','hit_stop','held_range','broke_range','invalidated') "
                "THEN agent_prediction_outcomes.resolution_reason WHEN excluded.status='data_pending' "
                "THEN excluded.resolution_reason WHEN agent_prediction_outcomes.evaluated_through IS NULL "
                "OR excluded.evaluated_through >= agent_prediction_outcomes.evaluated_through "
                "THEN excluded.resolution_reason ELSE agent_prediction_outcomes.resolution_reason END,"
                "evaluated_through=CASE WHEN excluded.evaluated_through IS NULL THEN agent_prediction_outcomes.evaluated_through "
                "WHEN agent_prediction_outcomes.evaluated_through IS NULL THEN excluded.evaluated_through "
                "ELSE GREATEST(agent_prediction_outcomes.evaluated_through,excluded.evaluated_through) END,"
                "market_provider=excluded.market_provider,market_as_of=excluded.market_as_of,"
                "algorithm_version=excluded.algorithm_version,updated_at=now()"
            ), outcome.model_dump())
        return outcome

    def pending_predictions(
        self,
        *,
        user_id: str | None = None,
        prediction_id: str | None = None,
        limit: int = 500,
    ) -> list[AgentPrediction]:
        filters = [
            "(o.status IS NULL OR o.status NOT IN "
            "('hit_target','hit_stop','held_range','broke_range','invalidated'))"
        ]
        params: dict[str, Any] = {"limit": max(1, min(5000, int(limit)))}
        if user_id is not None:
            normalized_user = str(user_id or "").strip()
            if not normalized_user or normalized_user == "public":
                return []
            filters.append("p.user_id=:user_id")
            params["user_id"] = normalized_user
        if prediction_id is not None:
            filters.append("p.id=CAST(:prediction_id AS uuid)")
            params["prediction_id"] = str(prediction_id)
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT p.* FROM agent_predictions p "
                "LEFT JOIN agent_prediction_outcomes o "
                "ON o.prediction_id=p.id AND o.user_id=p.user_id "
                "WHERE " + " AND ".join(filters) + " "
                "ORDER BY p.created_at ASC LIMIT :limit"
            ), params).mappings().all()
        from backend.services.agent_prediction_store import _prediction_from_row

        return [_prediction_from_row(row) for row in rows]

    def track_record(self, *, user_id: str, agent: str, days: int = 90) -> dict[str, Any]:
        normalized_user = str(user_id or "").strip()
        if not normalized_user or normalized_user == "public":
            return _empty_track_record()
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
    return resolve_core_postgres_dsn(required=False)


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


def _data_pending_outcome(
    prediction: AgentPrediction,
    *,
    market: Mapping[str, Any] | None = None,
    reason: str = MARKET_DATA_UNAVAILABLE,
) -> PredictionOutcome:
    payload = market if isinstance(market, Mapping) else {}
    return PredictionOutcome(
        prediction_id=prediction.id,
        user_id=prediction.user_id,
        status="data_pending",
        resolution_reason=str(reason or MARKET_DATA_UNAVAILABLE)[:200],
        market_provider=str(payload.get("provider") or "").strip() or None,
        market_as_of=str(payload.get("as_of") or "").strip() or None,
        algorithm_version=OUTCOME_ALGORITHM_VERSION,
    )


def run_prediction_outcome_cycle(
    *,
    user_id: str | None = None,
    prediction_id: str | None = None,
    limit: int = 500,
    store: PredictionOutcomeStore | None = None,
    market_gateway: Any | None = None,
) -> int:
    """日更与受保护补跑入口；只用可信 K 线，缺数据明确写 data_pending。"""
    from backend.services.market_data_gateway import get_market_data_gateway

    outcome_store = store or get_prediction_outcome_store()
    gateway = market_gateway or get_market_data_gateway()
    evaluated = 0
    predictions = outcome_store.pending_predictions(
        user_id=user_id,
        prediction_id=prediction_id,
        limit=limit,
    )
    for prediction in predictions:
        raw: Mapping[str, Any] | None = None
        try:
            result = gateway.get_kline(prediction.symbol, period="1y", interval="1d")
            raw = result if isinstance(result, Mapping) else None
            if (
                raw is None
                or raw.get("quality") != "trusted"
                or raw.get("error_code")
                or not raw.get("provider")
                or not raw.get("as_of")
            ):
                reason = str((raw or {}).get("error_code") or MARKET_DATA_UNAVAILABLE)
                outcome_store.upsert(_data_pending_outcome(prediction, market=raw, reason=reason))
                evaluated += 1
                continue
            bars = raw.get("kline_data")
            if not isinstance(bars, list) or not bars:
                outcome_store.upsert(_data_pending_outcome(prediction, market=raw))
                evaluated += 1
                continue
            outcome = resolve_prediction_outcome(
                prediction,
                bars,
                market_provider=str(raw["provider"]),
                market_as_of=str(raw["as_of"]),
                algorithm_version=OUTCOME_ALGORITHM_VERSION,
            )
            outcome_store.upsert(outcome)
            evaluated += 1
        except Exception as exc:
            logger.warning(
                "prediction outcome market evaluation failed prediction_id=%s error_type=%s",
                prediction.id,
                type(exc).__name__,
            )
            try:
                outcome_store.upsert(_data_pending_outcome(prediction, market=raw))
                evaluated += 1
            except Exception:
                logger.exception(
                    "prediction outcome data_pending write failed prediction_id=%s",
                    prediction.id,
                )
    return evaluated


__all__ = [
    "MARKET_DATA_UNAVAILABLE", "OUTCOME_ALGORITHM_VERSION", "PredictionOutcome",
    "PredictionOutcomeStore", "PredictionOutcomeStoreUnavailable",
    "TERMINAL_OUTCOMES", "get_prediction_outcome_store", "resolve_prediction_outcome",
    "run_prediction_outcome_cycle", "summarize_track_record",
]
