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
from backend.graph.renderers.news import _filter_news_by_company_identity, _format_news_item
from backend.graph.renderers.price import _format_price_line
from backend.graph.renderers.shared import (
    _append_sources,
    _case_insensitive_get,
    _finalize_chat_markdown,
    _first_matching_output,
    _parse_jsonish,
    _tickers,
)
from backend.graph.renderers.synthesis_vars import (
    _agent_risks,
    _agent_summary,
    _format_compact_number,
    _python_compute_metric_lines,
    _synthesis_points,
)


def _latest_quarter_facts(state: GraphState) -> list[str]:
    payload = _first_matching_output(state, {"get_sec_company_facts_quarterly"})
    parsed = _parse_jsonish(payload)
    if isinstance(parsed, dict) and not parsed.get("error"):
        periods = parsed.get("periods") if isinstance(parsed.get("periods"), list) else []
        period_label = str(periods[0] if periods else "最新季度").strip() or "最新季度"
        metric_specs = (
            ("revenue", "营收", True),
            ("gross_profit", "毛利", True),
            ("operating_income", "经营利润", True),
            ("net_income", "净利润", True),
            ("eps", "EPS", False),
            ("operating_cash_flow", "经营现金流", True),
            ("free_cash_flow", "自由现金流", True),
        )

        lines: list[str] = []
        for key, label, money in metric_specs:
            values = parsed.get(key)
            if not isinstance(values, list) or not values:
                continue
            formatted = _format_compact_number(values[0], money=money)
            if formatted:
                lines.append(f"{period_label} {label} {formatted}")
            if len(lines) >= 4:
                break
        if lines:
            return lines
    return _local_filing_fact_lines(state)

def _local_filing_fact_lines(state: GraphState) -> list[str]:
    payload = _first_matching_output(state, {"get_local_market_filings"})
    parsed = _parse_jsonish(payload)
    if not isinstance(parsed, dict) or parsed.get("error"):
        return []
    filings = parsed.get("filings") if isinstance(parsed.get("filings"), list) else []
    lines: list[str] = []
    for filing in filings:
        if not isinstance(filing, dict):
            continue
        title = str(filing.get("title") or filing.get("form") or "本地交易所公告").strip()
        description = str(
            filing.get("primary_doc_description")
            or filing.get("summary")
            or filing.get("snippet")
            or ""
        ).strip()
        date = str(filing.get("filing_date") or filing.get("date") or filing.get("published_at") or "").strip()
        line = " ".join(part for part in (date, title) if part)
        if description and description not in line:
            line = f"{line}：{description}" if line else description
        if line:
            lines.append(line)
        if len(lines) >= 3:
            break
    return lines

def _earnings_expectation_lines(state: GraphState) -> list[str]:
    lines: list[str] = []
    estimates = _parse_jsonish(_first_matching_output(state, {"get_earnings_estimates"}))
    if isinstance(estimates, dict) and not estimates.get("error"):
        rows = estimates.get("earnings_estimate")
        if isinstance(rows, list) and rows:
            first = rows[0] if isinstance(rows[0], dict) else {}
            avg = first.get("avg") or first.get("current") or first.get("estimate")
            period = str(first.get("period") or "下一季").strip() or "下一季"
            if avg is not None:
                lines.append(f"{period} 共识 EPS 约 {_format_compact_number(avg)}")
        signal = str(estimates.get("revision_signal") or "").strip()
        if signal:
            lines.append(f"盈利预期修正信号：{signal}")

    revisions = _parse_jsonish(_first_matching_output(state, {"get_eps_revisions"}))
    if isinstance(revisions, dict) and not revisions.get("error"):
        rows = revisions.get("eps_revisions")
        if isinstance(rows, list) and rows:
            first = rows[0] if isinstance(rows[0], dict) else {}
            up = _case_insensitive_get(first, "upLast7days")
            down = _case_insensitive_get(first, "downLast7days")
            if up is not None or down is not None:
                lines.append(f"近 7 天 EPS 上修 {up or 0} 次、下修 {down or 0} 次")
        signal = str(revisions.get("revision_signal") or "").strip()
        if signal and all(signal not in line for line in lines):
            lines.append(f"EPS 修正信号：{signal}")

    return lines[:4]

