# -*- coding: utf-8 -*-
"""Prediction 的显式生成、状态、历史、统计与运维补跑 API。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.agents.prediction_contract import PredictionAnchor, PredictionScenario
from backend.services.prediction_service import (
    PredictionRun,
    PredictionServiceUnavailable,
    normalize_prediction_symbol,
)
from backend.services.cost_audit import UserDailyCostLimitExceeded


class PredictionRunView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    symbol: str
    timeframe: str
    prompt_version: str
    status: Literal["queued", "running", "succeeded", "unavailable", "failed", "cancelled"]
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


class PredictionPriceRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: float
    high: float


class PredictionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_id: str
    run_id: str
    symbol: str
    agent: str
    direction: Literal["long", "short", "neutral"]
    confidence: float
    thesis: str
    anchor: PredictionAnchor
    entry_type: Literal["market", "limit", "stop"] | None = None
    entry: float | None = None
    stop: float | None = None
    target1: float | None = None
    target2: float | None = None
    invalidation_price: float | None = None
    range_low: float | None = None
    range_high: float | None = None
    range: PredictionPriceRange | None = None
    scenarios: list[PredictionScenario]
    status: Literal[
        "waiting", "open", "triggered", "invalidated", "hit_target", "hit_stop",
        "held_range", "broke_range",
    ]
    prompt_version: str
    evidence_provider: str | None = None
    evidence_as_of: datetime | None = None
    source_type: Literal["ai", "manual"]
    created_at: datetime
    updated_at: datetime


class PredictionOutcomeView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_id: str
    status: str
    resolved_at: datetime | None = None
    entry_time: datetime | None = None
    entry_price: float | None = None
    pct_since_anchor: float | None = None
    resolution_reason: str | None = None
    evaluated_through: datetime | None = None
    market_provider: str | None = None
    market_as_of: datetime | None = None
    algorithm_version: str


class GeneratePredictionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: PredictionRunView
    created: bool
    idempotent_reuse: bool


class PredictionRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: PredictionRunView


class PredictionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction: PredictionView | None
    outcome: PredictionOutcomeView | None = None


class PredictionHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction: PredictionView
    outcome: PredictionOutcomeView | None = None


class PredictionHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PredictionHistoryItem]
    limit: int
    offset: int


class PredictionStatBucket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    predictions: int
    hits: int
    misses: int
    invalidated: int
    resolved: int
    hit_rate: float | None


class PredictionStatsView(PredictionStatBucket):
    days: int
    symbol: str | None
    by_source: dict[str, PredictionStatBucket]
    by_direction: dict[str, PredictionStatBucket]


class PredictionStatsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stats: PredictionStatsView


class RecomputeOutcomesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluated: int
    prediction_id: str | None


class GeneratePredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=32)
    timeframe: Literal["1d"] = "1d"

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return normalize_prediction_symbol(value)


class RecomputeOutcomesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_id: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=500, ge=1, le=5000)

    @field_validator("prediction_id")
    @classmethod
    def validate_prediction_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return str(UUID(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("prediction_id must be a UUID") from exc


@dataclass(frozen=True)
class PredictionsRouterDeps:
    get_service: Callable[[], Any]
    check_user_quota: Callable[[str], None]
    run_outcome_cycle: Callable[..., int]
    is_internal_authorized: Callable[[Request], bool]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _user_id(request: Request) -> str:
    user_id = str(getattr(request.state, "user_id", "public") or "public").strip()
    if not user_id or user_id == "public":
        raise _error(401, "auth_required", "登录后才能使用 AI Prediction")
    return user_id


def _uuid_or_404(value: str, *, resource: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise _error(404, f"{resource}_not_found", f"{resource} not found") from exc


def _public_run(run: PredictionRun) -> dict[str, Any]:
    return run.model_dump(mode="json", exclude={"user_id"})


def _public_prediction(prediction: Any) -> dict[str, Any]:
    payload = prediction.model_dump(
        mode="json",
        exclude={"risk_reward", "user_id", "report_id"},
    )
    payload["prediction_id"] = payload.pop("id")
    if payload.get("range_low") is not None and payload.get("range_high") is not None:
        payload["range"] = {
            "low": payload["range_low"],
            "high": payload["range_high"],
        }
    return payload


def _public_outcome(outcome: Any) -> dict[str, Any] | None:
    if outcome is None:
        return None
    if isinstance(outcome, BaseModel):
        return outcome.model_dump(mode="json", exclude={"user_id"})
    if isinstance(outcome, dict):
        return {key: value for key, value in outcome.items() if key != "user_id"}
    return None


def create_predictions_router(deps: PredictionsRouterDeps) -> APIRouter:
    router = APIRouter(prefix="/api/predictions", tags=["Predictions"])

    def service() -> Any:
        try:
            return deps.get_service()
        except Exception as exc:
            raise _error(503, "store_unavailable", "Prediction 服务未就绪") from exc

    @router.post("/generate", status_code=202)
    async def generate_prediction(
        payload: GeneratePredictionRequest,
        request: Request,
    ) -> GeneratePredictionResponse:
        user_id = _user_id(request)
        try:
            deps.check_user_quota(user_id)
        except UserDailyCostLimitExceeded as exc:
            raise _error(429, "llm_quota_exceeded", str(exc)) from exc
        except Exception as exc:
            raise _error(503, "store_unavailable", "AI 额度暂时无法检查") from exc
        try:
            run, created = await service().generate(
                user_id=user_id,
                symbol=payload.symbol,
                timeframe=payload.timeframe,
            )
        except PredictionServiceUnavailable as exc:
            raise _error(503, "store_unavailable", "Prediction 服务未就绪") from exc
        except ValueError as exc:
            if str(exc) == "auth_required":
                raise _error(401, "auth_required", "登录后才能生成 AI Prediction") from exc
            raise _error(422, "prediction_validation_failed", str(exc)) from exc
        except Exception as exc:
            raise _error(503, "store_unavailable", "Prediction run 无法创建") from exc
        return GeneratePredictionResponse(
            run=_public_run(run),
            created=created,
            idempotent_reuse=not created,
        )

    @router.post("/outcomes/recompute")
    async def recompute_outcomes(
        payload: RecomputeOutcomesRequest,
        request: Request,
    ) -> RecomputeOutcomesResponse:
        user_id = _user_id(request)
        if not deps.is_internal_authorized(request):
            raise _error(403, "internal_authorization_required", "Outcome 补跑需要内部 API key")
        try:
            evaluated = await asyncio.to_thread(
                deps.run_outcome_cycle,
                user_id=user_id,
                prediction_id=payload.prediction_id,
                limit=payload.limit,
            )
        except Exception as exc:
            raise _error(503, "store_unavailable", "Outcome 补跑失败") from exc
        return RecomputeOutcomesResponse(
            evaluated=int(evaluated),
            prediction_id=payload.prediction_id,
        )

    @router.get("/runs/{run_id}")
    async def get_prediction_run(run_id: str, request: Request) -> PredictionRunResponse:
        user_id = _user_id(request)
        normalized_id = _uuid_or_404(run_id, resource="prediction_run")
        try:
            run = await service().get_run(normalized_id, user_id=user_id)
        except Exception as exc:
            raise _error(503, "store_unavailable", "Prediction run 暂时无法读取") from exc
        if run is None:
            raise _error(404, "prediction_run_not_found", "prediction run not found")
        return PredictionRunResponse(run=_public_run(run))

    @router.get("/latest")
    async def get_latest_prediction(
        request: Request,
        symbol: str = Query(min_length=1, max_length=32),
    ) -> PredictionResponse:
        user_id = _user_id(request)
        try:
            prediction = await service().get_latest(user_id=user_id, symbol=symbol)
            outcome = (
                await service().get_outcome(prediction.id, user_id=user_id)
                if prediction is not None
                else None
            )
        except ValueError as exc:
            raise _error(422, "prediction_validation_failed", "symbol 格式非法") from exc
        except Exception as exc:
            raise _error(503, "store_unavailable", "Prediction 暂时无法读取") from exc
        return PredictionResponse(
            prediction=_public_prediction(prediction) if prediction is not None else None,
            outcome=_public_outcome(outcome),
        )

    @router.get("/history")
    async def get_prediction_history(
        request: Request,
        symbol: str | None = Query(default=None, max_length=32),
        direction: Literal["long", "short", "neutral"] | None = None,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10000),
    ) -> PredictionHistoryResponse:
        user_id = _user_id(request)
        try:
            rows = await service().history(
                user_id=user_id,
                symbol=symbol,
                direction=direction,
                limit=limit,
                offset=offset,
            )
        except ValueError as exc:
            raise _error(422, "prediction_validation_failed", str(exc)) from exc
        except Exception as exc:
            raise _error(503, "store_unavailable", "Prediction history 暂时无法读取") from exc
        return PredictionHistoryResponse(
            items=[
                {
                    "prediction": _public_prediction(row["prediction"]),
                    "outcome": _public_outcome(row.get("outcome")),
                }
                for row in rows
            ],
            limit=limit,
            offset=offset,
        )

    @router.get("/stats")
    async def get_prediction_stats(
        request: Request,
        symbol: str | None = Query(default=None, max_length=32),
        days: int = Query(default=90, ge=1, le=3650),
    ) -> PredictionStatsResponse:
        user_id = _user_id(request)
        try:
            return PredictionStatsResponse(
                stats=await service().stats(user_id=user_id, symbol=symbol, days=days),
            )
        except ValueError as exc:
            raise _error(422, "prediction_validation_failed", str(exc)) from exc
        except Exception as exc:
            raise _error(503, "store_unavailable", "Prediction stats 暂时无法读取") from exc

    @router.get("/{prediction_id}")
    async def get_prediction(prediction_id: str, request: Request) -> PredictionResponse:
        user_id = _user_id(request)
        normalized_id = _uuid_or_404(prediction_id, resource="prediction")
        try:
            prediction = await service().get_prediction(normalized_id, user_id=user_id)
        except Exception as exc:
            raise _error(503, "store_unavailable", "Prediction 暂时无法读取") from exc
        if prediction is None:
            # 不区分不存在和跨租户，避免泄露资源存在性。
            raise _error(404, "prediction_not_found", "prediction not found")
        try:
            outcome = await service().get_outcome(prediction.id, user_id=user_id)
        except Exception as exc:
            raise _error(503, "store_unavailable", "Prediction Outcome 暂时无法读取") from exc
        return PredictionResponse(
            prediction=_public_prediction(prediction),
            outcome=_public_outcome(outcome),
        )

    return router


__all__ = [
    "GeneratePredictionRequest",
    "GeneratePredictionResponse",
    "PredictionHistoryResponse",
    "PredictionResponse",
    "PredictionRunResponse",
    "PredictionStatsResponse",
    "PredictionsRouterDeps",
    "RecomputeOutcomesRequest",
    "create_predictions_router",
]
