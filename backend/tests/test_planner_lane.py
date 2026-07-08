# -*- coding: utf-8 -*-
"""WP2-Task9: 双 planner 边界具名化——select_planner_lane 语义与旧判定完全一致。"""
from backend.graph.planning.lane_selector import select_planner_lane


def _company_task(op_name: str, *, reason: str = "primary", params: dict | None = None) -> dict:
    return {
        "id": "t1",
        "subject_type": "company",
        "tickers": ["AAPL"],
        "operation": {"name": op_name, "confidence": 0.8, "params": params or {}},
        "reason": reason,
    }


def test_pure_price_task_uses_rule_lane():
    state = {"output_mode": "chat", "ui_context": {}}
    assert select_planner_lane(state, [_company_task("price")]) == "rule"


def test_deep_research_uses_llm_lane():
    state = {"output_mode": "chat", "ui_context": {"analysis_depth": "deep_research"}}
    assert select_planner_lane(state, [_company_task("price")]) == "llm"


def test_router_decomposed_url_evidence_graph_uses_rule_lane():
    state = {"output_mode": "chat", "ui_context": {}}
    tasks = [
        _company_task("fetch", reason="explicit_url_reference",
                      params={"url": "https://example.com/report"}),
        _company_task("qa", reason="conversation_router_task_hint"),
    ]
    assert select_planner_lane(state, tasks) == "rule"


def test_report_mode_uses_llm_lane():
    state = {"output_mode": "investment_report", "ui_context": {}}
    assert select_planner_lane(state, [_company_task("price")]) == "llm"
