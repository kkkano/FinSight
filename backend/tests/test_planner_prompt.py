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
    assert "FIRST step MUST summarize selection" in prompt

