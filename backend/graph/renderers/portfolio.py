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
    _append_render_var_block,
    _finalize_chat_markdown,
    _tasks,
    _tickers,
)
from backend.graph.renderers.synthesis_vars import _render_vars, _useful_render_var


def _portfolio_positions(state: GraphState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in _tasks(state):
        if str(task.get("subject_type") or "").strip().lower() != "portfolio":
            continue
        params = task.get("params") if isinstance(task.get("params"), dict) else {}
        positions = params.get("positions") if isinstance(params.get("positions"), list) else []
        for item in positions:
            if isinstance(item, dict) and str(item.get("ticker") or "").strip():
                rows.append(item)
    if rows:
        return rows

    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    raw = ui_context.get("positions") or ui_context.get("holdings") or ui_context.get("portfolio")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict) and str(item.get("ticker") or item.get("symbol") or "").strip()]
    if isinstance(raw, dict):
        normalized: list[dict[str, Any]] = []
        for key, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("ticker", key)
                normalized.append(item)
            else:
                normalized.append({"ticker": key, "weight": value})
        return normalized
    return []

def _render_portfolio_markdown(state: GraphState) -> str:
    positions = _portfolio_positions(state)
    tickers = _tickers(state)
    render_vars = _render_vars(state)
    analysis_block = (
        _useful_render_var(render_vars, "impact_analysis")
        or _useful_render_var(render_vars, "conclusion")
        or _useful_render_var(render_vars, "investment_summary")
    )
    risks = _useful_render_var(render_vars, "risks")
    label = ", ".join(tickers[:6]) if tickers else "当前持仓"
    lines = [f"我先按你给的持仓看：{label}。"]
    if positions:
        lines.append("")
        lines.append("持仓锚点：")
        for item in positions[:8]:
            ticker = str(item.get("ticker") or item.get("symbol") or "").strip().upper()
            weight = item.get("weight")
            if weight is None:
                lines.append(f"- {ticker}")
            else:
                lines.append(f"- {ticker}: 权重约 {weight}")
    if analysis_block:
        _append_render_var_block(lines, analysis_block)
    elif risks:
        _append_render_var_block(lines, risks)
    else:
        lines.extend(
            [
                "",
                "这轮还缺少可验证的持仓影响证据，我不会按固定框架硬编单条新闻冲击。",
                "你可以补充新闻、持仓权重或时间窗口，我会按证据继续判断。",
            ]
        )
    return _finalize_chat_markdown(lines, state)


def render_portfolio(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#2：portfolio 任务（有持仓上下文，或全部任务都是 portfolio）。"""
    portfolio_tasks = [
        task
        for task in _tasks(state)
        if str(task.get("subject_type") or "").strip().lower() == "portfolio"
    ]
    non_portfolio_tasks = [
        task
        for task in _tasks(state)
        if str(task.get("subject_type") or "").strip().lower() != "portfolio"
    ]
    if portfolio_tasks and (_portfolio_positions(state) or not non_portfolio_tasks):
        return _render_portfolio_markdown(state)
    return None
