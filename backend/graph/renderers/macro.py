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
from backend.graph.renderers.portfolio import _portfolio_positions
from backend.graph.renderers.shared import _has_contract_facet, _subject_types, _tasks, _tickers


def _has_macro_context(state: GraphState) -> bool:
    return "macro" in _subject_types(state)

def _macro_impact_fallback_lines(state: GraphState) -> list[str]:
    tickers = _tickers(state)
    target = ", ".join(tickers[:4]) if tickers else "这个宏观问题"
    return [
        f"这轮没有合成出足够可靠的宏观影响判断，我先不硬给 {target} 下结论。",
        "可以继续补充你想看的市场、标的或时间窗口，我会按可验证证据接着分析。",
    ]

def _macro_mechanism_lines(state: GraphState) -> list[str]:
    tickers = _tickers(state)
    target = ", ".join(tickers[:4]) if tickers else "这类高估值资产"
    return [
        "利率影响估值，核心是折现率和机会成本：利率上行会降低远期现金流的现值，也会让无风险收益率更有吸引力。",
        f"所以 {target} 更敏感，后面要看利率预期是否继续压低估值倍数，以及业绩指引能不能抵消这部分压力。",
        "这类问题我不硬给单点结论，先看利率预期、业绩指引和价格反应能否互相验证。",
    ]

def _focus_task_present(state: GraphState) -> bool:
    if _portfolio_positions(state):
        return False
    for task in _tasks(state):
        if str(task.get("subject_type") or "").strip().lower() != "portfolio":
            continue
        op = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        if str(op.get("name") or "").strip().lower() == "qa":
            return True
    return False

def _focus_line(state: GraphState) -> str:
    tickers = _tickers(state)
    ticker_label = "/".join(tickers[:3]) if tickers else "相关标的"
    if _has_macro_context(state):
        return f"一句话：先关注利率和通胀预期是否继续压估值，再看 {ticker_label} 的业绩指引和价格反应能不能抵消压力。"
    return f"一句话：先关注 {ticker_label} 的价格反应是否被后续新闻、财报指引和成交量确认。"

def _external_entity_impact_fallback_lines(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
    news_map: dict[str, list[dict[str, Any]]],
) -> list[str]:
    if not _has_contract_facet(state, "external_entity_impact"):
        return []
    has_news = any(items for items in news_map.values())
    has_price = any((payload or {}).get("price") for payload in prices.values())
    lines = [
        "初步影响判断：",
        "- 这类问题要按“外部实体/主题 -> 公司基本面、估值叙事、管理层注意力、市场情绪”来拆，不应该只做概念解释。",
    ]
    if has_news:
        lines.append("- 本轮已经抓到相关新闻和行情锚点；按现有证据，更稳妥的判断是先视为间接叙事/风险影响，除非新闻或公告显示明确的收入、成本、融资、持股或监管传导。")
    else:
        lines.append("- 本轮没有抓到足够新闻证据，不能硬编直接影响结论；当前只能把它列为待验证的外部风险主题。")
    if has_price:
        lines.append("- 股价涨跌只能说明市场反应，不能单独证明因果；后续要看同一时间段是否有公司公告、权威报道或分析师下修/上修预期。")
    lines.append("- 下一步重点看：是否有跨公司资金/业务关系、管理层注意力分散、供应链/技术协同、或市场把两者叙事绑定交易。")
    return lines
