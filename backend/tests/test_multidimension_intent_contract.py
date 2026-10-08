# -*- coding: utf-8 -*-
import asyncio

import pytest

from backend.graph.intent_contract import derive_intent_contract, legacy_operation_for_contract
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.nodes.route_request import route_request
from backend.graph.planning.rule_planner import rule_based_planner
from backend.graph.understanding_v2 import infer_facets


INTC_QUERY = "分析一下 英特尔 的最新基本面、技术面、催化剂与主要风险"


@pytest.mark.parametrize(
    "query,expected_facets,expected_evidence",
    [
        (
            INTC_QUERY,
            {"fundamental", "technical", "catalyst", "risk"},
            {"fundamental_snapshot", "filing_context", "technical_snapshot", "news_context", "event_calendar", "risk_profile"},
        ),
        (
            "Analyze Intel fundamentals, technicals, catalysts and risks",
            {"fundamental", "technical", "catalyst", "risk"},
            {"fundamental_snapshot", "technical_snapshot", "news_context", "event_calendar", "risk_profile"},
        ),
        ("英特尔基本面怎么样", {"fundamental"}, {"company_profile", "earnings_estimates", "fundamental_snapshot", "filing_context"}),
        ("INTC 下季度有哪些催化剂", {"catalyst"}, {"news_context", "event_calendar"}),
    ],
)
def test_explicit_research_dimensions_become_evidence_obligations(query, expected_facets, expected_evidence):
    contract = derive_intent_contract(query=query, tickers=["INTC"], output_mode="chat")
    operation = legacy_operation_for_contract(contract)

    assert set(contract["facets"]) == expected_facets
    assert expected_evidence <= set(contract["required_evidence"])
    assert set(operation["params"]["facets"]) == expected_facets
    assert operation["name"] == "investment_opinion"
    assert operation["params"]["evidence_focus"] == "investment_opinion"


@pytest.mark.parametrize(
    "query,expected_name,expected_focus,excluded_evidence",
    [
        ("INTC 技术面分析", "technical", None, {"news_context", "fundamental_snapshot"}),
        ("INTC 主要风险", "investment_opinion", "risk", {"news_context", "fundamental_snapshot"}),
        ("INTC 估值分析", "investment_opinion", "valuation", {"news_context", "risk_profile"}),
        ("INTC 估值与主要风险", "investment_opinion", "investment_opinion", {"news_context"}),
        ("INTC 基本面，不要新闻与催化剂", "investment_opinion", "investment_opinion", {"news_context", "event_calendar"}),
    ],
)
def test_single_dimension_focus_and_explicit_news_exclusion_remain_scoped(query, expected_name, expected_focus, excluded_evidence):
    contract = derive_intent_contract(query=query, tickers=["INTC"], output_mode="chat")
    operation = legacy_operation_for_contract(contract)

    assert operation["name"] == expected_name
    assert operation["params"].get("evidence_focus") == expected_focus
    assert excluded_evidence.isdisjoint(contract["required_evidence"])
    assert operation["params"]["facets"] == contract["facets"]


def test_four_dimension_query_preserves_semantics_through_policy_and_planning():
    state = {"query": INTC_QUERY, "ui_context": {"market": "US"}, "output_mode": "chat"}
    understanding = asyncio.run(route_request(state))
    policy = policy_gate({**state, **understanding})
    plan = rule_based_planner({**state, **understanding, **policy})["plan_ir"]

    assert len(understanding["tasks"]) == 1
    task = understanding["tasks"][0]
    frame = understanding["request_frames"][0]
    assert task["tickers"] == ["INTC"]
    assert set(task["operation"]["params"]["facets"]) == {"fundamental", "catalyst", "risk", "technical"}
    assert set(frame["render_contract"]["dimensions"]) == {"fundamental_quality", "news_catalysts", "risk_level", "technical_quality"}
    assert {"fundamental_agent", "technical_agent", "news_agent", "risk_agent", "get_event_calendar"} <= {step["name"] for step in plan["steps"]}
    assert all(step.get("task_id") == task["id"] for step in plan["steps"])
    filings_step = next(step for step in plan["steps"] if step["name"] == "get_sec_filings")
    from backend.langchain_tools import SecFilingsInput

    assert SecFilingsInput.model_validate(filings_step["inputs"]).forms == "10-K,10-Q"


def test_history_bound_catalyst_followup_recompiles_frame_before_planning():
    state = {
        "query": "你刚才提到的催化剂，未来一个季度哪些最值得跟踪？",
        "messages": [{"role": "user", "content": INTC_QUERY}, {"role": "assistant", "content": "INTC 需要跟踪催化剂。"}],
        "ui_context": {},
        "output_mode": "chat",
    }
    understanding = asyncio.run(route_request(state))
    policy = policy_gate({**state, **understanding})
    plan_out = rule_based_planner({**state, **understanding, **policy})
    task = understanding["tasks"][0]
    frame = understanding["request_frames"][0]

    assert task["tickers"] == frame["subject"]["tickers"] == ["INTC"]
    assert task["operation"]["name"] == "investment_opinion"
    assert task["operation"]["params"]["facets"] == ["catalyst"]
    assert frame["evidence_obligations"] == ["news_context", "event_calendar"]
    steps = plan_out["plan_ir"]["steps"]
    assert {"get_company_news", "get_authoritative_media_news", "get_event_calendar"} <= {step["name"] for step in steps}
    assert all(step.get("task_id") == task["id"] for step in steps)
    assert next(step for step in steps if step["name"] == "get_event_calendar")["inputs"]["ticker"] == "INTC"
    assert plan_out["trace"]["coverage_validator"]["status"] == "ok"


def test_shadow_understanding_includes_requested_fundamentals_and_catalysts():
    names = {facet["name"] for facet in infer_facets(INTC_QUERY)}
    assert {"fundamental", "technical", "news", "risk"} <= names


def test_explicit_technical_indicator_question_does_not_expand_to_general_opinion():
    state = {"query": "AAPL 的短线趋势、RSI、MACD 和支撑阻力怎么看？", "ui_context": {}, "output_mode": "chat"}
    understanding = asyncio.run(route_request(state))
    policy = policy_gate({**state, **understanding})
    plan = rule_based_planner({**state, **understanding, **policy})["plan_ir"]

    assert understanding["operation"]["name"] == "technical"
    assert understanding["blocked_tasks"] == []
    assert set(understanding["intent_contract"]["facets"]) == {"trend", "technical"}
    assert {"get_stock_price", "get_technical_snapshot", "technical_agent"} <= {step["name"] for step in plan["steps"]}
    assert {"news_agent", "fundamental_agent", "get_company_news", "get_company_info"}.isdisjoint(step["name"] for step in plan["steps"])
