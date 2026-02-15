# -*- coding: utf-8 -*-
from backend.graph.nodes.policy_gate import policy_gate


def test_policy_gate_outputs_budget_and_allowed_tools():
    result = policy_gate(
        {
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
            "output_mode": "investment_report",
        }
    )
    policy = result.get("policy") or {}
    budget = policy.get("budget") or {}
    allowed_agents = policy.get("allowed_agents") or []
    assert budget.get("max_rounds") == 6
    assert budget.get("max_tools") == 8
    assert "get_stock_price" in (policy.get("allowed_tools") or [])
    assert {"price_agent", "news_agent", "fundamental_agent"}.issubset(set(allowed_agents))
    assert len(allowed_agents) >= 1


def test_policy_gate_includes_tool_schemas_for_allowed_tools():
    result = policy_gate(
        {
            "subject": {
                "subject_type": "news_item",
                "tickers": [],
                "selection_ids": ["n1"],
                "selection_types": ["news"],
                "selection_payload": [{"type": "news", "id": "n1"}],
            },
            "output_mode": "brief",
        }
    )
    policy = result.get("policy") or {}
    schemas = policy.get("tool_schemas") or {}
    assert isinstance(schemas, dict)
    # We must at least provide schema entries for the allowlist (even if empty dict).
    for name in policy.get("allowed_tools") or []:
        assert name in schemas

    agent_schemas = policy.get("agent_schemas") or {}
    assert isinstance(agent_schemas, dict)
    for name in policy.get("allowed_agents") or []:
        assert name in agent_schemas


def test_policy_gate_company_technical_allowlist_is_tight_and_includes_technical_snapshot():
    result = policy_gate(
        {
            "subject": {
                "subject_type": "company",
                "tickers": ["NVDA"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
            "operation": {"name": "technical", "confidence": 0.9, "params": {}},
            "output_mode": "brief",
        }
    )
    policy = result.get("policy") or {}
    tools = policy.get("allowed_tools") or []
    assert "get_stock_price" in tools
    assert "get_technical_snapshot" in tools
    assert "get_company_news" not in tools, "technical mode should not default to news tools"


def test_policy_gate_company_compare_allowlist_includes_performance_comparison():
    result = policy_gate(
        {
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL", "MSFT"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
            "operation": {"name": "compare", "confidence": 0.9, "params": {}},
            "output_mode": "brief",
        }
    )
    policy = result.get("policy") or {}
    tools = policy.get("allowed_tools") or []
    assert "get_performance_comparison" in tools
    assert "get_stock_price" not in tools, "compare mode should not default to single-stock price tool"


def test_policy_gate_company_compare_brief_disables_agents_by_default():
    result = policy_gate(
        {
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL", "MSFT"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
            "operation": {"name": "compare", "confidence": 0.9, "params": {}},
            "output_mode": "brief",
        }
    )
    policy = result.get("policy") or {}
    assert (policy.get("allowed_agents") or []) == []


def test_policy_gate_company_report_deep_query_includes_deep_search_agent():
    result = policy_gate(
        {
            "query": "Deep research for AAPL and generate investment report",
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
            "operation": {"name": "generate_report", "confidence": 0.9, "params": {}},
            "output_mode": "investment_report",
        }
    )
    policy = result.get("policy") or {}
    allowed_agents = policy.get("allowed_agents") or []
    assert "deep_search_agent" in allowed_agents


def test_policy_gate_agents_override_takes_priority():
    """agents_override from ui_context should override automatic agent selection."""
    result = policy_gate(
        {
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
            "output_mode": "investment_report",
            "ui_context": {
                "agents_override": ["price_agent", "news_agent"],
            },
        }
    )
    policy = result.get("policy") or {}
    allowed_agents = policy.get("allowed_agents") or []
    assert allowed_agents == ["price_agent", "news_agent"]


def test_policy_gate_agents_override_rejects_unknown_agents():
    """Unknown agent names in agents_override should be silently filtered."""
    result = policy_gate(
        {
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
            "output_mode": "investment_report",
            "ui_context": {
                "agents_override": ["price_agent", "fake_agent", "news_agent"],
            },
        }
    )
    policy = result.get("policy") or {}
    allowed_agents = policy.get("allowed_agents") or []
    assert allowed_agents == ["price_agent", "news_agent"]
    assert "fake_agent" not in allowed_agents


def test_policy_gate_budget_override():
    """budget_override in ui_context should override default budget."""
    result = policy_gate(
        {
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
            "output_mode": "investment_report",
            "ui_context": {
                "budget_override": 8,
            },
        }
    )
    policy = result.get("policy") or {}
    budget = policy.get("budget") or {}
    assert budget.get("max_rounds") == 8


def test_policy_gate_budget_override_clamped():
    """budget_override exceeding range should be clamped to [1, 10]."""
    result = policy_gate(
        {
            "subject": {"subject_type": "unknown", "tickers": []},
            "output_mode": "brief",
            "ui_context": {"budget_override": 99},
        }
    )
    budget = (result.get("policy") or {}).get("budget") or {}
    assert budget.get("max_rounds") == 10


def test_policy_gate_agent_preferences_off_removes_agent():
    """agent_preferences with depth='off' should remove the agent."""
    result = policy_gate(
        {
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
            "output_mode": "investment_report",
            "ui_context": {
                "agent_preferences": {
                    "agents": {
                        "macro_agent": "off",
                    },
                },
            },
        }
    )
    policy = result.get("policy") or {}
    allowed_agents = policy.get("allowed_agents") or []
    assert "macro_agent" not in allowed_agents


def test_policy_gate_agent_preferences_invalid_depth_ignored():
    """Invalid depth values in preferences should be treated as 'standard'."""
    result = policy_gate(
        {
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
            "output_mode": "investment_report",
            "ui_context": {
                "agent_preferences": {
                    "agents": {
                        "price_agent": "invalid_depth",
                    },
                },
            },
        }
    )
    policy = result.get("policy") or {}
    allowed_agents = policy.get("allowed_agents") or []
    # price_agent should still be selected (invalid depth treated as standard)
    assert "price_agent" in allowed_agents


def test_policy_gate_agent_preferences_unknown_agent_ignored():
    """Unknown agent names in preferences should be silently ignored."""
    result = policy_gate(
        {
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": [],
                "selection_types": [],
                "selection_payload": [],
            },
            "output_mode": "investment_report",
            "ui_context": {
                "agent_preferences": {
                    "agents": {
                        "nonexistent_agent": "off",
                        "price_agent": "standard",
                    },
                },
            },
        }
    )
    policy = result.get("policy") or {}
    allowed_agents = policy.get("allowed_agents") or []
    assert "price_agent" in allowed_agents
    assert "nonexistent_agent" not in allowed_agents
