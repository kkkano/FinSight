# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.state import GraphState, OutputMode


_REPORT_TRIGGERS = (
    "投资报告",
    "投資報告",
    "研报",
    "研報",
    "生成报告",
    "生成報告",
    "investment report",
    "research report",
    "generate report",
    "generate a report",
    "create report",
    "create a report",
    "write report",
    "write a report",
    "full report",
    "complete report",
    "deep report",
    "in-depth report",
)

_NEGATED_REPORT_TRIGGERS = (
    "do not generate a report",
    "do not generate report",
    "don't generate a report",
    "don't generate report",
    "dont generate a report",
    "dont generate report",
    "do not create a report",
    "do not create report",
    "don't create a report",
    "don't create report",
    "dont create a report",
    "dont create report",
    "do not write a report",
    "do not write report",
    "don't write a report",
    "don't write report",
    "dont write a report",
    "dont write report",
    "do not make a report",
    "do not make report",
    "don't make a report",
    "don't make report",
    "dont make a report",
    "dont make report",
    "do not output a report",
    "do not output report",
    "don't output a report",
    "don't output report",
    "dont output a report",
    "dont output report",
    "not a report",
    "no report format",
    "without a report",
    "without report",
)


def decide_output_mode(state: GraphState) -> dict:
    """
    Decide output_mode with priority:
    1) UI explicit (runner sets state.output_mode)
    2) explicit words in query (strong triggers only)
    3) default: chat
    """
    explicit: OutputMode | None = state.get("output_mode")
    if explicit in ("chat", "brief", "investment_report"):
        return {"output_mode": explicit}

    query = (state.get("query") or "").strip()
    if query:
        lowered = query.lower()
        if any(token in lowered for token in _NEGATED_REPORT_TRIGGERS):
            return {"output_mode": "chat"}
        if any(token.lower() in lowered for token in _REPORT_TRIGGERS):
            return {"output_mode": "investment_report"}
    return {"output_mode": "chat"}
