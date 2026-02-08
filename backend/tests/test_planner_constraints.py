# -*- coding: utf-8 -*-
from backend.graph.nodes.planner_stub import planner_stub


def test_planner_includes_selection_summary_step_first_when_selection_present():
    state = {
        "query": "分析影响",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.7, "params": {}},
        "subject": {
            "subject_type": "news_item",
            "tickers": [],
            "selection_ids": ["n1"],
            "selection_types": ["news"],
            "selection_payload": [{"type": "news", "id": "n1", "title": "t", "snippet": "s"}],
        },
        "policy": {"budget": {"max_rounds": 3, "max_tools": 4}, "allowed_tools": ["search"]},
    }
    result = planner_stub(state)
    plan = result.get("plan_ir") or {}
    steps = plan.get("steps") or []
    assert steps, "planner should add at least selection summary step"
    assert steps[0].get("name") == "summarize_selection"
    assert steps[0].get("kind") == "llm"


def test_planner_does_not_add_report_fill_steps_when_not_investment_report_mode():
    state = {
        "query": "分析影响",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.7, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "policy": {"budget": {"max_rounds": 3, "max_tools": 4}, "allowed_tools": ["get_company_info"]},
    }
    plan = (planner_stub(state).get("plan_ir") or {})
    names = [s.get("name") for s in (plan.get("steps") or [])]
    assert not any("report" in (n or "") for n in names)


def test_planner_no_selection_no_summary_step():
    state = {
        "query": "分析影响",
        "output_mode": "brief",
        "operation": {"name": "qa", "confidence": 0.5, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "policy": {"budget": {"max_rounds": 3, "max_tools": 4}, "allowed_tools": []},
    }
    plan = (planner_stub(state).get("plan_ir") or {})
    names = [s.get("name") for s in (plan.get("steps") or [])]
    assert "summarize_selection" not in names

