"""真实问题的跨层规划合同；不调用外部服务。"""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from backend.graph.coverage_validator import validate_plan_coverage_for_frames
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.nodes.route_request import route_request
from backend.graph.planning.rule_planner import rule_based_planner
from backend.graph.planning.steps import finalize_step_dependencies
from backend.graph.planning.validation import validate_executable_plan


def planned(query):
    state = {"query": query, "output_mode": "chat", "ui_context": {"market": "US"},
             "memory_context": {}, "artifacts": {}, "trace": {}}
    state.update(asyncio.run(route_request(state)))
    state.update(policy_gate(state))
    state.update(rule_based_planner(state))
    return state


def test_compound_request_keeps_third_fundamental_subject():
    state = planned("AAPL price, MSFT news, NVDA fundamentals")
    assert state["trace"]["planner"]["validated"]
    assert {ticker for task in state["tasks"] for ticker in task["tickers"]} == {"AAPL", "MSFT", "NVDA"}
    for task in state["tasks"]:
        assert any(task["id"] in step.get("task_ids", []) for step in state["plan_ir"]["steps"])
    assert any(step["name"] == "fundamental_agent" and step["inputs"]["ticker"] == "NVDA"
               for step in state["plan_ir"]["steps"])
    assert state["trace"]["coverage_validator"]["status"] == "ok"


def test_price_for_one_subject_does_not_prove_other_subject_technical_coverage():
    frames = [{"frame_id": ticker, "task_ids": [ticker], "subject": {"tickers": [ticker]},
               "evidence_obligations": ["technical_snapshot"]} for ticker in ["AAPL", "MSFT"]]
    plan = {"steps": [{"id": "price", "kind": "tool", "name": "get_stock_price",
                       "inputs": {"ticker": "AAPL"}, "task_ids": ["AAPL", "MSFT"]}]}
    result = validate_plan_coverage_for_frames(request_frames=frames, plan_ir=plan)
    assert result["status"] == "missing"
    assert {row["subject"] for row in result["missing_requirements"]} == {"AAPL", "MSFT"}


def test_growth_and_risk_are_not_pruned_by_valuation_profile():
    state = planned("比较 NVDA 和 AMD 的估值、增长与投资风险，哪个更适合长期研究？")
    for ticker in ["NVDA", "AMD"]:
        assert any(step["name"] == "fundamental_agent" and step["inputs"].get("ticker") == ticker
                   for step in state["plan_ir"]["steps"])
        assert any(step["name"] == "get_factor_exposure" and step["inputs"]["positions"][0]["ticker"] == ticker
                   for step in state["plan_ir"]["steps"])


def test_business_and_competition_are_explicit_request_obligations():
    state = planned("分析 AAPL 的业务模式与竞争格局")
    frame = state["request_frame"]
    assert {"business_model", "competition"} <= set(frame["render_contract"]["dimensions"])
    assert "document_context" in frame["evidence_obligations"]
    assert any(step["name"] == "deep_search_agent" for step in state["plan_ir"]["steps"])
    assert state["trace"]["coverage_validator"]["status"] == "ok"


def test_quarter_catalyst_query_plans_the_requested_forward_window():
    state = planned("INTC 未来一个季度哪些催化剂值得跟踪？")
    calendar = next(step for step in state["plan_ir"]["steps"] if step["name"] == "get_event_calendar")
    assert calendar["inputs"]["days_ahead"] == 90
    assert state["tasks"][0]["time_scope"]["days_ahead"] == 90


def test_dependencies_follow_evidence_even_if_producer_is_listed_after_agent():
    steps = [
        {"id": "agent", "kind": "agent", "name": "fundamental_agent", "inputs": {"ticker": "AAPL"}},
        {"id": "other", "kind": "tool", "name": "get_company_info", "inputs": {"ticker": "MSFT"}},
        {"id": "facts", "kind": "tool", "name": "get_sec_company_facts_quarterly", "inputs": {"ticker": "AAPL"}},
    ]
    first = finalize_step_dependencies(deepcopy(steps))
    reverse = finalize_step_dependencies(deepcopy(list(reversed(steps))))
    assert {step["id"]: step["data_dependencies"] for step in first} == {step["id"]: step["data_dependencies"] for step in reverse}
    assert first[0]["data_dependencies"] == ["facts"]
    assert "filing_context" in first[0]["inputs"]["required_evidence"]


class ToolInput(BaseModel):
    ticker: str
    forms: str


@pytest.mark.parametrize("mutation,code", [
    ("inputs", "invalid_plan_tool_inputs"), ("duplicate", "duplicate_plan_step_id"),
    ("unknown", "invalid_plan_dependency"), ("cycle", "plan_dependency_cycle"),
])
def test_invalid_plan_fails_before_tool_io(mutation, code):
    steps = [{"id": "a", "kind": "tool", "name": "filings", "inputs": {"ticker": "AAPL", "forms": "10-Q"}},
             {"id": "b", "kind": "tool", "name": "filings", "inputs": {"ticker": "MSFT", "forms": "10-Q"}}]
    if mutation == "inputs": steps[0]["inputs"]["forms"] = ["10-Q"]
    if mutation == "duplicate": steps[1]["id"] = "a"
    if mutation == "unknown": steps[0]["depends_on"] = ["missing"]
    if mutation == "cycle":
        steps[0]["depends_on"] = ["b"]
        steps[1]["data_dependencies"] = ["a"]
    with pytest.raises(ValueError, match=code):
        validate_executable_plan({"goal": "test", "subject": {"subject_type": "company"},
            "output_mode": "chat", "steps": steps, "budget": {"max_rounds": 1, "max_tools": 10}},
            tool_lookup=lambda _: SimpleNamespace(args_schema=ToolInput))
