# -*- coding: utf-8 -*-
from backend.graph.request_facets import derive_request_facets
from backend.graph.nodes.policy_gate import policy_gate


def _state(query: str, operation_name: str, ticker: str = "NVDA") -> dict:
    subject = {
        "subject_type": "company",
        "tickers": [ticker],
        "selection_ids": [],
        "selection_types": [],
        "selection_payload": [],
    }
    operation = {"name": operation_name, "confidence": 0.9, "params": {}}
    return {
        "query": query,
        "operation": operation,
        "output_mode": "chat",
        "subject": subject,
        "facets": derive_request_facets(query=query, operation=operation, subject=subject),
    }


def test_policy_selects_earnings_skill_without_hard_filtering_agents():
    result = policy_gate(_state("请问英伟达这个季度财报对股价的影响", "earnings_impact"))
    policy = result["policy"]
    selection = policy.get("skill_selection") or {}

    assert selection.get("selected_skill") == "earnings-impact-investigator"
    assert "run_python_compute" in policy.get("allowed_tools", [])
    assert {"fundamental_agent", "news_agent", "risk_agent"}.issubset(set(policy.get("allowed_agents", [])))


def test_policy_selects_valuation_skill_from_facets():
    result = policy_gate(_state("NVDA 现在估值贵不贵，和增长匹配吗", "valuation_sanity"))
    policy = result["policy"]
    selection = policy.get("skill_selection") or {}

    assert selection.get("selected_skill") == "valuation-sanity-check"
    assert "run_python_compute" in policy.get("allowed_tools", [])
    assert {"fundamental_agent", "technical_agent", "risk_agent"}.issubset(set(policy.get("allowed_agents", [])))
    assert policy["budget"]["max_tools"] >= 8


def test_policy_keeps_price_short_path_without_skill():
    result = policy_gate(_state("NVDA 当前价格是多少", "price"))
    policy = result["policy"]

    assert (policy.get("skill_selection") or {}).get("selected_skill") is None
    assert "run_python_compute" not in policy.get("allowed_tools", [])
    assert policy.get("allowed_agents") == []
