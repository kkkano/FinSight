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
from backend.graph.renderers.news import _format_news_item
from backend.graph.renderers.price import _format_price_line
from backend.graph.renderers.shared import (
    _append_render_var_block,
    _append_sources_for_state,
    _finalize_chat_markdown,
    _format_number,
    _parse_jsonish,
    _risk_or_qa_fallback_lines,
    _step_outputs,
    _ticker_for_step,
    _tickers,
)


def _technical_text(output: Any) -> str:
    parsed = _parse_jsonish(output)
    if isinstance(parsed, str):
        return parsed.strip()[:700]
    if not isinstance(parsed, dict):
        return ""
    if parsed.get("summary"):
        return str(parsed["summary"]).strip()[:700]
    parts: list[str] = []
    for key, label in (
        ("rsi14", "RSI(14)"),
        ("macd", "MACD"),
        ("macd_signal", "MACD signal"),
        ("ma20", "MA20"),
        ("ma50", "MA50"),
        ("ma200", "MA200"),
        ("support", "支撑"),
        ("resistance", "阻力"),
        ("trend", "趋势"),
    ):
        value = parsed.get(key)
        if value is not None:
            parts.append(f"{label}: {_format_number(value)}")
    return "；".join(parts[:8])

def _technical_action_line(ticker: str, text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    support_match = re.search(r"支撑\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)", cleaned)
    resistance_match = re.search(r"阻力\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)", cleaned)
    support = support_match.group(1) if support_match else ""
    resistance = resistance_match.group(1) if resistance_match else ""
    if any(marker in cleaned for marker in ("偏强", "上升趋势", "多头排列")):
        bias = "偏强"
    elif any(marker in cleaned for marker in ("偏弱", "下降趋势", "空头排列")):
        bias = "偏弱"
    elif "空头" in cleaned:
        bias = "信号有分歧"
    else:
        bias = "中性"

    if support and resistance:
        return (
            f"可执行结论：{ticker} 技术状态{bias}；接近阻力 {resistance} 不追高，"
            f"放量突破后再上调目标；回踩支撑 {support} 不破再考虑低吸，跌破则降低仓位或止损。"
        )
    if support:
        return f"可执行结论：{ticker} 技术状态{bias}；先盯支撑 {support}，跌破则降低仓位，站稳后再看量能确认。"
    if resistance:
        return f"可执行结论：{ticker} 技术状态{bias}；先盯阻力 {resistance}，未放量突破前避免追高。"
    return f"可执行结论：{ticker} 技术状态{bias}；等价格、MACD 和成交量同向确认后再加仓，信号冲突时控制仓位。"

def _technical_by_ticker(state: GraphState) -> dict[str, str]:
    rows: dict[str, str] = {}
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") not in {"get_technical_snapshot", "technical_agent"}:
            continue
        ticker = _ticker_for_step(step, output, state)
        text = _technical_text(output)
        if ticker and text:
            rows[ticker] = text
    return rows


def render_last_report_followup(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#1：绑定 last_report 的跟聊。"""
    last_report = ctx["last_report"]
    binding = ctx["binding"]
    if not (last_report and binding.get("source") == "last_report"):
        return None
    title = str(last_report.get("title") or "刚才那份报告").strip()
    summary = str(last_report.get("summary") or "").strip()
    risks = last_report.get("risks") if isinstance(last_report.get("risks"), list) else []
    lines = [f"可以，按《{title}》继续聊。"]
    if risks:
        lines.append("")
        lines.append("这份报告里最需要先看的风险是：")
        for item in risks[:4]:
            text = str(item or "").strip()
            if text:
                lines.append(f"- {text}")
    elif summary:
        lines.append("")
        lines.append(summary[:700])
    else:
        lines.append("")
        lines.append("我已经拿到这份报告的会话引用，但摘要不完整；你可以直接问要展开的章节或风险点。")
    return _finalize_chat_markdown(lines, state)


def render_technical(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#13：technical 操作。"""
    operations = ctx["operations"]
    if "technical" not in operations:
        return None
    ticker_label = ctx["ticker_label"]
    technical_map = ctx["technical_map"]
    technical = ctx["technical"]
    price_snapshot = ctx["price_snapshot"]
    technical_snapshot = ctx["technical_snapshot"]
    conclusion = ctx["conclusion"]
    lines: list[str] = []
    if price_snapshot:
        _append_render_var_block(lines, price_snapshot)
    if technical_map:
        for ticker, text in list(technical_map.items())[:4]:
            lines.append(f"{ticker} 技术面结论：{text}")
            action_line = _technical_action_line(ticker, text)
            if action_line:
                lines.append(action_line)
        if conclusion:
            _append_render_var_block(lines, conclusion)
    elif technical:
        lines.append(f"{ticker_label} 技术面结论：{technical}")
        action_line = _technical_action_line(ticker_label, technical)
        if action_line:
            lines.append(action_line)
    elif technical_snapshot:
        _append_render_var_block(lines, technical_snapshot)
    else:
        lines.append(f"这次没有拿到 {ticker_label} 的可用技术指标数据，所以我不能给出 RSI、MACD 或支撑阻力的具体数值。可以稍后重试，或先用 K 线页确认最新行情。")
    return _finalize_chat_markdown(lines, state)


def render_default(state: GraphState, ctx: dict[str, Any]) -> str:
    """原分支#14：末端兜底链（恒返回）。"""
    query = ctx["query"]
    ticker_label = ctx["ticker_label"]
    operations = ctx["operations"]
    artifacts = ctx["artifacts"]
    price = ctx["price"]
    news = ctx["news"]
    evidence_items = ctx["evidence_items"]
    risks = ctx["risks"]
    comparison_conclusion = ctx["comparison_conclusion"]
    conclusion = ctx["conclusion"]
    lines: list[str] = []
    if price.get("price"):
        lines.append(_format_price_line(ticker_label, price))
    elif news:
        lines.append(f"我找到了 {ticker_label} 的几条相关信息，核心先看事件是否改变业绩预期：")
        for item in news[:3]:
            lines.append(f"- {item['title']}")
        _append_sources_for_state(lines, news, state)
    elif evidence_items:
        lines.append(f"我先按 {ticker_label} 相关来源给你看要点：")
        for item in evidence_items[:4]:
            lines.append(f"- {_format_news_item(item)}")
        _append_sources_for_state(lines, evidence_items, state)
    elif risks:
        lines.extend(_risk_or_qa_fallback_lines(state, risks))
    elif comparison_conclusion:
        _append_render_var_block(lines, comparison_conclusion)
        if risks:
            _append_render_var_block(lines, risks)
    elif "daily_brief" in operations:
        lines.append(f"{ticker_label} 先给你一个很短的快评。")
        if conclusion:
            lines.append(conclusion)
        elif risks:
            lines.append(risks)
        else:
            lines.append("这次还没拿到足够的实时数据，我会继续看价格和新闻后再补一句判断。")
    elif conclusion:
        lines.append(conclusion)
    else:
        existing = artifacts.get("draft_markdown")
        if isinstance(existing, str) and existing.strip():
            lines.append(existing.strip())
        else:
            target = f"（{ticker_label}）" if _tickers(state) else ""
            lines.append(f"我理解你的问题是：{query or '继续分析'}{target}。这次可用数据不足，我会先保留上下文；你可以继续补充标的、时间范围或想看的维度。")
    return _finalize_chat_markdown(lines, state)
