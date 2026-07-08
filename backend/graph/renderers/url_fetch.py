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
from backend.graph.renderers.macro import (
    _focus_line,
    _focus_task_present,
    _has_macro_context,
    _macro_mechanism_lines,
)
from backend.graph.renderers.price import _format_price_line
from backend.graph.renderers.shared import (
    _append_render_var_block,
    _append_sources,
    _finalize_chat_markdown,
    _parse_jsonish,
    _step_outputs,
    _tasks,
    _ticker_for_step,
    _tickers,
)
from backend.graph.renderers.synthesis_vars import _useful_render_var


def _url_fetch_rows(state: GraphState) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") != "fetch_url_content":
            continue
        parsed = _parse_jsonish(output)
        inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
        url = str(inputs.get("url") or "").strip()
        title = ""
        snippet = ""
        error = ""
        if isinstance(parsed, dict):
            url = str(parsed.get("final_url") or parsed.get("url") or url).strip()
            title = str(parsed.get("title") or "").strip()
            snippet = str(parsed.get("content") or parsed.get("text") or parsed.get("snippet") or "").strip()
            error = str(parsed.get("error") or "").strip()
        elif isinstance(parsed, str):
            snippet = parsed.strip()
        rows.append(
            {
                "ticker": _ticker_for_step(step, output, state),
                "url": url,
                "title": title,
                "snippet": snippet[:420],
                "error": error,
            }
        )
    return rows

def _append_url_fetch_notes(lines: list[str], state: GraphState) -> None:
    rows = _url_fetch_rows(state)
    if not rows:
        return
    if lines and lines[-1] != "":
        lines.append("")
    for row in rows[:3]:
        label = row.get("title") or row.get("ticker") or "这个链接"
        url = row.get("url") or ""
        error = row.get("error") or ""
        snippet = row.get("snippet") or ""
        if error:
            detail = f"（{error}）" if error else ""
            if url:
                if label == "这个链接":
                    lines.append(f"我试着读取这个链接，但这次没有拿到可读正文{detail}：{url}。所以我先不把它当作支持证据，需要换成可访问正文后再判断。")
                else:
                    lines.append(f"我试着读取 {label}，但这次没有拿到可读正文{detail}：{url}。所以我先不把它当作支持证据，需要换成可访问正文后再判断。")
            else:
                lines.append(f"我试着读取{label}，但这次没有拿到可读正文{detail}，所以我先不把它当作支持证据。")
        elif snippet:
            linked = f"[{row.get('title') or url}]({url})" if url else (row.get("title") or label)
            lines.append(f"{label} 相关链接我已读到正文，先看这点：{linked}，{snippet}")

def _url_fetch_all_failed(state: GraphState) -> bool:
    rows = _url_fetch_rows(state)
    if not rows:
        return False
    return not any((row.get("snippet") or "").strip() and not (row.get("error") or "").strip() for row in rows)

def _has_url_context(state: GraphState) -> bool:
    if _url_fetch_rows(state):
        return True
    for task in _tasks(state):
        operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        params = operation.get("params") if isinstance(operation.get("params"), dict) else {}
        if str(params.get("url") or "").startswith(("http://", "https://")):
            return True
    return False


def render_url_context(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#3：URL 上下文（用户给了链接）。"""
    if not ctx["has_url_context"]:
        return None
    prices = ctx["prices"]
    render_vars = ctx["render_vars"]
    next_watch = ctx["next_watch"]
    news = ctx["news"]
    evidence_items = ctx["evidence_items"]
    lines: list[str] = []
    for ticker in (_tickers(state) or list(prices.keys()))[:5]:
        ticker_price = prices.get(ticker)
        if ticker_price:
            lines.append(_format_price_line(ticker, ticker_price))
    _append_url_fetch_notes(lines, state)
    analysis_block = (
        _useful_render_var(render_vars, "impact_analysis")
        or _useful_render_var(render_vars, "conclusion")
        or _useful_render_var(render_vars, "investment_summary")
    )
    has_other_answerable_tasks = bool(
        prices
        or analysis_block
        or next_watch
        or _has_macro_context(state)
        or _focus_task_present(state)
    )
    if _url_fetch_all_failed(state) and not has_other_answerable_tasks:
        if not lines:
            lines.append("URL fetch failed; no readable content was available, so I will not infer from the URL text alone.")
        return _finalize_chat_markdown(lines, state)
    if analysis_block:
        if lines and lines[-1] != "":
            lines.append("")
        _append_render_var_block(lines, analysis_block)
    if _has_macro_context(state):
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(_macro_mechanism_lines(state))
    if lines and "关注" not in "\n".join(lines):
        lines.append("")
        lines.append(_focus_line(state))
    if not lines:
        lines.append("这个链接和宏观问题需要更多可读证据；我先不按 URL 字面内容硬下结论。")
    _append_sources(lines, news or evidence_items)
    return _finalize_chat_markdown(lines, state)
