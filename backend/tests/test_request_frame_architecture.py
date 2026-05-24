# -*- coding: utf-8 -*-
import asyncio

from backend.graph.nodes.planner_stub import planner_stub
from backend.graph.nodes.policy_gate import policy_gate


def test_backtest_request_frame_is_action_not_technical():
    from backend.graph.request_frame import compile_request_frame

    frame = compile_request_frame(
        query="backtest MACD strategy on AAPL",
        tickers=["AAPL"],
        output_mode="chat",
    )

    assert frame["lane"] == "action"
    assert frame["workflow_action"]["name"] == "backtest"
    assert frame["workflow_action"]["slots"]["ticker"] == "AAPL"
    assert frame["workflow_action"]["slots"]["strategy"] == "macd"
    assert frame["required_results"] == ["backtest_result"]
    assert frame["evidence_obligations"] == []
    assert frame["legacy_operation"]["name"] == "backtest"


def test_macd_analysis_request_frame_stays_technical_research():
    from backend.graph.request_frame import compile_request_frame

    frame = compile_request_frame(
        query="AAPL MACD technical analysis",
        tickers=["AAPL"],
        output_mode="chat",
    )

    assert frame["lane"] == "research"
    assert frame.get("workflow_action") is None
    assert "technical_snapshot" in frame["evidence_obligations"]
    assert frame["legacy_operation"]["name"] == "technical"


def test_backtest_definition_request_frame_stays_answer():
    from backend.graph.request_frame import compile_request_frame

    frame = compile_request_frame(
        query="what is backtesting?",
        tickers=[],
        output_mode="chat",
    )

    assert frame["lane"] == "answer"
    assert frame.get("workflow_action") is None
    assert frame["required_results"] == []
    assert frame["legacy_operation"]["name"] == "qa"


def test_understand_request_projects_backtest_action_before_technical_fast_path(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {
        "query": "backtest MACD strategy on AAPL",
        "ui_context": {},
        "output_mode": "chat",
    }
    understanding = asyncio.run(understand_request(state))

    frame = understanding.get("request_frame") or {}
    tasks = understanding.get("tasks") or []
    task_ops = [(task.get("operation") or {}).get("name") for task in tasks]

    assert frame.get("lane") == "action"
    assert (frame.get("workflow_action") or {}).get("name") == "backtest"
    assert task_ops == ["backtest"]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = [step.get("name") for step in steps]

    assert "run_strategy_backtest" in step_names
    assert "technical_agent" not in step_names

    backtest_step = next(step for step in steps if step.get("name") == "run_strategy_backtest")
    assert (backtest_step.get("inputs") or {}).get("strategy") == "macd"

    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}
    assert coverage.get("status") == "ok"
    assert coverage.get("fulfilled_results") == ["backtest_result"]
    assert coverage.get("missing_results") == []


def test_coverage_validator_flags_missing_workflow_result():
    from backend.graph.coverage_validator import validate_plan_coverage
    from backend.graph.request_frame import compile_request_frame

    frame = compile_request_frame(
        query="backtest MACD strategy on AAPL",
        tickers=["AAPL"],
        output_mode="chat",
    )

    missing = validate_plan_coverage(request_frame=frame, plan_ir={"steps": []})
    assert missing["status"] == "missing"
    assert missing["missing_results"] == ["backtest_result"]

    covered = validate_plan_coverage(
        request_frame=frame,
        plan_ir={"steps": [{"kind": "tool", "name": "run_strategy_backtest", "inputs": {}}]},
    )
    assert covered["status"] == "ok"
    assert covered["fulfilled_results"] == ["backtest_result"]


def test_request_frame_for_valuation_compare_carries_evidence_contract(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {
        "query": "NVDA and AMD which valuation is more reasonable",
        "ui_context": {},
        "output_mode": "chat",
    }
    understanding = asyncio.run(understand_request(state))
    frame = understanding.get("request_frame") or {}

    assert frame.get("lane") == "research"
    assert frame.get("relation") == "rank"
    assert (frame.get("subject") or {}).get("tickers") == ["NVDA", "AMD"]
    assert frame.get("evidence_obligations") == [
        "price_snapshot",
        "company_profile",
        "earnings_estimates",
    ]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert coverage.get("status") == "ok"
    assert coverage.get("fulfilled_evidence") == [
        "price_snapshot",
        "company_profile",
        "earnings_estimates",
    ]
    assert coverage.get("missing_evidence") == []


def test_request_frame_for_external_entity_impact_carries_risk_and_news(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {
        "query": "Research whether TSLA could be affected by SpaceX",
        "ui_context": {},
        "output_mode": "chat",
    }
    understanding = asyncio.run(understand_request(state))
    frame = understanding.get("request_frame") or {}

    assert frame.get("lane") == "research"
    assert frame.get("relation") == "impact"
    assert (frame.get("subject") or {}).get("tickers") == ["TSLA"]
    assert frame.get("evidence_obligations") == [
        "price_snapshot",
        "news_context",
        "risk_profile",
    ]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert coverage.get("status") == "ok"
    assert coverage.get("missing_evidence") == []
