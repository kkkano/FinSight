"""Shared quote parsing & float conversion utilities.

Single source of truth — all routers/services MUST import from here.
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional


def safe_float(value: Any) -> Optional[float]:
    """Convert *value* to float; return None for invalid numbers."""
    if value is None:
        return None
    try:
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except (TypeError, ValueError):
        return None


def parse_quote_payload(payload: Any) -> dict[str, Any] | None:
    """Parse raw quote payload into ``{price, change, change_percent}``."""
    if payload is None:
        return None

    if isinstance(payload, dict):
        nested = payload.get("data")
        if nested is not None:
            inner = parse_quote_payload(nested)
            if inner:
                return inner

        price = safe_float(payload.get("price"))
        if price is not None:
            return {
                "price": price,
                "change": safe_float(payload.get("change")),
                "change_percent": safe_float(payload.get("change_percent")),
            }
        return None

    text = str(payload)
    price_match = re.search(r"Current Price:\s*\$([0-9.,]+)", text, re.IGNORECASE)
    fallback_price_match = re.search(r"\$([0-9]+(?:\.[0-9]+)?)", text)
    change_match = re.search(r"Change:\s*([+-]?[0-9.]+)", text, re.IGNORECASE)
    pct_match = re.search(r"\(([-+]?[0-9.]+)%\)", text)

    price_text = (
        price_match.group(1).replace(",", "")
        if price_match
        else (fallback_price_match.group(1) if fallback_price_match else None)
    )
    price = safe_float(price_text) if price_text else None
    if price is None:
        return None

    return {
        "price": price,
        "change": safe_float(change_match.group(1)) if change_match else None,
        "change_percent": safe_float(pct_match.group(1)) if pct_match else None,
    }


def fallback_quote_yfinance(ticker: str) -> dict[str, Any] | None:
    """Last-resort quote fetch via yfinance 5-day daily history."""
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="5d", interval="1d")
        if hist is None or hist.empty:
            return None

        close = safe_float(hist["Close"].iloc[-1])
        if close is None:
            return None

        prev_close = safe_float(hist["Close"].iloc[-2]) if len(hist) > 1 else None
        change = (close - prev_close) if prev_close not in (None, 0.0) else None
        change_pct = ((change / prev_close) * 100.0) if change is not None and prev_close else None
        return {
            "price": close,
            "change": change,
            "change_percent": change_pct,
            "source": "yfinance_fallback",
        }
    except Exception:
        return None


def resolve_live_quote(
    ticker: str,
    get_stock_price: Any = None,
) -> tuple[dict[str, Any] | None, Any]:
    """Resolve quote via tools bridge first, then yfinance fallback.

    Returns ``(parsed_quote, raw_payload)``.
    """
    raw_payload: Any = None

    if get_stock_price is not None:
        try:
            raw_payload = get_stock_price(ticker)
        except Exception:
            raw_payload = None

        parsed = parse_quote_payload(raw_payload)
        if parsed:
            parsed["source"] = "tools_bridge"
            return parsed, raw_payload

    fallback = fallback_quote_yfinance(ticker)
    if fallback:
        return fallback, raw_payload

    return None, raw_payload

