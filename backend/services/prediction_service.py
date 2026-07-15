# -*- coding: utf-8 -*-
"""显式 Prediction run 状态机、分析执行与 PostgreSQL 原子归档。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Awaitable, Callable, Collection, Literal, Mapping
from uuid import UUID, uuid4

import pandas as pd
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from backend.agents.prediction_contract import AgentPrediction
from backend.agents.prediction_submit import (
    build_prediction,
    prediction_json_from_llm_content,
)
from backend.config.ticker_mapping import normalize_ticker
from backend.services.agent_prediction_store import _prediction_from_row, insert_prediction
from backend.services.database import create_core_engine, resolve_core_postgres_dsn
from backend.services.llm_retry import (
    LLMCallContext,
    ainvoke_configured_llm,
    classify_llm_error,
)
from backend.services.llm_usage import estimate_cost
from backend.services.market_data_gateway import get_market_data_gateway


logger = logging.getLogger(__name__)

PredictionRunStatus = Literal[
    "queued", "running", "succeeded", "unavailable", "failed", "cancelled",
]

PREDICTION_PROMPT_VERSION = "prediction-analyst-v1"
PREDICTION_AGENT = "prediction_analyst"
PREDICTION_OPERATION = "technical"
PREDICTION_MIN_BARS = 60
PREDICTION_MAX_PROVIDER_ATTEMPTS = 2
PREDICTION_HARD_TIMEOUT_SECONDS = 75.0
PREDICTION_LLM_ATTEMPT_TIMEOUT_SECONDS = 30.0
PREDICTION_NEWS_TIMEOUT_SECONDS = 5.0
PREDICTION_DEFAULT_LLM_ENDPOINT_NAMES = ("openai-compatible-primary",)

MARKET_DATA_UNAVAILABLE = "market_data_unavailable"
PREDICTION_VALIDATION_FAILED = "prediction_validation_failed"
STORE_UNAVAILABLE = "store_unavailable"

_SYMBOL_PATTERN = re.compile(
    r"^(?=.{1,32}$)(?:\^[A-Z0-9][A-Z0-9.-]*|[A-Z0-9][A-Z0-9.-]*(?:=[A-Z])?)$",
    flags=re.ASCII,
)


class PredictionRun(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: str
    symbol: str
    timeframe: str
    prompt_version: str
    status: PredictionRunStatus
    anchor_time: str | None = None
    anchor_price: float | None = None
    market_provider: str | None = None
    market_as_of: datetime | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    prediction_id: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    provider_attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PredictionServiceUnavailable(RuntimeError):
    pass


class MarketDataUnavailable(RuntimeError):
    pass


class PredictionValidationError(RuntimeError):
    pass


def _prediction_llm_endpoint_names(value: str | Collection[str] | None) -> tuple[str, ...]:
    raw: Collection[str]
    if value is None:
        raw = str(
            os.getenv(
                "PREDICTION_LLM_ENDPOINT_NAMES",
                ",".join(PREDICTION_DEFAULT_LLM_ENDPOINT_NAMES),
            )
        ).split(",")
    elif isinstance(value, str):
        raw = value.split(",")
    else:
        raw = value
    names = tuple(dict.fromkeys(str(name or "").strip() for name in raw))
    names = tuple(name for name in names if name)
    if not names:
        raise ValueError("prediction LLM endpoint names must not be empty")
    return names


def normalize_prediction_symbol(value: str) -> str:
    normalized = normalize_ticker(str(value or "").strip())
    if not _SYMBOL_PATTERN.fullmatch(normalized):
        raise ValueError("invalid prediction symbol")
    return normalized


def _run_from_row(row: Mapping[str, Any]) -> PredictionRun:
    payload = dict(row)
    for key in ("id", "prediction_id"):
        if isinstance(payload.get(key), UUID):
            payload[key] = str(payload[key])
    return PredictionRun.model_validate(payload)


def _safe_failure_detail(value: Any) -> str:
    message = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    message = re.sub(r"(?i)(api[_ -]?key|authorization|bearer|token)\s*[:=]\s*\S+", r"\1=[redacted]", message)
    return message[:400] or "prediction run failed"


def _attempt_totals(attempts: list[Mapping[str, Any]]) -> dict[str, Any]:
    bounded = attempts[:PREDICTION_MAX_PROVIDER_ATTEMPTS]
    prompt = sum(max(0, int(item.get("prompt_tokens") or 0)) for item in bounded)
    completion = sum(max(0, int(item.get("completion_tokens") or 0)) for item in bounded)
    last = bounded[-1] if bounded else {}
    success = next((item for item in reversed(bounded) if item.get("status") == "success"), last)
    return {
        "provider_attempts": len(bounded),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "llm_provider": str(success.get("provider") or "").strip() or None,
        "llm_model": str(success.get("model") or "").strip() or None,
    }


class PredictionRunStore:
    """Prediction run 与规范读取模型的 PostgreSQL repository。"""

    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        self._engine = engine if engine is not None else create_core_engine(dsn=dsn)

    def create_or_get_active(
        self,
        *,
        user_id: str,
        symbol: str,
        timeframe: str,
        prompt_version: str,
    ) -> tuple[PredictionRun, bool]:
        run_id = str(uuid4())
        params = {
            "id": run_id,
            "user_id": user_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "prompt_version": prompt_version,
        }
        with self._engine.begin() as conn:
            row = conn.execute(text(
                "INSERT INTO prediction_runs(id,user_id,symbol,timeframe,prompt_version,status) "
                "VALUES(CAST(:id AS uuid),:user_id,:symbol,:timeframe,:prompt_version,'queued') "
                "ON CONFLICT(user_id,symbol,timeframe,prompt_version) "
                "WHERE status IN ('queued','running') DO NOTHING RETURNING *"
            ), params).mappings().first()
            if row is not None:
                return _run_from_row(row), True
            row = conn.execute(text(
                "SELECT * FROM prediction_runs WHERE user_id=:user_id AND symbol=:symbol "
                "AND timeframe=:timeframe AND prompt_version=:prompt_version "
                "AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1"
            ), params).mappings().first()
        if row is None:
            raise PredictionServiceUnavailable("active prediction run could not be resolved")
        return _run_from_row(row), False

    def get_run(self, run_id: str, *, user_id: str) -> PredictionRun | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT * FROM prediction_runs WHERE id=CAST(:id AS uuid) AND user_id=:user_id"
            ), {"id": run_id, "user_id": user_id}).mappings().first()
        return _run_from_row(row) if row is not None else None

    def claim(self, run_id: str) -> PredictionRun | None:
        with self._engine.begin() as conn:
            row = conn.execute(text(
                "UPDATE prediction_runs SET status='running',started_at=COALESCE(started_at,now()),"
                "updated_at=now(),failure_code=NULL,failure_detail=NULL "
                "WHERE id=CAST(:id AS uuid) AND (status='queued' OR "
                "(status='running' AND updated_at < now() - interval '90 seconds')) RETURNING *"
            ), {"id": run_id}).mappings().first()
        return _run_from_row(row) if row is not None else None

    def recoverable_run_ids(self, *, limit: int = 100) -> list[str]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id FROM prediction_runs WHERE status='queued' OR "
                "(status='running' AND updated_at < now() - interval '90 seconds') "
                "ORDER BY created_at ASC LIMIT :limit"
            ), {"limit": max(1, min(1000, int(limit)))}).scalars().all()
        return [str(value) for value in rows]

    def set_market_context(self, run: PredictionRun, market: Mapping[str, Any]) -> None:
        bars = market.get("kline_data")
        anchor = bars[-1] if isinstance(bars, list) and bars else {}
        with self._engine.begin() as conn:
            conn.execute(text(
                "UPDATE prediction_runs SET anchor_time=:anchor_time,anchor_price=:anchor_price,"
                "market_provider=:provider,market_as_of=CAST(:as_of AS timestamptz),updated_at=now() "
                "WHERE id=CAST(:id AS uuid) AND user_id=:user_id AND status='running'"
            ), {
                "id": run.id,
                "user_id": run.user_id,
                "anchor_time": str(anchor.get("time") or ""),
                "anchor_price": float(anchor.get("close")),
                "provider": str(market.get("provider") or ""),
                "as_of": str(market.get("as_of") or ""),
            })

    def get_prediction(self, prediction_id: str, *, user_id: str) -> AgentPrediction | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT * FROM agent_predictions WHERE id=CAST(:id AS uuid) AND user_id=:user_id"
            ), {"id": prediction_id, "user_id": user_id}).mappings().first()
        return _prediction_from_row(row) if row is not None else None

    def get_latest_prediction(self, *, user_id: str, symbol: str) -> AgentPrediction | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT * FROM agent_predictions WHERE user_id=:user_id AND symbol=:symbol "
                "ORDER BY created_at DESC LIMIT 1"
            ), {"user_id": user_id, "symbol": symbol}).mappings().first()
        return _prediction_from_row(row) if row is not None else None

    def get_outcome(self, prediction_id: str, *, user_id: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT prediction_id,user_id,status,resolved_at,entry_time,entry_price,"
                "pct_since_anchor,resolution_reason,evaluated_through,market_provider,"
                "market_as_of,algorithm_version FROM agent_prediction_outcomes "
                "WHERE prediction_id=CAST(:prediction_id AS uuid) AND user_id=:user_id"
            ), {"prediction_id": prediction_id, "user_id": user_id}).mappings().first()
        return dict(row) if row is not None else None

    def get_by_anchor(
        self,
        *,
        user_id: str,
        symbol: str,
        timeframe: str,
        anchor_time: str,
        prompt_version: str,
    ) -> AgentPrediction | None:
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT * FROM agent_predictions WHERE user_id=:user_id AND symbol=:symbol "
                "AND anchor_timeframe=:timeframe AND anchor_time=:anchor_time "
                "AND prompt_version=:prompt_version ORDER BY created_at DESC LIMIT 1"
            ), {
                "user_id": user_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "anchor_time": anchor_time,
                "prompt_version": prompt_version,
            }).mappings().first()
        return _prediction_from_row(row) if row is not None else None

    def complete_reused(
        self,
        run: PredictionRun,
        prediction: AgentPrediction,
        *,
        latency_ms: int,
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO agent_run_archive(run_id,user_id,agent,layer,prediction_id,model,"
                "prompt_tokens,completion_tokens,total_tokens,cost_usd,call_count,failed_call_count,"
                "duration_ms,status,provider,prompt_version) VALUES("
                ":run_id,:user_id,:agent,'prediction',CAST(:prediction_id AS uuid),'none',"
                "0,0,0,0,0,0,:duration_ms,'reused',NULL,:prompt_version) "
                "ON CONFLICT(run_id,user_id,agent,layer,model) DO NOTHING"
            ), {
                "run_id": run.id,
                "user_id": run.user_id,
                "agent": PREDICTION_AGENT,
                "prediction_id": prediction.id,
                "duration_ms": max(0, int(latency_ms)),
                "prompt_version": run.prompt_version,
            })
            conn.execute(text(
                "UPDATE prediction_runs SET status='succeeded',prediction_id=CAST(:prediction_id AS uuid),"
                "llm_provider=NULL,llm_model=NULL,provider_attempts=0,prompt_tokens=0,completion_tokens=0,"
                "total_tokens=0,latency_ms=:latency_ms,completed_at=now(),updated_at=now() "
                "WHERE id=CAST(:id AS uuid) AND user_id=:user_id AND status='running'"
            ), {
                "id": run.id,
                "user_id": run.user_id,
                "prediction_id": prediction.id,
                "latency_ms": max(0, int(latency_ms)),
            })

    def complete_success(
        self,
        run: PredictionRun,
        prediction: AgentPrediction,
        *,
        attempts: list[Mapping[str, Any]],
        latency_ms: int,
    ) -> None:
        totals = _attempt_totals(attempts)
        with self._engine.begin() as conn:
            insert_prediction(conn, prediction)
            self._insert_usage(conn, run=run, prediction_id=prediction.id, attempts=attempts)
            self._insert_archive(
                conn,
                run=run,
                prediction_id=prediction.id,
                attempts=attempts,
                status="succeeded",
                failure_code=None,
            )
            conn.execute(text(
                "UPDATE prediction_runs SET status='succeeded',prediction_id=CAST(:prediction_id AS uuid),"
                "llm_provider=:llm_provider,llm_model=:llm_model,provider_attempts=:provider_attempts,"
                "prompt_tokens=:prompt_tokens,completion_tokens=:completion_tokens,total_tokens=:total_tokens,"
                "latency_ms=:latency_ms,completed_at=now(),updated_at=now() "
                "WHERE id=CAST(:id AS uuid) AND user_id=:user_id AND status='running'"
            ), {
                **totals,
                "id": run.id,
                "user_id": run.user_id,
                "prediction_id": prediction.id,
                "latency_ms": max(0, int(latency_ms)),
            })

    def complete_failure(
        self,
        run: PredictionRun,
        *,
        status: Literal["unavailable", "failed", "cancelled"],
        failure_code: str,
        failure_detail: str,
        attempts: list[Mapping[str, Any]],
        latency_ms: int,
    ) -> None:
        totals = _attempt_totals(attempts)
        with self._engine.begin() as conn:
            self._insert_usage(conn, run=run, prediction_id=None, attempts=attempts)
            if attempts:
                self._insert_archive(
                    conn,
                    run=run,
                    prediction_id=None,
                    attempts=attempts,
                    status=status,
                    failure_code=failure_code,
                )
            conn.execute(text(
                "UPDATE prediction_runs SET status=:status,failure_code=:failure_code,"
                "failure_detail=:failure_detail,llm_provider=:llm_provider,llm_model=:llm_model,"
                "provider_attempts=:provider_attempts,prompt_tokens=:prompt_tokens,"
                "completion_tokens=:completion_tokens,total_tokens=:total_tokens,latency_ms=:latency_ms,"
                "completed_at=now(),updated_at=now() WHERE id=CAST(:id AS uuid) "
                "AND user_id=:user_id AND status IN ('queued','running')"
            ), {
                **totals,
                "id": run.id,
                "user_id": run.user_id,
                "status": status,
                "failure_code": failure_code,
                "failure_detail": _safe_failure_detail(failure_detail),
                "latency_ms": max(0, int(latency_ms)),
            })

    def _insert_usage(
        self,
        conn: Any,
        *,
        run: PredictionRun,
        prediction_id: str | None,
        attempts: list[Mapping[str, Any]],
    ) -> None:
        for raw in attempts[:PREDICTION_MAX_PROVIDER_ATTEMPTS]:
            model = str(raw.get("model") or "unknown")
            prompt = max(0, int(raw.get("prompt_tokens") or 0))
            completion = max(0, int(raw.get("completion_tokens") or 0))
            conn.execute(text(
                "INSERT INTO llm_usage(run_id,user_id,logical_role,attempt,provider,model,prompt_version,"
                "prediction_id,prompt_tokens,completion_tokens,total_tokens,cost_usd,latency_ms,status,error_code) "
                "VALUES(:run_id,:user_id,:logical_role,:attempt,:provider,:model,:prompt_version,"
                "CAST(:prediction_id AS uuid),:prompt_tokens,:completion_tokens,:total_tokens,:cost_usd,"
                ":latency_ms,:status,:error_code) ON CONFLICT(run_id,user_id,logical_role,attempt) DO NOTHING"
            ), {
                "run_id": run.id,
                "user_id": run.user_id,
                "logical_role": PREDICTION_AGENT,
                "attempt": max(1, min(2, int(raw.get("attempt") or 1))),
                "provider": str(raw.get("provider") or raw.get("endpoint_name") or "unknown"),
                "model": model,
                "prompt_version": run.prompt_version,
                "prediction_id": prediction_id,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
                "cost_usd": estimate_cost({model: {"prompt": prompt, "completion": completion}}),
                "latency_ms": max(0, int(raw.get("duration_ms") or 0)),
                "status": str(raw.get("status") or "failed"),
                "error_code": str(raw.get("error_code") or "").strip() or None,
            })

    def _insert_archive(
        self,
        conn: Any,
        *,
        run: PredictionRun,
        prediction_id: str | None,
        attempts: list[Mapping[str, Any]],
        status: str,
        failure_code: str | None,
    ) -> None:
        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "prompt": 0,
                "completion": 0,
                "calls": 0,
                "failed": 0,
                "duration": 0,
                "providers": set(),
            }
        )
        for raw in attempts:
            model = str(raw.get("model") or "unknown")
            item = grouped[model]
            item["providers"].add(str(raw.get("provider") or raw.get("endpoint_name") or "unknown"))
            item["prompt"] += max(0, int(raw.get("prompt_tokens") or 0))
            item["completion"] += max(0, int(raw.get("completion_tokens") or 0))
            item["calls"] += 1
            item["failed"] += int(raw.get("status") != "success")
            item["duration"] += max(0, int(raw.get("duration_ms") or 0))
        for model, item in grouped.items():
            provider = ",".join(sorted(item["providers"]))
            conn.execute(text(
                "INSERT INTO agent_run_archive(run_id,user_id,agent,layer,prediction_id,model,"
                "prompt_tokens,completion_tokens,total_tokens,cost_usd,call_count,failed_call_count,"
                "duration_ms,status,failure_code,provider,prompt_version) VALUES("
                ":run_id,:user_id,:agent,'prediction',CAST(:prediction_id AS uuid),:model,:prompt_tokens,"
                ":completion_tokens,:total_tokens,:cost_usd,:call_count,:failed_call_count,:duration_ms,"
                ":status,:failure_code,:provider,:prompt_version) "
                "ON CONFLICT(run_id,user_id,agent,layer,model) DO UPDATE SET "
                "prediction_id=excluded.prediction_id,prompt_tokens=excluded.prompt_tokens,"
                "completion_tokens=excluded.completion_tokens,total_tokens=excluded.total_tokens,"
                "cost_usd=excluded.cost_usd,call_count=excluded.call_count,"
                "failed_call_count=excluded.failed_call_count,duration_ms=excluded.duration_ms,"
                "status=excluded.status,failure_code=excluded.failure_code,provider=excluded.provider,"
                "prompt_version=excluded.prompt_version"
            ), {
                "run_id": run.id,
                "user_id": run.user_id,
                "agent": PREDICTION_AGENT,
                "prediction_id": prediction_id,
                "model": model,
                "prompt_tokens": item["prompt"],
                "completion_tokens": item["completion"],
                "total_tokens": item["prompt"] + item["completion"],
                "cost_usd": estimate_cost({model: {"prompt": item["prompt"], "completion": item["completion"]}}),
                "call_count": item["calls"],
                "failed_call_count": item["failed"],
                "duration_ms": item["duration"],
                "status": status,
                "failure_code": failure_code,
                "provider": provider,
                "prompt_version": run.prompt_version,
            })

    def history(
        self,
        *,
        user_id: str,
        symbol: str | None,
        direction: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        filters = ["p.user_id=:user_id"]
        params: dict[str, Any] = {
            "user_id": user_id,
            "limit": max(1, min(100, int(limit))),
            "offset": max(0, int(offset)),
        }
        if symbol:
            filters.append("p.symbol=:symbol")
            params["symbol"] = symbol
        if direction:
            filters.append("p.direction=:direction")
            params["direction"] = direction
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT p.*,CASE WHEN o.prediction_id IS NULL THEN NULL ELSE jsonb_build_object("
                "'status',o.status,'resolved_at',o.resolved_at,'entry_time',o.entry_time,"
                "'entry_price',o.entry_price,'pct_since_anchor',o.pct_since_anchor,"
                "'resolution_reason',o.resolution_reason,'evaluated_through',o.evaluated_through,"
                "'market_provider',o.market_provider,'market_as_of',o.market_as_of,"
                "'algorithm_version',o.algorithm_version) END AS outcome_json "
                "FROM agent_predictions p LEFT JOIN agent_prediction_outcomes o "
                "ON o.prediction_id=p.id AND o.user_id=p.user_id WHERE "
                + " AND ".join(filters)
                + " ORDER BY p.created_at DESC LIMIT :limit OFFSET :offset"
            ), params).mappings().all()
        result: list[dict[str, Any]] = []
        for raw in rows:
            payload = dict(raw)
            outcome = payload.pop("outcome_json", None)
            result.append({
                "prediction": _prediction_from_row(payload),
                "outcome": dict(outcome) if isinstance(outcome, Mapping) else outcome,
            })
        return result

    def stats(self, *, user_id: str, symbol: str | None, days: int) -> dict[str, Any]:
        filters = ["p.user_id=:user_id", "p.created_at >= now() - (:days * interval '1 day')"]
        params: dict[str, Any] = {"user_id": user_id, "days": max(1, min(3650, int(days)))}
        if symbol:
            filters.append("p.symbol=:symbol")
            params["symbol"] = symbol
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT p.source_type,p.direction,o.status,COUNT(*) AS count "
                "FROM agent_predictions p LEFT JOIN agent_prediction_outcomes o "
                "ON o.prediction_id=p.id AND o.user_id=p.user_id WHERE "
                + " AND ".join(filters)
                + " GROUP BY p.source_type,p.direction,o.status"
            ), params).mappings().all()
        return _summarize_stats(rows, days=params["days"], symbol=symbol)


def _empty_stat_bucket() -> dict[str, Any]:
    return {
        "predictions": 0,
        "hits": 0,
        "misses": 0,
        "invalidated": 0,
        "resolved": 0,
        "hit_rate": None,
    }


def _summarize_stats(
    rows: list[Mapping[str, Any]],
    *,
    days: int,
    symbol: str | None,
) -> dict[str, Any]:
    overall = _empty_stat_bucket()
    by_source = {"ai": _empty_stat_bucket(), "manual": _empty_stat_bucket()}
    by_direction: dict[str, dict[str, Any]] = {}

    def apply(bucket: dict[str, Any], status: str, count: int) -> None:
        bucket["predictions"] += count
        if status in {"hit_target", "held_range"}:
            bucket["hits"] += count
        elif status in {"hit_stop", "broke_range"}:
            bucket["misses"] += count
        elif status == "invalidated":
            bucket["invalidated"] += count

    for row in rows:
        source = str(row.get("source_type") or "ai")
        direction = str(row.get("direction") or "unknown")
        status = str(row.get("status") or "open")
        count = max(0, int(row.get("count") or 0))
        source_bucket = by_source.setdefault(source, _empty_stat_bucket())
        direction_bucket = by_direction.setdefault(direction, _empty_stat_bucket())
        apply(overall, status, count)
        apply(source_bucket, status, count)
        apply(direction_bucket, status, count)

    for bucket in [overall, *by_source.values(), *by_direction.values()]:
        bucket["resolved"] = bucket["hits"] + bucket["misses"]
        if bucket["resolved"]:
            bucket["hit_rate"] = round(bucket["hits"] / bucket["resolved"], 4)
    return {
        "days": days,
        "symbol": symbol,
        **overall,
        "by_source": by_source,
        "by_direction": by_direction,
    }


class PredictionService:
    def __init__(
        self,
        *,
        store: PredictionRunStore,
        market_gateway: Any,
        invoke_llm: Callable[..., Awaitable[Any]] = ainvoke_configured_llm,
        prompt_version: str = PREDICTION_PROMPT_VERSION,
        timeout_seconds: float = PREDICTION_HARD_TIMEOUT_SECONDS,
        llm_attempt_timeout_seconds: float = PREDICTION_LLM_ATTEMPT_TIMEOUT_SECONDS,
        news_timeout_seconds: float = PREDICTION_NEWS_TIMEOUT_SECONDS,
        llm_endpoint_names: str | Collection[str] | None = None,
        max_concurrent_runs: int = 2,
        enabled: bool = True,
    ) -> None:
        self.store = store
        self.market_gateway = market_gateway
        self.invoke_llm = invoke_llm
        self.prompt_version = str(prompt_version or PREDICTION_PROMPT_VERSION)
        self.timeout_seconds = max(10.0, min(PREDICTION_HARD_TIMEOUT_SECONDS, float(timeout_seconds)))
        self.llm_attempt_timeout_seconds = max(
            5.0,
            min(32.0, float(llm_attempt_timeout_seconds)),
        )
        self.news_timeout_seconds = max(0.1, min(10.0, float(news_timeout_seconds)))
        self.llm_endpoint_names = _prediction_llm_endpoint_names(llm_endpoint_names)
        self.enabled = bool(enabled)
        self._run_slots = asyncio.Semaphore(max(1, min(16, int(max_concurrent_runs))))
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._recovery_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def generate(self, *, user_id: str, symbol: str, timeframe: str = "1d") -> tuple[PredictionRun, bool]:
        if not self.enabled:
            raise PredictionServiceUnavailable("prediction generation disabled")
        normalized_user = str(user_id or "").strip()
        if not normalized_user or normalized_user == "public":
            raise ValueError("auth_required")
        normalized_symbol = normalize_prediction_symbol(symbol)
        if timeframe != "1d":
            raise ValueError("unsupported prediction timeframe")
        run, created = await asyncio.to_thread(
            self.store.create_or_get_active,
            user_id=normalized_user,
            symbol=normalized_symbol,
            timeframe=timeframe,
            prompt_version=self.prompt_version,
        )
        if created:
            self._schedule(run.id)
        return run, created

    async def get_run(self, run_id: str, *, user_id: str) -> PredictionRun | None:
        return await asyncio.to_thread(self.store.get_run, run_id, user_id=user_id)

    async def get_prediction(self, prediction_id: str, *, user_id: str) -> AgentPrediction | None:
        return await asyncio.to_thread(self.store.get_prediction, prediction_id, user_id=user_id)

    async def get_latest(self, *, user_id: str, symbol: str) -> AgentPrediction | None:
        return await asyncio.to_thread(
            self.store.get_latest_prediction,
            user_id=user_id,
            symbol=normalize_prediction_symbol(symbol),
        )

    async def get_outcome(self, prediction_id: str, *, user_id: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self.store.get_outcome,
            prediction_id,
            user_id=user_id,
        )

    async def history(
        self,
        *,
        user_id: str,
        symbol: str | None,
        direction: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        normalized_symbol = normalize_prediction_symbol(symbol) if symbol else None
        if direction not in {None, "long", "short", "neutral"}:
            raise ValueError("invalid prediction direction")
        return await asyncio.to_thread(
            self.store.history,
            user_id=user_id,
            symbol=normalized_symbol,
            direction=direction,
            limit=limit,
            offset=offset,
        )

    async def stats(self, *, user_id: str, symbol: str | None, days: int) -> dict[str, Any]:
        normalized_symbol = normalize_prediction_symbol(symbol) if symbol else None
        return await asyncio.to_thread(
            self.store.stats,
            user_id=user_id,
            symbol=normalized_symbol,
            days=days,
        )

    def enqueue(
        self,
        *,
        user_id: str,
        symbol: str,
        timeframe: str = "1d",
    ) -> tuple[PredictionRun, bool]:
        """从调度器线程创建 run，并安全投递给 FastAPI 主事件循环。"""
        if not self.enabled:
            raise PredictionServiceUnavailable("prediction generation disabled")
        normalized_user = str(user_id or "").strip()
        if not normalized_user or normalized_user == "public":
            raise ValueError("auth_required")
        normalized_symbol = normalize_prediction_symbol(symbol)
        if timeframe != "1d":
            raise ValueError("unsupported prediction timeframe")
        loop = self._loop
        if loop is None or loop.is_closed() or not loop.is_running():
            raise PredictionServiceUnavailable("prediction worker unavailable")
        run, created = self.store.create_or_get_active(
            user_id=normalized_user,
            symbol=normalized_symbol,
            timeframe=timeframe,
            prompt_version=self.prompt_version,
        )
        if created:
            loop.call_soon_threadsafe(self._schedule, run.id)
        return run, created

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._recovery_task is None or self._recovery_task.done():
            self._recovery_task = asyncio.create_task(self._recovery_loop())

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            tasks.append(self._recovery_task)
            self._recovery_task = None
        for task in self._tasks.values():
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._loop = None

    def _schedule(self, run_id: str) -> None:
        current = self._tasks.get(run_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(self._process_run(run_id))
        self._tasks[run_id] = task

        def _discard(done: asyncio.Task[None], *, key: str = run_id) -> None:
            if self._tasks.get(key) is done:
                self._tasks.pop(key, None)
            try:
                done.exception()
            except (asyncio.CancelledError, Exception):
                return

        task.add_done_callback(_discard)

    async def _recovery_loop(self) -> None:
        try:
            while True:
                try:
                    run_ids = await asyncio.to_thread(self.store.recoverable_run_ids, limit=100)
                    for run_id in run_ids:
                        self._schedule(run_id)
                except Exception:
                    logger.exception("prediction run recovery scan failed")
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            return

    async def _process_run(self, run_id: str) -> None:
        async with self._run_slots:
            await self._process_claimed_run(run_id)

    async def _process_claimed_run(self, run_id: str) -> None:
        started = perf_counter()
        attempts: list[Mapping[str, Any]] = []
        run = await asyncio.to_thread(self.store.claim, run_id)
        if run is None:
            return
        stage = "market"
        try:
            async with asyncio.timeout(self.timeout_seconds):
                market_task = asyncio.to_thread(
                    self.market_gateway.get_kline,
                    run.symbol,
                    period="1y",
                    interval=run.timeframe,
                )
                news_task = asyncio.wait_for(
                    asyncio.to_thread(self.market_gateway.get_news, run.symbol, limit=5),
                    timeout=self.news_timeout_seconds,
                )
                market, news = await asyncio.gather(market_task, news_task, return_exceptions=True)
                if isinstance(market, BaseException):
                    raise MarketDataUnavailable(_safe_failure_detail(market))
                if isinstance(news, BaseException):
                    logger.info("prediction optional news unavailable: symbol=%s", run.symbol)
                    news = {}
                self._validate_market(market)
                await asyncio.to_thread(self.store.set_market_context, run, market)
                bars = market["kline_data"]
                anchor = bars[-1]
                existing = await asyncio.to_thread(
                    self.store.get_by_anchor,
                    user_id=run.user_id,
                    symbol=run.symbol,
                    timeframe=run.timeframe,
                    anchor_time=str(anchor["time"]),
                    prompt_version=run.prompt_version,
                )
                if existing is not None:
                    await asyncio.to_thread(
                        self.store.complete_reused,
                        run,
                        existing,
                        latency_ms=int((perf_counter() - started) * 1000),
                    )
                    return

                previous = await asyncio.to_thread(
                    self.store.get_latest_prediction,
                    user_id=run.user_id,
                    symbol=run.symbol,
                )
                indicators = await asyncio.to_thread(_compute_indicators, bars)
                stage = "llm"

                def observe(payload: Mapping[str, Any]) -> None:
                    attempts.append(dict(payload))

                context = LLMCallContext.create(
                    stage="prediction_generate",
                    agent=PREDICTION_AGENT,
                    layer="prediction",
                    max_provider_attempts=PREDICTION_MAX_PROVIDER_ATTEMPTS,
                    on_attempt=observe,
                )
                feedback: list[dict[str, Any]] | None = None
                prediction: AgentPrediction | None = None
                for _submission_attempt in range(2):
                    try:
                        response = await self._invoke(
                            _prediction_prompt(
                                run=run,
                                market=market,
                                indicators=indicators,
                                news=news,
                                previous=previous,
                                feedback=feedback,
                            ),
                            context=context,
                        )
                    except Exception as exc:
                        if feedback is not None and context.budget.remaining <= 0:
                            logger.warning(
                                "prediction correction exhausted provider budget: run_id=%s error_code=%s",
                                run.id,
                                classify_llm_error(exc).code,
                            )
                            raise PredictionValidationError(
                                json.dumps(feedback, ensure_ascii=False)
                            ) from exc
                        raise
                    raw = prediction_json_from_llm_content(response)
                    if raw is None:
                        feedback = [{
                            "field": "prediction",
                            "rule": "invalid_json",
                            "expected": "只返回一个符合合同的 JSON 对象",
                        }]
                        continue
                    try:
                        prediction = build_prediction(
                            raw,
                            symbol=run.symbol,
                            agent=PREDICTION_AGENT,
                            user_id=run.user_id,
                            run_id=run.id,
                            operation=PREDICTION_OPERATION,
                            raw_bars=market,
                            prompt_version=run.prompt_version,
                        )
                        break
                    except Exception as exc:
                        feedback = [{
                            "field": "prediction",
                            "rule": "contract_validation",
                            "expected": _safe_failure_detail(exc),
                        }]
                if prediction is None:
                    raise PredictionValidationError(json.dumps(feedback or [], ensure_ascii=False))
                stage = "store"
                await asyncio.to_thread(
                    self.store.complete_success,
                    run,
                    prediction,
                    attempts=attempts,
                    latency_ms=int((perf_counter() - started) * 1000),
                )
        except asyncio.CancelledError:
            await self._finish_failure(
                run,
                status="cancelled",
                code="cancelled",
                detail="prediction worker stopped",
                attempts=attempts,
                started=started,
            )
            raise
        except TimeoutError as exc:
            code = MARKET_DATA_UNAVAILABLE if stage == "market" else "llm_timeout"
            await self._finish_failure(
                run,
                status="unavailable",
                code=code,
                detail=exc or f"{stage} timeout",
                attempts=attempts,
                started=started,
            )
        except MarketDataUnavailable as exc:
            await self._finish_failure(
                run,
                status="unavailable",
                code=MARKET_DATA_UNAVAILABLE,
                detail=exc,
                attempts=attempts,
                started=started,
            )
        except PredictionValidationError as exc:
            await self._finish_failure(
                run,
                status="failed",
                code=PREDICTION_VALIDATION_FAILED,
                detail=exc,
                attempts=attempts,
                started=started,
            )
        except Exception as exc:
            if stage == "llm":
                classification = classify_llm_error(exc)
                code = _public_llm_error_code(classification.code)
                status: Literal["unavailable", "failed"] = "unavailable"
            else:
                code = STORE_UNAVAILABLE if stage == "store" else MARKET_DATA_UNAVAILABLE
                status = "failed" if stage == "store" else "unavailable"
            await self._finish_failure(
                run,
                status=status,
                code=code,
                detail=exc,
                attempts=attempts,
                started=started,
            )

    async def _invoke(self, prompt: str, *, context: LLMCallContext) -> Any:
        from langchain_core.messages import HumanMessage

        return await self.invoke_llm(
            [HumanMessage(content=prompt)],
            context=context,
            temperature=0.1,
            max_tokens=max(512, min(2400, int(os.getenv("PREDICTION_LLM_MAX_TOKENS", "1600")))),
            request_timeout=int(self.llm_attempt_timeout_seconds),
            acquire_token=True,
            acquire_timeout_seconds=min(10.0, self.llm_attempt_timeout_seconds),
            endpoint_names=self.llm_endpoint_names,
        )

    async def _finish_failure(
        self,
        run: PredictionRun,
        *,
        status: Literal["unavailable", "failed", "cancelled"],
        code: str,
        detail: Any,
        attempts: list[Mapping[str, Any]],
        started: float,
    ) -> None:
        try:
            await asyncio.to_thread(
                self.store.complete_failure,
                run,
                status=status,
                failure_code=code,
                failure_detail=_safe_failure_detail(detail),
                attempts=attempts,
                latency_ms=int((perf_counter() - started) * 1000),
            )
        except Exception:
            logger.exception("prediction run failure state could not be persisted: run_id=%s", run.id)

    @staticmethod
    def _validate_market(market: Any) -> None:
        if not isinstance(market, Mapping):
            raise MarketDataUnavailable(MARKET_DATA_UNAVAILABLE)
        if market.get("quality") != "trusted" or market.get("error_code"):
            raise MarketDataUnavailable(str(market.get("error_code") or MARKET_DATA_UNAVAILABLE))
        if not str(market.get("provider") or "").strip() or not str(market.get("as_of") or "").strip():
            raise MarketDataUnavailable("trusted market provenance missing")
        bars = market.get("kline_data")
        if not isinstance(bars, list) or len(bars) < PREDICTION_MIN_BARS:
            raise MarketDataUnavailable(f"trusted kline requires at least {PREDICTION_MIN_BARS} bars")


def _compute_indicators(bars: list[Mapping[str, Any]]) -> dict[str, Any]:
    from backend.tools.technical import compute_technical_indicators

    frame = pd.DataFrame([
        {
            "Open": item.get("open"),
            "High": item.get("high"),
            "Low": item.get("low"),
            "Close": item.get("close"),
            "Volume": item.get("volume") or 0,
        }
        for item in bars
    ])
    indicators = compute_technical_indicators(frame)
    if not indicators:
        raise MarketDataUnavailable("technical indicators unavailable")
    return indicators


def _compact_bars(bars: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in bars[-90:]:
        result.append({
            "time": item.get("time"),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "close": item.get("close"),
            "volume": item.get("volume"),
        })
    return result


def _compact_news(news: Any) -> list[dict[str, Any]]:
    if not isinstance(news, Mapping):
        return []
    items = news.get("news") or news.get("data")
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for item in items[:5]:
        if not isinstance(item, Mapping):
            continue
        result.append({
            "title": str(item.get("title") or item.get("headline") or "")[:200],
            "published_at": item.get("published_at") or item.get("datetime") or item.get("date"),
            "source": item.get("source"),
            "summary": str(item.get("summary") or item.get("snippet") or "")[:400],
        })
    return result


def _prediction_prompt(
    *,
    run: PredictionRun,
    market: Mapping[str, Any],
    indicators: Mapping[str, Any],
    news: Any,
    previous: AgentPrediction | None,
    feedback: list[dict[str, Any]] | None,
) -> str:
    bars = market["kline_data"]
    anchor = bars[-1]
    previous_payload = (
        previous.model_dump(
            mode="json",
            exclude={"risk_reward", "user_id", "run_id", "report_id"},
        )
        if previous is not None else None
    )
    correction = (
        "\n上次输出未通过服务端合同，逐项修正："
        + json.dumps(feedback, ensure_ascii=False, default=str)
        if feedback else ""
    )
    return f"""你是 FinSight 的 PredictionAnalyst。根据服务端提供的真实行情和确定性指标，
