from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from backend.api.schemas import KlineResponse, StockDataResponse


@dataclass(frozen=True)
class MarketRouterDeps:
    get_market_data_gateway: Callable[[], Any]
    logger: Any


_TICKER_PATTERN = re.compile(r"^[A-Z0-9^][A-Z0-9.^=-]{0,19}$")


def _validate_ticker_or_400(raw_ticker: str) -> str:
    ticker = str(raw_ticker or "").strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker 不能为空")
    if not _TICKER_PATTERN.fullmatch(ticker):
        raise HTTPException(status_code=400, detail=f"ticker 格式非法: {raw_ticker}")
    return ticker


def create_market_router(deps: MarketRouterDeps) -> APIRouter:
    """可信 quote、news、financials 与 Kline 数据网关。"""
    router = APIRouter(tags=["Market"])

    @router.get("/api/stock/price/{ticker}", response_model=StockDataResponse)
    def get_price(ticker: str):
        normalized = _validate_ticker_or_400(ticker)
        try:
            result = deps.get_market_data_gateway().get_quote(normalized)
            return {"ticker": normalized, "data": result, "cached": bool(result.get("cached"))}
        except Exception as exc:
            deps.logger.warning("[Market] quote unavailable ticker=%s error_type=%s", normalized, type(exc).__name__)
            return {
                "ticker": normalized,
                "data": {"data": {}, "error": "market_data_unavailable", "error_code": "market_data_unavailable"},
                "cached": False,
            }

    @router.get("/api/stock/news/{ticker}", response_model=StockDataResponse)
    def get_news(ticker: str, limit: int = 5):
        normalized = _validate_ticker_or_400(ticker)
        try:
            result = deps.get_market_data_gateway().get_news(normalized, limit=max(1, min(50, limit)))
            return {"ticker": normalized, "data": result, "cached": bool(result.get("cached"))}
        except Exception as exc:
            deps.logger.warning("[Market] news unavailable ticker=%s error_type=%s", normalized, type(exc).__name__)
            return {
                "ticker": normalized,
                "data": {"data": [], "error": "market_data_unavailable", "error_code": "market_data_unavailable"},
                "cached": False,
            }

    @router.get("/api/financials/{ticker}", response_model=StockDataResponse)
    def get_financials(ticker: str):
        normalized = _validate_ticker_or_400(ticker)
        try:
            result = deps.get_market_data_gateway().get_financials(normalized)
            return {"ticker": normalized, "data": result, "cached": bool(result.get("cached"))}
        except Exception as exc:
            deps.logger.warning(
                "[Market] financials unavailable ticker=%s error_type=%s",
                normalized,
                type(exc).__name__,
            )
            return {
                "ticker": normalized,
                "data": {"data": {}, "error": "market_data_unavailable", "error_code": "market_data_unavailable"},
                "cached": False,
            }

    @router.get("/api/stock/kline/{ticker}", response_model=KlineResponse)
    def get_kline_data(ticker: str, period: str = "1y", interval: str = "1d"):
        normalized = _validate_ticker_or_400(ticker)
        try:
            result = deps.get_market_data_gateway().get_kline(
                normalized,
                period=period,
                interval=interval,
            )
            return {"ticker": normalized, "data": result, "cached": bool(result.get("cached"))}
        except Exception as exc:
            deps.logger.warning("[Market] kline unavailable ticker=%s error_type=%s", normalized, type(exc).__name__)
            return {
                "ticker": normalized,
                "data": {
                    "data": [],
                    "kline_data": [],
                    "error": "market_data_unavailable",
                    "error_code": "market_data_unavailable",
                },
                "cached": False,
            }

    return router


__all__ = ["MarketRouterDeps", "create_market_router"]
