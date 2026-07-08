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
from backend.graph.renderers.misc import _technical_action_line
from backend.graph.renderers.news import _format_news_item
from backend.graph.renderers.price import _format_price_line, _price_change_pct
from backend.graph.renderers.shared import _append_sources, _finalize_chat_markdown, _tickers
from backend.graph.renderers.synthesis_vars import _agent_risks, _agent_summary


def _investment_opinion_bias(price: dict[str, Any], technical: str, risk_lines: list[str]) -> str:
    score = 0
    change_pct = _price_change_pct(price)
    if change_pct is not None:
        if change_pct >= 1.0:
            score += 1
        elif change_pct <= -1.0:
            score -= 1
    tech_text = str(technical or "")
    if any(token in tech_text for token in ("偏强", "上升趋势", "多头排列", "多头")):
        score += 1
    if any(token in tech_text for token in ("偏弱", "下降趋势", "空头排列", "空头")):
        score -= 1
    risk_text = " ".join(str(item or "") for item in risk_lines).lower()
    controlled_risk = any(
        token in risk_text
        for token in ("可控", "中等", "未触发", "没有触及", "尚未", "moderate", "controlled", "contained")
    )
    elevated_risk = any(
        token in risk_text
        for token in (
            "高风险",
            "风险较高",
            "显著",
            "急剧",
            "已跌破",
            "跌破支撑",
            "破位",
            "趋势转弱",
            "下修",
            "监管",
            "elevated",
            "high risk",
            "bearish",
        )
    )
    if elevated_risk and not controlled_risk:
        score -= 1
    if score >= 2:
        return "中性偏多"
    if score <= -2:
        return "偏谨慎"
    return "中性观察"

def _render_investment_opinion_markdown(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
    news_map: dict[str, list[dict[str, str]]],
    technical_map: dict[str, str],
    evidence_items: list[dict[str, str]],
) -> str:
    tickers = _tickers(state)
    ticker_label = ", ".join(tickers) or "这个标的"
    primary_ticker = tickers[0] if tickers else ticker_label
    price = prices.get(primary_ticker) or next(iter(prices.values()), {})
    technical = technical_map.get(primary_ticker) or next(iter(technical_map.values()), "")
    news = [item for items in news_map.values() for item in items]
    fundamental = _agent_summary(state, {"fundamental_agent"})
    risk_summary = _agent_summary(state, {"risk_agent"})
    risk_lines = _agent_risks(state, {"risk_agent", "fundamental_agent", "technical_agent"})
    bias = _investment_opinion_bias(price, technical, risk_lines)

    lines: list[str] = [
        f"**结论**：{ticker_label} 这轮先按「{bias}」处理；这不是买卖指令，核心取决于技术位、盈利验证和风险触发是否同时改善。",
        "",
        "**价格/趋势**",
    ]
    if price.get("price"):
        lines.append(f"- {_format_price_line(primary_ticker, price)}")
    else:
        lines.append("- [数据缺失] 本轮未取得可用当前报价，方向判断缺少价格锚点。")

    lines.extend(["", "**技术面**"])
    if technical:
        lines.append(f"- {technical}")
        action_line = _technical_action_line(primary_ticker, technical)
        if action_line:
            lines.append(f"- {action_line}")
    else:
        lines.append("- [数据缺失] 本轮未取得趋势、动量、支撑阻力等技术证据，不能只凭新闻判断走势。")

    lines.extend(["", "**消息/催化**"])
    if news:
        for item in news[:3]:
            lines.append(f"- {_format_news_item(item)}")
    else:
        lines.append("- [数据缺失] 本轮未取得可引用的近期新闻或事件日历，催化判断需要保守。")

    lines.extend(["", "**基本面/估值**"])
    if fundamental:
        lines.append(f"- {fundamental}")
    else:
        lines.append("- [数据缺失] 本轮未取得基本面、盈利预期或估值证据，不能支持强买入/强卖出结论。")

    lines.extend(["", "**风险**"])
    if risk_lines:
        for item in risk_lines:
            lines.append(f"- {item}")
    elif risk_summary:
        lines.append(f"- {risk_summary}")
    else:
        lines.append("- [数据缺失] 本轮未取得回撤、波动或因子风险证据；仓位建议需要等待风险模块补齐。")

    _append_sources(lines, news or evidence_items)
    return _finalize_chat_markdown(lines, state)


def render_investment_opinion(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#11：investment_opinion 操作。"""
    if "investment_opinion" not in ctx["operations"]:
        return None
    return _render_investment_opinion_markdown(
        state,
        prices=ctx["prices"],
        news_map=ctx["news_map"],
        technical_map=ctx["technical_map"],
        evidence_items=ctx["evidence_items"],
    )
