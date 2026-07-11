# -*- coding: utf-8 -*-
"""组合收益归因 API。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.tools import price as price_tools


attribution_router = APIRouter(tags=["Portfolio"])


class AttributionPosition(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    weight: float = Field(..., ge=0, le=1)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        ticker = value.strip().upper()
        if not ticker:
            raise ValueError("ticker is required")
        return ticker


class AttributionRequest(BaseModel):
    positions: list[AttributionPosition] = Field(default_factory=list)
    lookback_days: int = Field(default=252, ge=30, le=1260)


class ContributionItem(BaseModel):
    ticker: str
    weight: float
    return_pct: float | None
    contribution_pct: float | None


class BenchmarkResult(BaseModel):
    symbol: str = "SPY"
    return_pct: float | None


class AttributionResponse(BaseModel):
    beta: float | None
    factor_exposure: dict[str, Any]
    contribution: list[ContributionItem]
    benchmark: BenchmarkResult
    as_of: str
    warnings: list[str]


def _period_return_pct(frame: pd.DataFrame, symbol: str) -> float | None:
    if symbol not in frame.columns:
        return None
    values = pd.to_numeric(frame[symbol], errors="coerce").dropna()
    if len(values) < 2:
        return None
    first = float(values.iloc[0])
    last = float(values.iloc[-1])
    if first <= 0:
        return None
    return (last / first - 1.0) * 100.0


def _resolve_as_of(frame: pd.DataFrame | None) -> str:
    if frame is not None and not frame.empty:
        last_index = frame.index[-1]
        if isinstance(last_index, (pd.Timestamp, datetime, date)):
            return last_index.date().isoformat() if isinstance(last_index, (pd.Timestamp, datetime)) else last_index.isoformat()
    return date.today().isoformat()


@attribution_router.post(
    "/api/portfolio/attribution",
    response_model=AttributionResponse,
)
def calculate_portfolio_attribution(request: AttributionRequest) -> AttributionResponse:
    """按区间收益率 × 权重计算持仓贡献，并复用现有因子暴露工具。"""
    if not request.positions:
        raise HTTPException(status_code=422, detail="请先录入至少一个持仓，再计算组合归因")
    if sum(position.weight for position in request.positions) <= 0:
        raise HTTPException(status_code=422, detail="持仓权重之和必须大于 0")

    positions = [position.model_dump() for position in request.positions]
    symbols = list(dict.fromkeys([position.ticker for position in request.positions] + ["SPY"]))
    frame = price_tools._download_close_frame(symbols, lookback_days=request.lookback_days)
    if frame is None:
        frame = pd.DataFrame()

    factor_exposure = price_tools.get_factor_exposure(
        positions,
        lookback_days=request.lookback_days,
    )
    factor_beta = factor_exposure.get("factor_beta")
    beta_value = factor_beta.get("market") if isinstance(factor_beta, dict) else None
    beta = round(float(beta_value), 4) if isinstance(beta_value, (int, float)) else None

    contribution: list[ContributionItem] = []
    warnings: list[str] = []
    for position in request.positions:
        return_pct = _period_return_pct(frame, position.ticker)
        if return_pct is None:
            warnings.append(f"{position.ticker} 缺少可用历史数据，已跳过该标的贡献计算")
            contribution.append(
                ContributionItem(
                    ticker=position.ticker,
                    weight=round(position.weight, 6),
                    return_pct=None,
                    contribution_pct=None,
                )
            )
            continue

        contribution.append(
            ContributionItem(
                ticker=position.ticker,
                weight=round(position.weight, 6),
                return_pct=round(return_pct, 4),
                contribution_pct=round(return_pct * position.weight, 4),
            )
        )

    benchmark_return = _period_return_pct(frame, "SPY")
    if benchmark_return is None:
        warnings.append("SPY 缺少可用历史数据，基准收益暂不可用")

    return AttributionResponse(
        beta=beta,
        factor_exposure=factor_exposure,
        contribution=contribution,
        benchmark=BenchmarkResult(
            symbol="SPY",
            return_pct=round(benchmark_return, 4) if benchmark_return is not None else None,
        ),
        as_of=_resolve_as_of(frame),
        warnings=warnings,
    )


__all__ = ["attribution_router"]
