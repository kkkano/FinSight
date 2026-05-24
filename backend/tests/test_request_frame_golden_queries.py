# -*- coding: utf-8 -*-
import asyncio
from dataclasses import dataclass, field

import pytest

from backend.graph.nodes.planner_stub import planner_stub
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.nodes.understand_request import understand_request


@dataclass(frozen=True)
class GoldenQueryCase:
    query: str
    expected_frame_count: int = 1
    expected_lane: str | None = None
    expected_relation: str | None = None
    expected_tickers: list[str] | None = None
    expected_evidence: list[str] | None = None
    expected_frame_evidence: list[list[str]] | None = None
    expected_required_results: list[str] = field(default_factory=list)
    expected_action: str | None = None
    expected_render_shape: str | None = None
    must_include_steps: set[str] = field(default_factory=set)
    must_exclude_steps: set[str] = field(default_factory=set)


GOLDEN_QUERY_CASES = [
    GoldenQueryCase(
        query="NVDA and AMD which valuation is more reasonable",
        expected_relation="rank",
        expected_tickers=["NVDA", "AMD"],
        expected_evidence=["price_snapshot", "company_profile", "earnings_estimates"],
        expected_render_shape="compare",
        must_include_steps={"get_stock_price", "get_company_info", "get_earnings_estimates"},
        must_exclude_steps={"get_performance_comparison"},
    ),
    GoldenQueryCase(
        query="Research whether TSLA could be affected by SpaceX",
        expected_relation="impact",
        expected_tickers=["TSLA"],
        expected_evidence=["price_snapshot", "news_context", "risk_profile"],
        expected_render_shape="answer",
        must_include_steps={"get_stock_price", "get_company_news", "analyze_historical_drawdowns"},
    ),
    GoldenQueryCase(
        query="backtest MACD strategy on AAPL",
        expected_lane="action",
        expected_relation="single",
        expected_tickers=["AAPL"],
        expected_required_results=["backtest_result"],
        expected_action="backtest",
        expected_render_shape="action_result",
        must_include_steps={"run_strategy_backtest"},
        must_exclude_steps={"technical_agent"},
    ),
    GoldenQueryCase(
        query="what is backtesting?",
        expected_lane="answer",
        expected_relation="none",
        expected_evidence=[],
        expected_render_shape="answer",
        must_exclude_steps={"run_strategy_backtest", "technical_agent", "fundamental_agent"},
    ),
    GoldenQueryCase(
        query="Do not look up news. Just tell me why semiconductors can sell off together.",
        expected_lane="answer",
        expected_relation="none",
        expected_evidence=[],
        expected_render_shape="answer",
        must_exclude_steps={"get_company_news", "get_authoritative_media_news", "news_agent"},
    ),
    GoldenQueryCase(
        query="Check AAPL price, MSFT news, then explain Fed rate impact",
        expected_frame_count=3,
        expected_frame_evidence=[["price_snapshot"], ["news_context"], ["macro_context"]],
        must_include_steps={"get_stock_price", "get_company_news", "get_official_macro_releases"},
    ),
    GoldenQueryCase(
        query="AAPL MACD technical analysis",
        expected_relation="single",
        expected_tickers=["AAPL"],
        expected_evidence=["price_snapshot", "technical_snapshot", "options_derivatives"],
        expected_render_shape="answer",
        must_include_steps={"get_stock_price", "get_technical_snapshot", "get_option_chain_metrics"},
    ),
    GoldenQueryCase(
        query="latest news links for MSFT",
        expected_relation="single",
        expected_tickers=["MSFT"],
        expected_evidence=["news_context"],
        expected_render_shape="answer",
        must_include_steps={"get_company_news", "get_authoritative_media_news"},
    ),
    GoldenQueryCase(
        query="AAPL price now",
        expected_relation="single",
        expected_tickers=["AAPL"],
        expected_evidence=["price_snapshot"],
        expected_render_shape="answer",
        must_include_steps={"get_stock_price"},
    ),
    GoldenQueryCase(
        query="How did NVDA earnings affect the stock price?",
        expected_relation="single",
        expected_tickers=["NVDA"],
        expected_evidence=[
            "company_profile",
            "earnings_estimates",
            "fundamental_snapshot",
            "news_context",
            "event_calendar",
            "transcript_context",
            "filing_context",
            "risk_profile",
            "price_snapshot",
        ],
        expected_render_shape="answer",
        must_include_steps={"get_company_info", "fundamental_agent", "get_event_calendar", "get_stock_price"},
    ),
    GoldenQueryCase(
        query="How was MSFT earnings performance?",
        expected_relation="single",
        expected_tickers=["MSFT"],
        expected_evidence=[
            "company_profile",
            "earnings_estimates",
            "fundamental_snapshot",
            "news_context",
            "event_calendar",
            "transcript_context",
            "filing_context",
        ],
        expected_render_shape="answer",
        must_include_steps={"get_company_info", "fundamental_agent", "get_earnings_call_transcripts"},
        must_exclude_steps={"get_stock_price", "risk_agent"},
    ),
    GoldenQueryCase(
        query="Compare AAPL and MSFT risk",
        expected_relation="compare",
        expected_tickers=["AAPL", "MSFT"],
        expected_evidence=["price_snapshot", "risk_profile"],
        expected_render_shape="compare",
        must_include_steps={"get_stock_price", "analyze_historical_drawdowns", "get_factor_exposure"},
    ),
    GoldenQueryCase(
        query="Research AAPL institutional holdings",
        expected_relation="single",
        expected_tickers=["AAPL"],
        expected_evidence=["holdings_ownership"],
        expected_render_shape="answer",
        must_include_steps={"get_institution_holdings_by_ticker", "get_insider_transactions"},
    ),
]