只输出一个 JSON 对象，不要 markdown、解释前缀或行情数组。

固定身份与锚点：
- symbol={run.symbol}
- agent={PREDICTION_AGENT}
- anchor.timeframe={run.timeframe}
- anchor.time={anchor['time']}
- anchor.price={anchor['close']}

输出合同：
- symbol、agent、direction(long|short|neutral)、confidence(0-1)、thesis(1-400字)、anchor。
- scenarios 必须 2-4 条；每条含 name、probability(0-100)、invalidation；概率和在 90-110。
- long/short 必须含 entry_type(market|limit|stop)、entry、stop、target1、invalidation_price；RR>=1；target2 可选。
- long: stop < entry < target1，invalidation_price <= stop。
- short: target1 < entry < stop，invalidation_price >= stop。
- neutral 不得包含方向性价位或 entry_type，必须给 range_low/range_high，且包含 anchor.price。
- 禁止输出 bars、candles、series、ohlc、data、user_id、run_id、provider 或 token 字段。

行情 provenance：provider={market.get('provider')}, as_of={market.get('as_of')}。
最近真实日线（只作为输入，禁止原样输出）：
{json.dumps(_compact_bars(bars), ensure_ascii=False, separators=(',', ':'), default=str)}

服务端指标：
{json.dumps(dict(indicators), ensure_ascii=False, separators=(',', ':'), default=str)}

