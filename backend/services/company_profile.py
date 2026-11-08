"""公开公司头部与估值字段，按标的缓存，缺失字段保持空值。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
import time

_cache: dict[str, tuple[float, dict]] = {}
_pending: dict[str, asyncio.Task] = {}


def _fetch(ticker: str) -> dict:
    from backend.tools.yfinance_client import create_ticker
    info = create_ticker(ticker).get_info()
    if not isinstance(info, dict) or not (info.get("longName") or info.get("shortName")):
        raise ValueError("company_profile_missing")
    def value(key):
        item = info.get(key)
        return item if type(item) in {float, int} and math.isfinite(item) else None
    stamp = value("regularMarketTime")
    annual_dividend, market_price = value("trailingAnnualDividendRate"), value("regularMarketPrice")
    dividend_yield = annual_dividend / market_price if annual_dividend is not None and market_price is not None and market_price > 0 else None
    return {"ticker": ticker, "status": "ok", "name": info.get("longName") or info.get("shortName"),
            "name_zh": None, "exchange": info.get("fullExchangeName") or info.get("exchange"),
            "market_cap": value("marketCap"), "pe_ratio": value("trailingPE"), "dividend_yield": dividend_yield,
            "dividend_yield_basis": "trailing_annual_dividend_rate_over_price" if dividend_yield is not None else None,
            "currency": info.get("currency"), "source": "yfinance", "source_url": f"https://finance.yahoo.com/quote/{ticker}/profile/",
            "as_of": datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp is not None else None,
            "observed_at": datetime.now(timezone.utc).isoformat()}


async def company_profile(ticker: str) -> dict:
    cached = _cache.get(ticker)
    if cached and cached[0] > time.monotonic():
        return {**cached[1], "cached": True}
    async def fetch():
        try:
            result = await asyncio.wait_for(asyncio.to_thread(_fetch, ticker), timeout=12)
        except Exception:
            result = {"ticker": ticker, "status": "unavailable", "name": None, "name_zh": None, "exchange": None,
                      "market_cap": None, "pe_ratio": None, "dividend_yield": None, "source": "yfinance", "as_of": None,
                      "reason": "Yahoo Finance 暂未返回公司资料"}
        if len(_cache) >= 256:
            _cache.pop(next(iter(_cache)))
        _cache[ticker] = (time.monotonic() + (300 if result["status"] == "ok" else 30), result)
        return {**result, "cached": False}
    task = _pending.get(ticker)
    if task is None:
        task = asyncio.create_task(fetch())
        _pending[ticker] = task
        task.add_done_callback(lambda done: _pending.pop(ticker, None) if _pending.get(ticker) is done else None)
    return await asyncio.shield(task)
