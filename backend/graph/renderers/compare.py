# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/chat_renderer.py（WP3 Task1，零行为变更）。
from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import quote_plus

from backend.graph.renderers.news import _format_news_item
from backend.graph.renderers.price import _format_price_line, _price_change_pct
from backend.graph.renderers.shared import (
    _append_render_var_block,
    _append_sources,
    _finalize_chat_markdown,
    _intent_contract,
    _tickers,
    _understanding_v2,
    _v2_profiles,
)
from backend.graph.renderers.synthesis_vars import _agent_summary
from backend.graph.state import GraphState
from backend.graph.understanding_v2 import VALUATION_COMPARE_LIGHT_PROFILE


def _render_compare_or_basket_markdown(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
    news_map: dict[str, list[dict[str, str]]],
    comparison_conclusion: str,
    comparison_metrics: str,
) -> str:
    tickers = _tickers(state)
    ticker_label = ", ".join(tickers) or "这些标的"
    lines: list[str] = []

    if prices or news_map:
        lines.append(f"我先按 {ticker_label} 这组代表标的看。")
        for ticker in tickers[:6]:
            parts: list[str] = []
            price = prices.get(ticker)
            if price and price.get("price"):
                parts.append(_format_price_line(ticker, price))
            items = news_map.get(ticker) or []
            if items:
                parts.append("相关消息：" + "；".join(_format_news_item(item) for item in items[:2]))
            if parts:
                lines.append("")
                lines.append(f"{ticker}:")
                lines.extend(f"- {part}" for part in parts)

    if comparison_conclusion:
        _append_render_var_block(lines, comparison_conclusion)
    if comparison_metrics:
        _append_render_var_block(lines, comparison_metrics)
    if not comparison_conclusion and len(tickers) >= 2:
        comparable = [
            (ticker, _price_change_pct(prices.get(ticker) or {}))
            for ticker in tickers
            if _price_change_pct(prices.get(ticker) or {}) is not None
        ]
        if len(comparable) >= 2:
            ranked = sorted(comparable, key=lambda item: item[1], reverse=True)
            winner, winner_pct = ranked[0]
            runner, runner_pct = ranked[1]
            lines.append("")
            lines.append(
                f"按这次拿到的涨跌幅，{winner} 暂时更强（{winner_pct:.2f}% vs {runner} {runner_pct:.2f}%）。"
            )
        if news_map:
            lines.append("风险上先看新闻标题能不能落实到收入、利润率或指引；只靠标题还不能证明基本面已经变化。")

    if not lines:
        lines.append(f"我先按 {ticker_label} 这组标的理解。当前没有拿到足够的可引用行情或新闻，所以不硬给排序；更稳的是等价格和新闻源恢复后再比较强弱。")

    sources = [item for items in news_map.values() for item in items]
    _append_sources(lines, sources)
    return _finalize_chat_markdown(lines, state)

def _v2_requires_research_compare(state: GraphState) -> bool:
    v2 = _understanding_v2(state)
    if not v2.get("relations"):
        return False
    return VALUATION_COMPARE_LIGHT_PROFILE in _v2_profiles(state)

def _render_research_compare_markdown(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
    news_map: dict[str, list[dict[str, str]]],
    evidence_items: list[dict[str, str]],
) -> str:
    contract = _intent_contract(state)
    v2 = _understanding_v2(state)
    scope = v2.get("scope") if isinstance(v2.get("scope"), dict) else {}
    if contract:
        raw_tickers = contract.get("primary_tickers") if isinstance(contract.get("primary_tickers"), list) else _tickers(state)
        tickers = [str(ticker).strip().upper() for ticker in raw_tickers if str(ticker).strip()]
        facets = {str(item) for item in (contract.get("facets") if isinstance(contract.get("facets"), list) else [])}
        render_intent = contract.get("render_intent") if isinstance(contract.get("render_intent"), dict) else {}
        dimensions = (
            [str(item) for item in render_intent.get("dimensions") if str(item).strip()]
            if isinstance(render_intent.get("dimensions"), list)
            else []
        )
        focus = ", ".join(dimensions or sorted(facets) or ["research"])
        headline = f"Research comparison for {', '.join(tickers) or 'these tickers'}: focus={focus}."
        omitted = contract.get("omitted_tickers") if isinstance(contract.get("omitted_tickers"), list) else []
    else:
        raw_tickers = scope.get("primary_tickers") if isinstance(scope.get("primary_tickers"), list) else _tickers(state)
        tickers = [str(ticker).strip().upper() for ticker in raw_tickers if str(ticker).strip()]
        facets = {
            str(facet.get("name") or "").strip()
            for facet in (v2.get("facets") or [])
            if isinstance(facet, dict) and str(facet.get("name") or "").strip()
        }
        headline = f"Research comparison for {', '.join(tickers) or 'these tickers'}."
        omitted = scope.get("omitted_tickers") if isinstance(scope.get("omitted_tickers"), list) else []
    label = ", ".join(tickers) or "these tickers"
    lines: list[str] = [
        headline,
        "",
        "Per-ticker evidence",
    ]
    for ticker in tickers[:6]:
        lines.append(f"- {ticker}:")
        price = prices.get(ticker)
        if price and price.get("price"):
            lines.append(f"  - {_format_price_line(ticker, price)}")
        else:
            lines.append("  - [data missing] current price evidence was not available.")
        if "valuation" in facets:
            lines.append("  - Valuation evidence uses company context, earnings expectations, and fundamental review.")

    fundamental = _agent_summary(state, {"fundamental_agent"})
    if fundamental:
        lines.extend(["", "Fundamental / valuation read", f"- {fundamental}"])
    elif "valuation" in facets:
        lines.extend([
            "",
            "Valuation read",
            "- Quick valuation pass is based on current price, company context, and earnings-expectation evidence for each ticker.",
        ])

    omitted = [str(ticker).strip().upper() for ticker in omitted if str(ticker).strip()]
    if omitted:
        lines.extend(["", f"Not covered in this lightweight chat pass: {', '.join(omitted)}."])

    sources = [item for items in news_map.values() for item in items] or evidence_items
    _append_sources(lines, sources)
    return _finalize_chat_markdown(lines, state)


def render_research_compare(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#4：意图契约 compare 形态 / v2 轻量对比档案。"""
    intent_contract = _intent_contract(state)
    render_intent = intent_contract.get("render_intent") if isinstance(intent_contract.get("render_intent"), dict) else {}
    if (
        render_intent.get("shape") == "compare"
        and bool(intent_contract.get("per_ticker_required"))
    ) or _v2_requires_research_compare(state):
        return _render_research_compare_markdown(
            state,
            prices=ctx["prices"],
            news_map=ctx["news_map"],
            evidence_items=ctx["evidence_items"],
        )
    return None


def render_compare(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#10：compare 操作。"""
    if "compare" not in ctx["operations"]:
        return None
    return _render_compare_or_basket_markdown(
        state,
        prices=ctx["prices"],
        news_map=ctx["news_map"],
        comparison_conclusion=ctx["comparison_conclusion"],
        comparison_metrics=ctx["comparison_metrics"],
    )