近期新闻（可为空）：
{json.dumps(_compact_news(news), ensure_ascii=False, separators=(',', ':'), default=str)}

上一条已验证 Prediction（可为空，仅用于判断是否需要改变观点）：
{json.dumps(previous_payload, ensure_ascii=False, separators=(',', ':'), default=str)}{correction}"""


def _public_llm_error_code(code: str) -> str:
    mapping = {
        "llm_authentication_failed": "llm_authentication_failed",
        "llm_quota_exhausted": "llm_quota_exceeded",
        "llm_policy_refusal": "llm_policy_rejected",
        "llm_timeout": "llm_timeout",
        "llm_configuration_error": "llm_authentication_failed",
    }
    return mapping.get(code, "llm_timeout")


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "true" if default else "false")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


_service: PredictionService | None = None
_service_lock = threading.Lock()


def get_prediction_service() -> PredictionService:
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            dsn = resolve_core_postgres_dsn(required=False)
            if not dsn:
                raise PredictionServiceUnavailable("prediction postgres unavailable")
            _service = PredictionService(
                store=PredictionRunStore(dsn=dsn),
                market_gateway=get_market_data_gateway(),
                prompt_version=str(os.getenv("PREDICTION_PROMPT_VERSION") or PREDICTION_PROMPT_VERSION),
                timeout_seconds=float(os.getenv("PREDICTION_RUN_TIMEOUT_SECONDS", "75")),
                llm_attempt_timeout_seconds=float(
                    os.getenv("PREDICTION_LLM_ATTEMPT_TIMEOUT_SECONDS", "30")
                ),
                news_timeout_seconds=float(os.getenv("PREDICTION_NEWS_TIMEOUT_SECONDS", "5")),
                max_concurrent_runs=int(os.getenv("PREDICTION_MAX_CONCURRENT_RUNS", "2")),
                enabled=_env_bool("PREDICTION_GENERATION_ENABLED", True),
            )
    return _service


def reset_prediction_service_cache() -> None:
    global _service
    with _service_lock:
        _service = None


__all__ = [
    "MARKET_DATA_UNAVAILABLE",
    "PREDICTION_HARD_TIMEOUT_SECONDS",
    "PREDICTION_DEFAULT_LLM_ENDPOINT_NAMES",
    "PREDICTION_LLM_ATTEMPT_TIMEOUT_SECONDS",
    "PREDICTION_MAX_PROVIDER_ATTEMPTS",
    "PREDICTION_NEWS_TIMEOUT_SECONDS",
    "PREDICTION_PROMPT_VERSION",
    "PREDICTION_VALIDATION_FAILED",
    "PredictionRun",
    "PredictionRunStore",
    "PredictionService",
    "PredictionServiceUnavailable",
    "get_prediction_service",
    "normalize_prediction_symbol",
    "reset_prediction_service_cache",
]