def _run_golden_query(query: str) -> tuple[dict, dict]:
    state = {
        "query": query,
        "ui_context": {"market": "US"},
        "output_mode": "chat",
    }
    understanding = asyncio.run(understand_request(state))
    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    return understanding, plan_out


@pytest.mark.parametrize("case", GOLDEN_QUERY_CASES, ids=lambda case: case.query)
def test_request_frame_golden_query_contracts(case: GoldenQueryCase, monkeypatch):
    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")
    monkeypatch.setenv("SEC_HOLDINGS_ENABLED", "true")

    understanding, plan_out = _run_golden_query(case.query)
    frames = understanding.get("request_frames") or []
    assert len(frames) == case.expected_frame_count

    primary_frame = frames[0] if frames else {}
    if case.expected_lane is not None:
        assert primary_frame.get("lane") == case.expected_lane
    if case.expected_relation is not None:
        assert primary_frame.get("relation") == case.expected_relation
    if case.expected_tickers is not None:
        assert (primary_frame.get("subject") or {}).get("tickers") == case.expected_tickers
    if case.expected_evidence is not None:
        assert primary_frame.get("evidence_obligations") == case.expected_evidence
    if case.expected_frame_evidence is not None:
        assert [frame.get("evidence_obligations") for frame in frames] == case.expected_frame_evidence
    if case.expected_required_results:
        assert primary_frame.get("required_results") == case.expected_required_results
    if case.expected_action is not None:
        assert (primary_frame.get("workflow_action") or {}).get("name") == case.expected_action
    if case.expected_render_shape is not None:
        assert (primary_frame.get("render_contract") or {}).get("shape") == case.expected_render_shape

    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = {str(step.get("name") or "") for step in steps}
    assert case.must_include_steps.issubset(step_names)
    assert case.must_exclude_steps.isdisjoint(step_names)

    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}
    assert coverage.get("status") == "ok"
    assert coverage.get("missing_evidence") == []
    assert coverage.get("missing_results") == []
