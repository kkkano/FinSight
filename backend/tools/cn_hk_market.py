from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

from backend.utils.quote import safe_float

from .http import _http_get

logger = logging.getLogger(__name__)

_EASTMONEY_USER_AGENT = os.getenv("EASTMONEY_USER_AGENT", "Mozilla/5.0 (FinSight)")
_EASTMONEY_TIMEOUT = int(os.getenv("EASTMONEY_TIMEOUT", "12"))
_EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"


def detect_market(ticker: str) -> str:
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return "UNKNOWN"
    if symbol.endswith((".SS", ".SZ", ".BJ")):
        return "CN"
    if symbol.endswith(".HK"):
        return "HK"
    return "UNKNOWN"


def normalize_ticker(ticker: str) -> str:
    return str(ticker or "").strip().upper()


def ticker_to_eastmoney_secid(ticker: str) -> str | None:
    symbol = normalize_ticker(ticker)
    market = detect_market(symbol)
    if market == "CN":
        if symbol.endswith(".SS"):
            return f"1.{symbol[:-3]}"
        if symbol.endswith(".SZ") or symbol.endswith(".BJ"):
            return f"0.{symbol[:-3]}"
        return None
    if market == "HK":
        core = re.sub(r"\D", "", symbol[:-3])
        if not core:
            return None
        return f"116.{core.zfill(5)}"
    return None


def _eastmoney_get_json(url: str, params: dict[str, Any], timeout: int | None = None) -> dict[str, Any] | None:
    try:
        resp = _http_get(
            url,
            params=params,
            timeout=int(timeout or _EASTMONEY_TIMEOUT),
            headers={"User-Agent": _EASTMONEY_USER_AGENT},
        )
        if getattr(resp, "status_code", 0) != 200:
            return None
        payload = resp.json()
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        logger.info("[CNHK] eastmoney request failed for %s: %s", url, exc)
        return None


def _price_from_raw(value: Any, decimals: int) -> Optional[float]:
    raw = safe_float(value)
    if raw is None:
        return None
    scale = 10 ** max(0, min(decimals, 6))
    if scale <= 0:
        scale = 100
    return raw / scale


def _percent_div_100(value: Any) -> Optional[float]:
    raw = safe_float(value)
    if raw is None:
        return None
    return raw / 100.0


def fetch_cn_hk_quote_metrics(ticker: str) -> dict[str, Any] | None:
    ticker_norm = normalize_ticker(ticker)
    market = detect_market(ticker_norm)
    if market not in {"CN", "HK"}:
        return None

    secid = ticker_to_eastmoney_secid(ticker_norm)
    if not secid:
        return None

    payload = _eastmoney_get_json(
        _EASTMONEY_QUOTE_URL,
        {
            "secid": secid,
            "fields": "f43,f57,f58,f59,f116,f162,f167,f170,f168,f169,f174,f175",
        },
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None

    decimals = int(safe_float(data.get("f59")) or 2)
    result = {
        "symbol": ticker_norm,
        "market": market,
        "name": str(data.get("f58") or "").strip() or ticker_norm,
        "last_price": _price_from_raw(data.get("f43"), decimals),
        "market_cap": safe_float(data.get("f116")),
        "trailing_pe": _percent_div_100(data.get("f162")),
        "forward_pe": None,
        "price_to_book": _percent_div_100(data.get("f167")),
        "price_to_sales": None,
        "ev_to_ebitda": None,
        "dividend_yield": None,
        "beta": None,
        "week52_high": _price_from_raw(data.get("f174"), decimals),
        "week52_low": _price_from_raw(data.get("f175"), decimals),
        "source": "eastmoney_quote",
    }
    if all(
        result.get(key) is None
        for key in (
            "last_price",
            "market_cap",
            "trailing_pe",
            "price_to_book",
            "week52_high",
            "week52_low",
        )
    ):
        return None
    return result


__all__ = [
    "detect_market",
    "normalize_ticker",
    "ticker_to_eastmoney_secid",
    "fetch_cn_hk_quote_metrics",
]
