# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import importlib


def _run(coro):
    return asyncio.run(coro)


def test_direct_and_clarify_lanes_do_not_call_external_io(monkeypatch):
    collect_module = importlib.import_module("backend.graph.nodes.collect_evidence")
    analyze_module = importlib.import_module("backend.graph.nodes.analyze")

    async def forbidden_io(_state):
        raise AssertionError("direct/clarify lane must not execute evidence I/O")

    async def forbidden_llm(_state):
        raise AssertionError("direct/clarify lane must not invoke ResearchAnalyst")

    monkeypatch.setattr(collect_module, "execute_plan_node", forbidden_io)
    monkeypatch.setattr(analyze_module, "synthesize", forbidden_llm)

    from backend.graph import GraphRunner

    runner = GraphRunner.create()
    direct = _run(runner.ainvoke(thread_id="wp6-no-io-direct", query="你好", ui_context={}))
    clarify = _run(runner.ainvoke(thread_id="wp6-no-io-clarify", query="分析影响", ui_context={}))
    assert (direct.get("understanding") or {}).get("route") == "direct"
    assert (clarify.get("understanding") or {}).get("route") == "clarify"


def test_fact_query_uses_deterministic_renderer_without_llm(monkeypatch):
    analyze_module = importlib.import_module("backend.graph.nodes.analyze")

    async def forbidden_llm(_state):
        raise AssertionError("fact query must not invoke ResearchAnalyst")

    monkeypatch.setattr(analyze_module, "synthesize", forbidden_llm)

    from backend.graph import GraphRunner

    result = _run(
        GraphRunner.create().ainvoke(
            thread_id="wp6-fact-zero-llm",
            query="AAPL 最新股价",
            ui_context={"active_symbol": "AAPL"},
        )
    )
    analysis_trace = (result.get("trace") or {}).get("analysis") or {}
    assert analysis_trace.get("role") == "deterministic_renderer"
    assert analysis_trace.get("llm_calls") == 0


def test_regular_research_invokes_one_research_analyst(monkeypatch):
    analyze_module = importlib.import_module("backend.graph.nodes.analyze")
    calls = 0

    async def fake_synthesize(state):
        nonlocal calls
        calls += 1
        return {
            "artifacts": {**(state.get("artifacts") or {}), "render_vars": {"conclusion": "grounded"}},
            "trace": dict(state.get("trace") or {}),
        }

    monkeypatch.setattr(analyze_module, "synthesize", fake_synthesize)
    result = _run(
        analyze_module.analyze(
            {
                "understanding": {"route": "research"},
                "operation": {"name": "investment_opinion"},
                "output_mode": "chat",
                "artifacts": {"evidence_pool": []},
                "trace": {},
            }
        )
    )
    assert calls == 1
    assert (result.get("trace") or {}).get("analysis", {}).get("business_llm_calls") == 1
    assert (result.get("trace") or {}).get("analysis", {}).get("verifier_allowed") is False


def test_collectors_are_constructed_without_llm_or_reflection(monkeypatch):
    adapter = importlib.import_module("backend.graph.adapters.collector_adapter")
    seen: dict[str, object] = {}

    class FakeCollector:
        def __init__(self, llm, _cache, _tools):
            seen["llm"] = llm

    monkeypatch.setattr("backend.agents.price_agent.PriceAgent", FakeCollector)
    invokers = adapter.build_collector_invokers(
        allowed_collectors=["price_agent"],
        state={"query": "AAPL", "subject": {"tickers": ["AAPL"]}},
    )
    assert set(invokers) == {"price_agent"}
    assert seen == {"llm": None}
