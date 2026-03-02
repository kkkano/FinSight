from __future__ import annotations

import logging
from typing import Any

import yfinance as yf

from backend.tools.env import FMP_API_KEY
from backend.tools.http import _http_get

logger = logging.getLogger(__name__)

_FMP_SCREENER_URL = "https://financialmodelingprep.com/api/v3/stock-screener"
_ALLOWED_SORT_BY = {
    "marketCap",
    "price",
    "volume",
    "beta",
    "lastAnnualDividend",
    "changesPercentage",
}
_ALLOWED_SORT_ORDER = {"asc", "desc"}

# Yahoo Finance predefined screener keys by market
_YF_SCREENER_MAP = {
    "US": "most_actives",  # Most active US stocks
    "CN": "most_actives",  # Fallback - yfinance doesn't have CN-specific
    "HK": "most_actives",  # Fallback
}


def _yfinance_screen_stocks(
    market: str,
    filters: dict[str, Any] | None,
    limit: int,
    sort_by: str,
    sort_order: str,
) -> dict[str, Any]:
    """Fallback screener using yfinance when FMP is unavailable."""
    market_norm = str(market or "US").strip().upper()

    try:
        # Use yfinance Screener for predefined screens
        screener_key = _YF_SCREENER_MAP.get(market_norm, "most_actives")
        screener = yf.Screener()
        screener.set_predefined_body(screener_key)

        response = screener.response
        if not response or "quotes" not in response:
            # Fallback to a list of popular tickers
            return _yfinance_popular_stocks(market_norm, limit, sort_by, sort_order)

        quotes = response.get("quotes", [])
        items: list[dict[str, Any]] = []

        for quote in quotes[:limit]:
            if not isinstance(quote, dict):
                continue
            symbol = str(quote.get("symbol") or "").strip().upper()
            if not symbol:
                continue

            # Apply basic filters if provided
            if filters:
                price = _clean_float(quote.get("regularMarketPrice"))
                market_cap = _clean_float(quote.get("marketCap"))

                if filters.get("priceMoreThan") and price and price < float(filters["priceMoreThan"]):
                    continue
                if filters.get("priceLowerThan") and price and price > float(filters["priceLowerThan"]):
                    continue
                if filters.get("marketCapMoreThan") and market_cap and market_cap < float(filters["marketCapMoreThan"]):
                    continue
                if filters.get("marketCapLowerThan") and market_cap and market_cap > float(filters["marketCapLowerThan"]):
                    continue

            items.append({
                "symbol": symbol,
                "name": str(quote.get("shortName") or quote.get("longName") or "").strip() or symbol,
                "sector": quote.get("sector"),
                "industry": quote.get("industry"),
                "country": None,
                "exchange": quote.get("exchange"),
                "price": _clean_float(quote.get("regularMarketPrice")),
                "market_cap": _clean_float(quote.get("marketCap")),
                "volume": _clean_float(quote.get("regularMarketVolume")),
                "beta": None,
                "dividend": _clean_float(quote.get("trailingAnnualDividendRate")),
                "change_percent": _clean_float(quote.get("regularMarketChangePercent")),
            })

        # Sort items
        sort_key_map = {
            "marketCap": "market_cap",
            "price": "price",
            "volume": "volume",
            "changesPercentage": "change_percent",
        }
        py_sort_key = sort_key_map.get(sort_by, "market_cap")
        reverse = sort_order == "desc"
        items.sort(key=lambda x: x.get(py_sort_key) or 0, reverse=reverse)

        return {
            "success": True,
            "market": market_norm,
            "items": items[:limit],
            "count": len(items[:limit]),
            "source": "yfinance_screener",
            "capability_note": "Using Yahoo Finance screener as fallback (FMP unavailable)",
        }
    except Exception as exc:
        logger.warning("yfinance screener failed: %s", exc)
        return _yfinance_popular_stocks(market_norm, limit, sort_by, sort_order)


def _yfinance_popular_stocks(
    market: str,
    limit: int,
    sort_by: str,
    sort_order: str,
) -> dict[str, Any]:
    """Fetch data for popular stocks when screener API fails."""
    # Popular US large-cap tickers
    popular_tickers = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
        "UNH", "JNJ", "V", "XOM", "JPM", "WMT", "PG", "MA", "HD", "CVX",
        "MRK", "ABBV", "LLY", "PFE", "KO", "PEP", "COST", "AVGO", "TMO",
        "MCD", "CSCO", "ACN", "ABT", "DHR", "NKE", "ORCL", "VZ", "ADBE",
    ]

    try:
        tickers = yf.Tickers(" ".join(popular_tickers[:limit * 2]))
        items: list[dict[str, Any]] = []

        for symbol in popular_tickers[:limit * 2]:
            try:
                ticker = tickers.tickers.get(symbol)
                if not ticker:
                    continue
                info = ticker.fast_info
                items.append({
                    "symbol": symbol,
                    "name": symbol,  # fast_info doesn't have name
                    "sector": None,
                    "industry": None,
                    "country": "US",
                    "exchange": None,
                    "price": _clean_float(getattr(info, "last_price", None)),
                    "market_cap": _clean_float(getattr(info, "market_cap", None)),
                    "volume": _clean_float(getattr(info, "last_volume", None)),
                    "beta": None,
                    "dividend": None,
                    "change_percent": None,
                })
            except Exception:
                continue

        # Sort
        sort_key_map = {"marketCap": "market_cap", "price": "price", "volume": "volume"}
        py_sort_key = sort_key_map.get(sort_by, "market_cap")
        reverse = sort_order == "desc"
        items.sort(key=lambda x: x.get(py_sort_key) or 0, reverse=reverse)

        return {
            "success": True,
            "market": market,
            "items": items[:limit],
            "count": len(items[:limit]),
            "source": "yfinance_popular",
            "capability_note": "Using popular US stocks fallback",
        }
    except Exception as exc:
        logger.warning("yfinance popular stocks failed: %s", exc)
        return {
            "success": False,
            "market": market,
            "items": [],
            "count": 0,
            "error": f"yfinance_fallback_failed: {exc}",
            "source": "yfinance_popular",
        }


