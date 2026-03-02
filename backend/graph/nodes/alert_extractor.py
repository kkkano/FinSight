# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any

from backend.graph.state import GraphState

_PRICE_TARGET_RE = re.compile(
    r"(?:"
    # Chinese patterns
    r"涨到|跌到|到达|到|达到|至|"
    # English patterns - price target
    r"price\s+(?:of|at|to)|target\s+price|reaches?|hits?|"
    # English patterns - directional
    r"(?:drops?|falls?|goes?|dips?)\s+(?:below|under|to)\s*|"
    r"(?:rises?|climbs?|goes?)\s+(?:above|over|to)\s*|"
    r"(?:above|below|over|under|at)\s*"
    r")\s*"
    r"(?P<price>\d+(?:\.\d+)?)\s*(?:元|块|美元|dollars?|usd|\$)?",
    re.IGNORECASE,
)

_PCT_THRESHOLD_RE = re.compile(
    r"(?:"
    # Chinese patterns
    r"涨|跌|上涨|下跌|变动|超过|涨跌超过|"
    # English patterns
    r"(?:rises?|drops?|falls?|moves?|changes?|fluctuates?)\s*(?:by\s*)?|"
    r"(?:up|down)\s*(?:by\s*)?|"
    r"(?:more\s+than|exceeds?|over)\s*"
    r")\s*"
    r"(?P<pct>\d+(?:\.\d+)?)\s*(?:%|percent|个点|pct)",
    re.IGNORECASE,
)


def _pick_ticker(state: GraphState) -> str | None:
    subject = state.get("subject") or {}
    tickers = subject.get("tickers") if isinstance(subject, dict) else None
    if isinstance(tickers, list) and tickers:
        first = str(tickers[0] or "").strip().upper()
        if first:
            return first

    ui_context = state.get("ui_context") or {}
    active_symbol = str((ui_context.get("active_symbol") if isinstance(ui_context, dict) else "") or "").strip().upper()
    return active_symbol or None


def _extract_direction(query: str) -> str | None:
    lowered = str(query or "").lower()
    below_tokens = ("跌到", "跌破", "低于", "小于", "below", "under", "<=")
    above_tokens = ("涨到", "突破", "高于", "大于", "above", "over", ">=")

    if any(token in lowered for token in below_tokens):
        return "below"
    if any(token in lowered for token in above_tokens):
        return "above"
    return None


def alert_extractor(state: GraphState) -> dict[str, Any]:
    query = str(state.get("query") or "").strip()
    ticker = _pick_ticker(state)

    price_target_match = _PRICE_TARGET_RE.search(query)
    pct_match = _PCT_THRESHOLD_RE.search(query)

    alert_params: dict[str, Any] = {
        "ticker": ticker,
        "alert_mode": None,
        "price_target": None,
        "price_threshold": None,
        "direction": None,
    }

    if price_target_match:
        alert_params["alert_mode"] = "price_target"
        alert_params["price_target"] = float(price_target_match.group("price"))
        alert_params["direction"] = _extract_direction(query)
    elif pct_match:
        alert_params["alert_mode"] = "price_change_pct"
        alert_params["price_threshold"] = float(pct_match.group("pct"))

    missing: list[str] = []
    if not ticker:
        missing.append("ticker")
    if not alert_params["alert_mode"]:
        missing.append("trigger")

    if missing:
        reason = "缺少标的代码" if "ticker" in missing else "缺少提醒阈值"
        if "ticker" in missing and "trigger" in missing:
            reason = "缺少标的代码和提醒阈值"
        draft = (
            "我可以帮你设置提醒，但还缺少必要信息。\n"
            f"- 问题：{reason}\n"
            "- 示例1：`AAPL 涨到 220 美元提醒我` / `Alert me when AAPL hits 220`\n"
            "- 示例2：`平安银行 涨跌超过 3% 提醒我` / `Notify me if TSLA moves 5%`"
        )
        return {
            "alert_valid": False,
            "alert_params": alert_params,
            "clarify": {
                "needed": True,
                "reason": "alert_missing_required_fields",
                "question": draft,
                "suggestions": [
                    "输入 ticker + 到价，例如 AAPL 涨到 220 美元提醒我",
                    "输入 ticker + 涨跌幅，例如 NVDA 涨跌超过 4% 提醒我",
                    "English: Alert me when AAPL drops below 180",
                    "English: Notify me if TSLA rises 10 percent",
                ],
            },
            "artifacts": {"draft_markdown": draft},
        }

    return {
        "alert_valid": True,
        "alert_params": alert_params,
    }


__all__ = ["alert_extractor"]