def _render_earnings_performance_markdown(
    state: GraphState,
    *,
    news_map: dict[str, list[dict[str, str]]],
    evidence_items: list[dict[str, str]],
) -> str:
    tickers = _tickers(state)
    ticker_label = ", ".join(tickers) or "这个标的"
    financial_lines = _latest_quarter_facts(state)
    expectation_lines = _earnings_expectation_lines(state)
    fundamental = _agent_summary(state, {"fundamental_agent"})
    news = _filter_news_by_company_identity(state, [item for items in news_map.values() for item in items])
    synthesis_points = _synthesis_points(state, ("conclusion", "impact_analysis"), limit=3)

    if synthesis_points:
        lines: list[str] = ["**结论**"]
        lines.extend(f"- {item}" for item in synthesis_points)
        lines.extend(["", "**最新季度/财务表现**"])
    else:
        lines = [
            f"**结论**：{ticker_label} 的财报表现需要同时看财务事实、盈利预期/EPS 修正和管理层指引。",
            "",
            "**最新季度/财务表现**",
        ]
    if financial_lines:
        for item in financial_lines:
            lines.append(f"- {item}")
    elif fundamental:
        lines.append(f"- {fundamental}")
    else:
        lines.append("- [数据缺失] 本轮没有拿到季度财务事实表，不能硬编营收、利润或 EPS。")

    if fundamental and financial_lines:
        lines.append(f"- {fundamental}")

    lines.extend(["", "**盈利预期/EPS 修正**"])
    if expectation_lines:
        for item in expectation_lines:
            lines.append(f"- {item}")
    else:
        lines.append("- [数据缺失] 本轮没有拿到盈利预期或 EPS 修正数据，无法判断市场预期是否继续上修。")

    lines.extend(["", "**消息/指引**"])
    if news:
        for item in news[:3]:
            lines.append(f"- {_format_news_item(item)}")
    else:
        lines.append("- [数据缺失] 本轮没有可引用的财报新闻、电话会或指引来源，事件解释需要保守。")

    lines.extend(["", "**风险/待验证**"])
    risk_lines = _agent_risks(state, {"fundamental_agent", "news_agent"})
    if risk_lines:
        for item in risk_lines[:4]:
            lines.append(f"- {item}")
    else:
        lines.append("- 重点验证下一季指引、毛利率/净利率变化和 EPS 修正方向；如果预期上修停止，财报利好可能被估值压力抵消。")

    _append_sources(lines, news or evidence_items)
    return _finalize_chat_markdown(lines, state)

def _render_earnings_impact_markdown(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
    news_map: dict[str, list[dict[str, str]]],
    evidence_items: list[dict[str, str]],
) -> str:
    tickers = _tickers(state)
    ticker_label = ", ".join(tickers) or "这个标的"
    primary_ticker = tickers[0] if tickers else ticker_label
    price = prices.get(primary_ticker) or next(iter(prices.values()), {})
    financial_lines = _latest_quarter_facts(state)
    expectation_lines = _earnings_expectation_lines(state)
    compute_lines = _python_compute_metric_lines(state)
    fundamental = _agent_summary(state, {"fundamental_agent"})
    risk_lines = _agent_risks(state, {"risk_agent", "fundamental_agent", "news_agent"})
    news = _filter_news_by_company_identity(state, [item for items in news_map.values() for item in items])
    synthesis_points = _synthesis_points(state, ("conclusion", "impact_analysis"), limit=3)

    if synthesis_points:
        lines: list[str] = ["**结论**"]
        lines.extend(f"- {item}" for item in synthesis_points)
        lines.extend(["", "**股价反应**"])
    else:
        lines = [
            f"**结论**：{ticker_label} 的财报对股价影响，要同时看“财报/指引是否超预期”和“股价是否已经反映”。本轮按财报事实、EPS 修正、股价反应和风险触发来判断。",
            "",
            "**股价反应**",
        ]
    if price.get("price"):
        lines.append(f"- {_format_price_line(primary_ticker, price)}")
    else:
        lines.append("- [数据缺失] 本轮没有拿到可用当前报价，无法量化市场即时反应。")

    lines.extend(["", "**财报/预期差**"])
    if financial_lines:
        for item in financial_lines:
            lines.append(f"- {item}")
    elif fundamental:
        lines.append("- 本轮 SEC 季度事实表不可用，先用基本面 Agent 的财务摘要作为替代证据。")
    else:
        lines.append("- [数据缺失] 本轮没有拿到季度财务事实表，不能硬判断财报本身是利好还是利空。")
    if fundamental:
        lines.append(f"- {fundamental}")

    lines.extend(["", "**盈利预期/EPS 修正**"])
    if expectation_lines:
        for item in expectation_lines:
            lines.append(f"- {item}")
    else:
        lines.append("- [数据缺失] 本轮没有拿到盈利预期或 EPS 修正，无法确认市场预期是否上修。")

    if compute_lines:
        lines.extend(["", "**计算指标**"])
        for item in compute_lines[:6]:
            lines.append(f"- {item}")

    lines.extend(["", "**消息/指引**"])
    if news:
        for item in news[:3]:
            lines.append(f"- {_format_news_item(item)}")
    else:
        lines.append("- [数据缺失] 本轮没有可引用的财报新闻、电话会或指引来源，事件解释需要保守。")

    lines.extend(["", "**风险/后续观察**"])
    if risk_lines:
        for item in risk_lines[:4]:
            lines.append(f"- {item}")
    else:
        lines.append("- 重点看下一季指引、毛利率、EPS 修正和股价是否放量确认；若预期上修停滞，短线利好可能被估值压力抵消。")

    _append_sources(lines, news or evidence_items)
    return _finalize_chat_markdown(lines, state)


def render_earnings_impact(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#5：earnings_impact 操作。"""
    if "earnings_impact" not in ctx["operations"]:
        return None
    return _render_earnings_impact_markdown(
        state,
        prices=ctx["prices"],
        news_map=ctx["news_map"],
        evidence_items=ctx["evidence_items"],
    )


def render_earnings_performance(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#6：earnings_performance 操作。"""
    if "earnings_performance" not in ctx["operations"]:
        return None
    return _render_earnings_performance_markdown(
        state,
        news_map=ctx["news_map"],
        evidence_items=ctx["evidence_items"],
    )
