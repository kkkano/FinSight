from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import ScreenerRunRequest
from backend.tools.screener import screen_stocks


screener_router = APIRouter(tags=["Screener"])


@screener_router.post("/api/screener/run")
def run_screener(payload: ScreenerRunRequest):
    result = screen_stocks(
        market=payload.market,
        filters=payload.filters,
        limit=payload.limit,
        page=payload.page,
        sort_by=payload.sort_by,
        sort_order=payload.sort_order,
    )
    return result


@screener_router.get("/api/screener/filters/meta")
def get_screener_filter_meta():
    return {
        "success": True,
        "markets": ["US", "CN", "HK"],
        "sort_by": ["marketCap", "price", "volume", "beta", "lastAnnualDividend", "changesPercentage"],
        "sort_order": ["asc", "desc"],
        "filter_keys": [
            "exchange",
            "country",
            "sector",
            "industry",
            "isEtf",
            "isActivelyTrading",
            "marketCapMoreThan",
            "marketCapLowerThan",
            "priceMoreThan",
            "priceLowerThan",
            "betaMoreThan",
            "betaLowerThan",
            "volumeMoreThan",
            "dividendMoreThan",
        ],
        "source": "fmp_stock_screener",
    }


__all__ = ["screener_router"]
