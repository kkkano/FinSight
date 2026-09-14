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
    _append_sources_for_state,
    _finalize_chat_markdown,
    _intent_contract,
    _parse_jsonish,
    _step_outputs,
    _ticker_for_step,
    _tickers,
    _understanding_v2,
    _v2_profiles,
)
from backend.graph.renderers.synthesis_vars import _agent_summary
from backend.graph.state import GraphState
from backend.graph.understanding_v2 import VALUATION_COMPARE_LIGHT_PROFILE


_VALUATION_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "market_cap": ("market_cap", "marketCap", "marketCapitalization"),
    "trailing_pe": ("trailing_pe", "trailingPE", "pe", "price_to_earnings"),
    "forward_pe": ("forward_pe", "forwardPE"),
    "price_to_book": ("price_to_book", "priceToBook", "pb"),
    "price_to_sales": ("price_to_sales", "priceToSalesTrailing12Months", "ps"),
    "ev_to_ebitda": ("ev_to_ebitda", "enterpriseToEbitda"),
}

_VALUATION_TEXT_LABELS: dict[str, tuple[str, ...]] = {
    "market_cap": ("Market Cap", "Market Capitalization"),
    "trailing_pe": ("Trailing P/E", "P/E", "PE Ratio"),
    "forward_pe": ("Forward P/E", "Forward PE"),
    "price_to_book": ("Price/Book", "Price to Book", "P/B"),
    "price_to_sales": ("Price/Sales", "Price to Sales", "P/S"),
    "ev_to_ebitda": ("EV/EBITDA", "Enterprise Value/EBITDA"),
}


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number else None
    text = str(value).strip().replace(",", "").replace("$", "")
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([KMBT])?", text, re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    scale = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get((match.group(2) or "").upper(), 1.0)
    return number * scale


def _first_number(payload: dict[str, Any], aliases: tuple[str, ...]) -> float | None:
    for alias in aliases:
        value = _as_number(payload.get(alias))
        if value is not None:
            return value
    lowered = {str(key).lower(): value for key, value in payload.items()}
    for alias in aliases:
        value = _as_number(lowered.get(alias.lower()))
        if value is not None:
            return value
    return None


def _parse_company_valuation(output: Any) -> dict[str, float]:
    parsed = _parse_jsonish(output)
    metrics: dict[str, float] = {}
    if isinstance(parsed, dict):
        for field, aliases in _VALUATION_FIELD_ALIASES.items():
            value = _first_number(parsed, aliases)
            if value is not None and value > 0:
                metrics[field] = value
        return metrics
    if not isinstance(parsed, str):
        return metrics
    for field, labels in _VALUATION_TEXT_LABELS.items():
        for label in labels:
            match = re.search(
                rf"(?:^|\n)\s*-?\s*{re.escape(label)}\s*:\s*([^\n]+)",
                parsed,
                re.IGNORECASE,
            )
            if not match:
                continue
            value = _as_number(match.group(1).strip())
            if value is not None and value > 0:
                metrics[field] = value
                break
    return metrics


def _forward_eps_from_estimates(payload: dict[str, Any]) -> tuple[float | None, str]:
    rows = payload.get("earnings_estimate")
    if not isinstance(rows, list):
        return None, ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        estimate = _first_number(
            row,
            ("avg", "avgEstimate", "epsEstimate", "currentEstimate", "mean", "consensus"),
        )
        if estimate is not None and estimate > 0:
            return estimate, str(row.get("period") or row.get("date") or "").strip()
    return None, ""