def _clean_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _clean_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _build_market_filters(market: str) -> dict[str, str]:
    m = str(market or "US").strip().upper()
    if m == "CN":
        return {"country": "CN"}
    if m == "HK":
        return {"exchange": "HKSE"}
    return {}


def screen_stocks(
    *,
    market: str = "US",
    filters: dict[str, Any] | None = None,
    limit: int = 20,
    page: int = 1,
    sort_by: str = "marketCap",
    sort_order: str = "desc",
) -> dict[str, Any]:
    """Run FMP stock screener with simple market-aware filters."""
    market_norm = str(market or "US").strip().upper()
    capability_note = None
    if market_norm in {"CN", "HK"}:
        capability_note = "CN/HK coverage is limited in FMP screener; empty or partial results are expected for some symbols."

    if not FMP_API_KEY:
        # No FMP key configured, use yfinance directly
        logger.info("FMP_API_KEY not configured, using yfinance screener")
        return _yfinance_screen_stocks(market_norm, filters, limit_norm, sort_key, sort_dir)

    limit_norm = _clean_int(limit, default=20, minimum=1, maximum=200)
    page_norm = _clean_int(page, default=1, minimum=1, maximum=100)

    sort_key = str(sort_by or "marketCap").strip()
    if sort_key not in _ALLOWED_SORT_BY:
        sort_key = "marketCap"
    sort_dir = str(sort_order or "desc").strip().lower()
    if sort_dir not in _ALLOWED_SORT_ORDER:
        sort_dir = "desc"

    payload_filters = filters if isinstance(filters, dict) else {}
    params: dict[str, Any] = {
        "apikey": FMP_API_KEY,
        "limit": limit_norm,
        "offset": (page_norm - 1) * limit_norm,
        "order": sort_dir,
        "sort": sort_key,
    }
    params.update(_build_market_filters(market))

    passthrough_keys = {
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
    }
    for key, value in payload_filters.items():
        if key not in passthrough_keys:
            continue
        if value is None or value == "":
            continue
        params[key] = value

    try:
        response = _http_get(_FMP_SCREENER_URL, params=params, timeout=15)
        if getattr(response, "status_code", 0) != 200:
            # FMP failed, try yfinance fallback
            logger.info("FMP screener returned %s, falling back to yfinance", getattr(response, "status_code", "unknown"))
            return _yfinance_screen_stocks(market_norm, payload_filters, limit_norm, sort_key, sort_dir)
        raw = response.json()
        # Check for FMP legacy endpoint error
        if isinstance(raw, dict) and "Error Message" in raw:
            logger.info("FMP legacy endpoint deprecated, falling back to yfinance")
            return _yfinance_screen_stocks(market_norm, payload_filters, limit_norm, sort_key, sort_dir)
        if not isinstance(raw, list):
            # Could be error response, fallback to yfinance
            logger.info("FMP returned non-list response, falling back to yfinance")
            return _yfinance_screen_stocks(market_norm, payload_filters, limit_norm, sort_key, sort_dir)

        items: list[dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            items.append(
                {
                    "symbol": symbol,
                    "name": str(row.get("companyName") or row.get("company") or "").strip() or symbol,
                    "sector": row.get("sector"),
                    "industry": row.get("industry"),
                    "country": row.get("country"),
                    "exchange": row.get("exchangeShortName") or row.get("exchange"),
                    "price": _clean_float(row.get("price")),
                    "market_cap": _clean_float(row.get("marketCap")),
                    "volume": _clean_float(row.get("volume")),
                    "beta": _clean_float(row.get("beta")),
                    "dividend": _clean_float(row.get("lastAnnualDividend")),
                    "change_percent": _clean_float(row.get("changesPercentage")),
                }
            )

        return {
            "success": True,
            "market": market_norm,
            "filters": payload_filters,
            "sort": {"by": sort_key, "order": sort_dir},
            "page": page_norm,
            "limit": limit_norm,
            "items": items,
            "count": len(items),
            "source": "fmp_stock_screener",
            "warning": None if items else ("coverage_limited_or_empty_result" if capability_note else "empty_result"),
            "capability_note": capability_note,
        }
    except Exception as exc:
        logger.warning("screen_stocks FMP failed: %s, trying yfinance fallback", exc)
        return _yfinance_screen_stocks(market_norm, payload_filters, limit_norm, sort_key, sort_dir)


__all__ = ["screen_stocks"]
