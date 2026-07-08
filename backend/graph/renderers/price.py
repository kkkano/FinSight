# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/chat_renderer.py（WP3 Task1，零行为变更）。
from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import quote_plus

from backend.graph.state import GraphState
from backend.graph.renderers.shared import (
    _finalize_chat_markdown,
    _first_matching_output,
    _format_number,
    _parse_jsonish,
    _step_outputs,
    _ticker_for_step,
    _tickers,
)
from backend.utils.quote import parse_quote_payload


def _extract_price(output: Any) -> dict[str, Any]:
    parsed = _parse_jsonish(output)
    if isinstance(parsed, list) and parsed:
        parsed = parsed[0]
    parsed_quote = parse_quote_payload(parsed)
    if parsed_quote:
        parsed_quote["currency"] = "USD"
        if isinstance(parsed, dict):
            data = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
            parsed_quote["currency"] = data.get("currency") or data.get("financialCurrency") or "USD"
            parsed_quote["as_of"] = data.get("as_of") or data.get("timestamp") or data.get("regularMarketTime")
        return parsed_quote
    if isinstance(parsed, str):
        parsed_quote = parse_quote_payload(parsed)
        if parsed_quote:
            parsed_quote["currency"] = "USD"
            return parsed_quote
    if not isinstance(parsed, dict):
        return {}

    data = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
    price = (
        data.get("price")
        or data.get("current_price")
        or data.get("currentPrice")
        or data.get("regularMarketPrice")
        or data.get("close")
    )
    change = data.get("change") or data.get("regularMarketChange")
    change_pct = (
        data.get("change_percent")
        or data.get("changePercent")
        or data.get("regularMarketChangePercent")
    )
    currency = data.get("currency") or data.get("financialCurrency") or "USD"
    as_of = data.get("as_of") or data.get("timestamp") or data.get("regularMarketTime")
    return {
        "price": price,
        "change": change,
        "change_percent": change_pct,
        "currency": currency,
        "as_of": as_of,
    }

def _format_price_line(ticker: str, price: dict[str, Any]) -> str:
    if not price.get("price"):
        return f"{ticker} 的实时价格这次没有拿到可用报价。可以稍后重试，或切到行情页确认最新成交价。"

    parts = [f"{ticker} 最新价格约为 {_format_number(price['price'])} {price.get('currency') or 'USD'}"]
    change = price.get("change")
    change_pct = price.get("change_percent") if "change_percent" in price else price.get("change_pct")
    if change is not None or change_pct is not None:
        move = []
        if change is not None:
            move.append(_format_number(change))
        if change_pct is not None:
            pct = _format_number(change_pct)
            if pct and not pct.endswith("%"):
                pct += "%"
            move.append(pct)
        if move:
            parts.append("，变动 " + " / ".join(move))
    if price.get("as_of"):
        parts.append(f"。数据时间：{price['as_of']}")
    else:
        parts.append("。")
    return "".join(parts)

def _price_change_pct(price: dict[str, Any]) -> float | None:
    raw = price.get("change_percent") if "change_percent" in price else price.get("change_pct")
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw or "").strip().replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None

def _prices_by_ticker(state: GraphState) -> dict[str, dict[str, Any]]:
    prices: dict[str, dict[str, Any]] = {}
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") not in {"get_stock_price", "price_agent"}:
            continue
        ticker = _ticker_for_step(step, output, state)
        price = _extract_price(output)
        if ticker and price:
            prices[ticker] = price
    if not prices:
        first = _first_matching_output(state, {"get_stock_price", "price_agent"})
        price = _extract_price(first)
        tickers = _tickers(state)
        if price and tickers:
            prices[tickers[0]] = price
    return prices


def render_price_only(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#9：纯价格问询（无 fetch/technical/analyze_impact 伴随）。"""
    operations = ctx["operations"]
    if not ("price" in operations and "fetch" not in operations and "technical" not in operations and "analyze_impact" not in operations):
        return None
    prices = ctx["prices"]
    price = ctx["price"]
    ticker_label = ctx["ticker_label"]
    lines: list[str] = []
    target_tickers = _tickers(state) or list(prices.keys()) or [ticker_label]
    for ticker in target_tickers[:5]:
        ticker_price = prices.get(ticker, price if len(target_tickers) == 1 else {})
        lines.append(_format_price_line(ticker, ticker_price))
    return _finalize_chat_markdown(lines, state)