def _valuation_evidence_by_ticker(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    evidence: dict[str, dict[str, Any]] = {ticker: {} for ticker in _tickers(state)}
    for step, output in _step_outputs(state):
        name = str(step.get("name") or "")
        if name not in {"get_company_info", "get_earnings_estimates", "run_python_compute"}:
            continue
        ticker = _ticker_for_step(step, output, state)
        if not ticker:
            continue
        row = evidence.setdefault(ticker, {})
        if name == "get_company_info":
            row.update(_parse_company_valuation(output))
            continue
        parsed = _parse_jsonish(output)
        if not isinstance(parsed, dict):
            continue
        if name == "get_earnings_estimates":
            revision_signal = str(parsed.get("revision_signal") or "").strip().lower()
            if revision_signal in {"positive", "neutral", "negative"}:
                row["revision_signal"] = revision_signal
            forward_eps, period = _forward_eps_from_estimates(parsed)
            if forward_eps is not None:
                row["forward_eps"] = forward_eps
                row["forward_eps_period"] = period
            continue
        metrics = parsed.get("metrics")
        if isinstance(metrics, dict):
            for field, aliases in _VALUATION_FIELD_ALIASES.items():
                value = _first_number(metrics, aliases)
                if value is not None and value > 0:
                    row.setdefault(field, value)

    for ticker, row in evidence.items():
        if row.get("forward_pe"):
            continue
        price = _as_number((prices.get(ticker) or {}).get("price"))
        forward_eps = _as_number(row.get("forward_eps"))
        if price is not None and forward_eps is not None and forward_eps > 0:
            row["forward_pe"] = price / forward_eps
            row["forward_pe_derived"] = True
    return evidence


def _format_market_cap(value: float) -> str:
    if value >= 1e12:
        return f"${value / 1e12:.2f}T"
    if value >= 1e9:
        return f"${value / 1e9:.2f}B"
    if value >= 1e6:
        return f"${value / 1e6:.2f}M"
    return f"${value:,.0f}"


def _valuation_conclusion(tickers: list[str], evidence: dict[str, dict[str, Any]]) -> str:
    for field, label in (("forward_pe", "Forward P/E"), ("trailing_pe", "Trailing P/E")):
        comparable = [
            (ticker, _as_number(evidence.get(ticker, {}).get(field)))
            for ticker in tickers
        ]
        comparable = [(ticker, value) for ticker, value in comparable if value is not None and value > 0]
        if len(comparable) < 2:
            continue
        ranked = sorted(comparable, key=lambda item: item[1])
        winner = ranked[0][0]
        comparison = "，".join(f"{ticker} {value:.2f}x" for ticker, value in ranked)
        return (
            f"按本轮可比的 {label}，{winner} 的估值倍数更低（{comparison}）。"
            "这回答的是相对便宜程度；是否更合理仍要结合增长和盈利修正，不能只凭单一倍数下结论。"
        )
    return (
        "当前只取得价格、公司资料或盈利预期中的部分证据，缺少至少两只标的可比的 "
        "P/E、Forward P/E 或同行基准，因此这轮不能诚实判断谁的估值更合理。"
    )


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
    _append_sources_for_state(lines, sources, state)
    return _finalize_chat_markdown(lines, state)

def _v2_requires_research_compare(state: GraphState) -> bool:
    v2 = _understanding_v2(state)
    if not v2.get("relations"):
        return False
    return VALUATION_COMPARE_LIGHT_PROFILE in _v2_profiles(state)


def requires_research_compare(state: GraphState) -> bool:
    """整体比较契约必须先于逐 task 分节渲染，否则会退化成多份单股模板。"""
    intent_contract = _intent_contract(state)
    render_intent = (
        intent_contract.get("render_intent")
        if isinstance(intent_contract.get("render_intent"), dict)
        else {}
    )
    return bool(
        (
            render_intent.get("shape") == "compare"
            and intent_contract.get("per_ticker_required")
        )
        or _v2_requires_research_compare(state)
    )

def _render_research_compare_markdown(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
    news_map: dict[str, list[dict[str, str]]],
    evidence_items: list[dict[str, str]],
) -> str:
    query = str(state.get("query") or "")
    is_chinese = bool(re.search(r"[\u4e00-\u9fff]", query))
    dimension_labels_zh = {
        "valuation": "估值",
        "valuation_reasonableness": "估值合理性",
        "fundamental": "基本面",
        "earnings": "盈利",
        "technical": "技术面",
        "risk": "风险",
        "news": "新闻",
        "macro": "宏观",
        "research": "研究证据",
    }
    dimension_labels_en = {
        "valuation": "valuation",
        "valuation_reasonableness": "valuation reasonableness",
        "fundamental": "fundamentals",
        "earnings": "earnings",
        "technical": "technical signals",
        "risk": "risk",
        "news": "news",
        "macro": "macro conditions",
        "research": "research evidence",
    }
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
        focus_items = dimensions or sorted(facets) or ["research"]
        labels = dimension_labels_zh if is_chinese else dimension_labels_en
        separator = "、" if is_chinese else ", "
        focus = separator.join(labels.get(item, "相关证据" if is_chinese else "relevant evidence") for item in focus_items)
        label = ", ".join(tickers) or ("这些标的" if is_chinese else "the selected assets")
        headline = (
            f"{label} 的横向比较，重点观察{focus}。"
            if is_chinese
            else f"Comparison of {label}, with emphasis on {focus}."
        )
        omitted = contract.get("omitted_tickers") if isinstance(contract.get("omitted_tickers"), list) else []
    else:
        raw_tickers = scope.get("primary_tickers") if isinstance(scope.get("primary_tickers"), list) else _tickers(state)
        tickers = [str(ticker).strip().upper() for ticker in raw_tickers if str(ticker).strip()]
        facets = {
            str(facet.get("name") or "").strip()
            for facet in (v2.get("facets") or [])
            if isinstance(facet, dict) and str(facet.get("name") or "").strip()
        }
        label = ", ".join(tickers) or ("这些标的" if is_chinese else "the selected assets")
        headline = f"{label} 的横向比较。" if is_chinese else f"Comparison of {label}."
        omitted = scope.get("omitted_tickers") if isinstance(scope.get("omitted_tickers"), list) else []
    valuation_evidence = _valuation_evidence_by_ticker(state, prices=prices) if "valuation" in facets else {}
    lines: list[str] = [
        headline,
        "",
        "分标的证据" if is_chinese else "Evidence by asset",
    ]
    for ticker in tickers[:6]:
        lines.append(f"- {ticker}:")
        price = prices.get(ticker)
        if price and price.get("price"):
            lines.append(f"  - {_format_price_line(ticker, price)}")
        else:
            lines.append("  - 本轮未取得当前价格证据。" if is_chinese else "  - Current price evidence was unavailable.")
        if "valuation" in facets:
            valuation = valuation_evidence.get(ticker, {})
            if valuation.get("market_cap"):
                lines.append(f"  - 市值：{_format_market_cap(float(valuation['market_cap']))}")
            multiple_lines: list[str] = []
            for field, label_text in (
                ("trailing_pe", "Trailing P/E"),
                ("forward_pe", "Forward P/E"),
                ("price_to_book", "P/B"),
                ("price_to_sales", "P/S"),
                ("ev_to_ebitda", "EV/EBITDA"),
            ):
                value = _as_number(valuation.get(field))
                if value is not None and value > 0:
                    suffix = "（按价格/EPS 预期推算）" if field == "forward_pe" and valuation.get("forward_pe_derived") else ""
                    multiple_lines.append(f"{label_text} {value:.2f}x{suffix}")
            if multiple_lines:
                lines.append("  - 估值倍数：" + "；".join(multiple_lines))
            revision_signal = str(valuation.get("revision_signal") or "")
            if revision_signal:
                signal_label = {"positive": "上修", "neutral": "中性", "negative": "下修"}.get(revision_signal, revision_signal)
                lines.append(f"  - EPS 修正信号：{signal_label}")
            if not any(valuation.get(field) for field in ("trailing_pe", "forward_pe", "price_to_book", "price_to_sales", "ev_to_ebitda")):
                lines.append("  - 本轮没有取得可比较的 P/E、Forward P/E、P/B、P/S 或 EV/EBITDA。")

    fundamental = _agent_summary(state, {"fundamental_agent"})
    if "valuation" in facets:
        lines.extend(["", "估值结论", f"- {_valuation_conclusion(tickers, valuation_evidence)}"])
    if fundamental:
        lines.extend(["", "基本面补充", f"- {fundamental}"])

    omitted = [str(ticker).strip().upper() for ticker in omitted if str(ticker).strip()]
    if omitted:
        omitted_text = (
            f"本次回答未覆盖：{', '.join(omitted)}。"
            if is_chinese
            else f"Not included in this response: {', '.join(omitted)}."
        )
        lines.extend(["", omitted_text])

    sources = [item for items in news_map.values() for item in items] or evidence_items
    _append_sources_for_state(lines, sources, state)
    return _finalize_chat_markdown(lines, state)


def render_research_compare(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#4：意图契约 compare 形态 / v2 轻量对比档案。"""
    if requires_research_compare(state):
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
