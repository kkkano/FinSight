# -*- coding: utf-8 -*-
from backend.graph.planner_prompt import build_planner_prompt


def test_planner_prompt_includes_allowlists_and_operation():
    state = {
        "query": "分析影响",
        "subject": {"subject_type": "news_item", "selection_payload": [{"id": "n1"}]},
        "operation": {"name": "analyze_impact", "confidence": 0.7, "params": {}},
        "output_mode": "brief",
        "policy": {"allowed_tools": ["search"], "allowed_agents": ["news_agent"], "budget": {"max_rounds": 3, "max_tools": 4}},
    }
    prompt = build_planner_prompt(state)
    assert "allowed_tools" in prompt
    assert "analyze_impact" in prompt
    assert "news_agent" in prompt
    assert "FIRST step MUST summarize selection" in prompt or "第一步必须为 summarize_selection" in prompt


def test_planner_prompt_variant_a_and_b_are_distinct_and_tagged():
    state = {
        "query": "compare AAPL MSFT",
        "subject": {"subject_type": "company", "tickers": ["AAPL", "MSFT"], "selection_payload": []},
        "operation": {"name": "compare", "confidence": 0.8, "params": {}},
        "output_mode": "brief",
        "policy": {"allowed_tools": ["get_performance_comparison"], "allowed_agents": [], "budget": {"max_rounds": 3, "max_tools": 4}},
    }
    prompt_a = build_planner_prompt(state, variant="A")
    prompt_b = build_planner_prompt(state, variant="B")

    assert "<planner_variant>A</planner_variant>" in prompt_a
    assert "<planner_variant>B</planner_variant>" in prompt_b
    assert "Variant A" in prompt_a
    assert "Variant B" in prompt_b
    assert prompt_a != prompt_b


def test_planner_prompt_includes_new_tool_allowlist_entries():
    state = {
        "query": "AAPL eps revisions and option skew",
        "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_payload": []},
        "operation": {"name": "qa", "confidence": 0.8, "params": {}},
        "output_mode": "brief",
        "policy": {
            "allowed_tools": [
                "get_earnings_estimates",
                "get_eps_revisions",
                "get_option_chain_metrics",
                "get_factor_exposure",
                "run_portfolio_stress_test",
                "get_event_calendar",
                "score_news_source_reliability",
            ],
            "allowed_agents": [],
            "budget": {"max_rounds": 3, "max_tools": 6},
        },
    }
    prompt = build_planner_prompt(state)
    for tool_name in state["policy"]["allowed_tools"]:
        assert tool_name in prompt
