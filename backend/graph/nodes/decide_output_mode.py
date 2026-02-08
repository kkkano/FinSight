# -*- coding: utf-8 -*-
from __future__ import annotations

import re

from backend.graph.state import GraphState, OutputMode


_REPORT_TRIGGERS = (
    "投资报告",
    "投資報告",
    "研报",
    "研報",
    "生成报告",
    "生成報告",
    "in-depth report",
)


def decide_output_mode(state: GraphState) -> dict:
    """
    Decide output_mode with priority:
    1) UI explicit (runner sets state.output_mode)
    2) explicit words in query (strong triggers only)
    3) default: brief
    """
    explicit: OutputMode | None = state.get("output_mode")
    if explicit in ("chat", "brief", "investment_report"):
        return {"output_mode": explicit}

    query = (state.get("query") or "").strip()
    if query:
        lowered = query.lower()
        if any(token.lower() in lowered for token in _REPORT_TRIGGERS):
            return {"output_mode": "investment_report"}
        # Avoid mapping generic "分析" to report.
        if re.search(r"\\b(report)\\b", lowered) and "analysis" not in lowered:
            return {"output_mode": "investment_report"}

    return {"output_mode": "brief"}

