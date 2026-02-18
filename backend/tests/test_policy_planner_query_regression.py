# -*- coding: utf-8 -*-
from backend.graph.nodes.planner_stub import planner_stub
from backend.graph.nodes.policy_gate import policy_gate


def _run_policy_and_planner(query: str, operation_name: str, tickers: list[str]) -> tuple[dict, dict]:
    state = {
        "query": query,
        "operation": {"name": operation_name, "confidence": 0.9, "params": {}},
        "output_mode": "brief",
        "subject": {
            "subject_type": "company",
            "tickers": tickers,
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
    }
    policy_out = policy_gate(state)
    state = {**state, **policy_out}
    plan_out = planner_stub(state)
    return policy_out, plan_out


def test_old_query_price_path_keeps_stock_price_step():
    policy_out, plan_out = _run_policy_and_planner("AAPL price", "price", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_stock_price" in tools
    assert "get_stock_price" in step_names


def test_old_query_technical_path_keeps_technical_snapshot_step():
    policy_out, plan_out = _run_policy_and_planner("AAPL technical analysis", "technical", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_technical_snapshot" in tools
    assert "get_technical_snapshot" in step_names


def test_old_query_compare_path_keeps_comparison_step():
    policy_out, plan_out = _run_policy_and_planner("AAPL vs MSFT", "compare", ["AAPL", "MSFT"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_performance_comparison" in tools
    assert "get_performance_comparison" in step_names


def test_old_query_fetch_path_keeps_company_news_step():
    policy_out, plan_out = _run_policy_and_planner("latest AAPL news", "fetch", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_company_news" in tools
    assert "get_company_news" in step_names


def test_new_query_fundamental_tools_are_allowlisted():
    policy_out, plan_out = _run_policy_and_planner("AAPL EPS revisions and earnings estimates", "qa", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_earnings_estimates" in tools
    assert "get_eps_revisions" in tools
    assert "get_earnings_estimates" in step_names
    assert "get_eps_revisions" in step_names


def test_new_query_options_tool_is_allowlisted():
    policy_out, plan_out = _run_policy_and_planner("AAPL option IV PCR skew", "technical", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_option_chain_metrics" in tools
    assert "get_option_chain_metrics" in step_names


def test_new_query_risk_tools_are_allowlisted():
    policy_out, plan_out = _run_policy_and_planner("AAPL factor exposure and stress test", "qa", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_factor_exposure" in tools
    assert "run_portfolio_stress_test" in tools
    assert "get_factor_exposure" in step_names
    assert "run_portfolio_stress_test" in step_names


def test_new_query_news_tools_are_allowlisted():
    policy_out, plan_out = _run_policy_and_planner(
        "AAPL earnings/dividend calendar and source reliability",
        "qa",
        ["AAPL"],
    )
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_event_calendar" in tools
    assert "score_news_source_reliability" in tools
    assert "get_event_calendar" in step_names
    assert "score_news_source_reliability" in step_names
