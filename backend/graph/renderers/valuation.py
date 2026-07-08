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
from backend.graph.renderers.price import _format_price_line
from backend.graph.renderers.shared import _append_sources, _finalize_chat_markdown, _tickers
from backend.graph.renderers.synthesis_vars import (
    _agent_risks,
    _agent_summary,
    _python_compute_metric_lines,
    _synthesis_points,
)


def _render_valuation_sanity_markdown(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
    technical_map: dict[str, str],
    evidence_items: list[dict[str, str]],
) -> str:
    tickers = _tickers(state)
    ticker_label = ", ".join(tickers) or "这个标的"
    primary_ticker = tickers[0] if tickers else ticker_label
    price = prices.get(primary_ticker) or next(iter(prices.values()), {})
    compute_lines = _python_compute_metric_lines(state)
    fundamental = _agent_summary(state, {"fundamental_agent"})
    risk_lines = _agent_risks(state, {"risk_agent", "fundamental_agent"})
    technical = technical_map.get(primary_ticker) or next(iter(technical_map.values()), "")
    synthesis_points = _synthesis_points(state, ("valuation", "conclusion", "investment_summary"), limit=3)

    if synthesis_points:
        lines: list[str] = ["**估值结论**"]
        lines.extend(f"- {item}" for item in synthesis_points)
    else:
        lines = [
            f"**估值结论**：{ticker_label} 是否贵，不能只看股价；要把估值倍数、增长率、盈利质量和回撤风险放在一起看。",
        ]

    lines.extend(["", "**价格锚点**"])
    if price.get("price"):
        lines.append(f"- {_format_price_line(primary_ticker, price)}")
    else:
        lines.append("- [数据缺失] 本轮没有拿到可用当前报价，估值判断缺少价格锚点。")

    lines.extend(["", "**估值/增长计算指标**"])
    if compute_lines:
        for item in compute_lines[:8]:
            lines.append(f"- {item}")
    else:
        lines.append("- [数据缺失] 本轮没有可用 Python 计算指标，不能量化估值与增长是否匹配。")

    lines.extend(["", "**基本面解释**"])
    if fundamental:
        lines.append(f"- {fundamental}")
    else:
        lines.append("- 需要继续验证收入增长、利润率和 EPS 修正是否足以支撑当前估值倍数。")
    if technical:
        lines.append(f"- 技术面补充：{technical[:420]}")

    lines.extend(["", "**风险/后续观察**"])
    if risk_lines:
        for item in risk_lines[:4]:
            lines.append(f"- {item}")
    else:
        lines.append("- 若增长放缓、EPS 下修或风险偏好回落，估值倍数可能先压缩。")

    _append_sources(lines, evidence_items)
    return _finalize_chat_markdown(lines, state)


def render_valuation_sanity(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#7：valuation_sanity 操作。"""
    if "valuation_sanity" not in ctx["operations"]:
        return None
    return _render_valuation_sanity_markdown(
        state,
        prices=ctx["prices"],
        technical_map=ctx["technical_map"],
        evidence_items=ctx["evidence_items"],
    )
