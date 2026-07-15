# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_normalize_collector_output_repairs_invalid_shapes():
    import backend.graph.adapters.collector_adapter as adapter

    out = adapter._normalize_agent_output(
        step_name="news_agent",
        output={
            "summary": "  news ok  ",
            "confidence": "0.95",
            "evidence": "bad-shape",
            "data_sources": "bad-shape",
            "risks": "bad-shape",
            "trace": "bad-shape",
        },
        query="q",
        ticker="MSFT",
    )
    assert out.get("agent_name") == "news_agent"
    assert out.get("summary") == "news ok"
    assert 0.0 <= float(out.get("confidence", 0)) <= 1.0
    assert isinstance(out.get("evidence"), list)
    assert isinstance(out.get("data_sources"), list)
    assert isinstance(out.get("risks"), list)
    assert isinstance(out.get("trace"), list)


def test_empty_summary_returns_structured_fallback():
    import backend.graph.adapters.collector_adapter as adapter

    out = adapter._normalize_agent_output(
        step_name="price_agent",
        output={"summary": "   ", "confidence": 0.9, "evidence": [], "data_sources": ["x"]},
        query="price check",
        ticker="AAPL",
    )
    assert out.get("agent_name") == "price_agent"
    assert out.get("fallback_used") is True
    assert out.get("requests") == []
    assert float(out.get("confidence", 1)) <= 0.2


def test_unknown_collector_returns_fallback():
    import backend.graph.adapters.collector_adapter as adapter

    invokers = adapter.build_collector_invokers(
        allowed_collectors=["unknown_agent"],
        state={"query": "q", "subject": {"tickers": ["AAPL"]}},
    )
    out = _run(invokers["unknown_agent"]({"query": "q", "ticker": "AAPL"}))
    assert out.get("agent_name") == "unknown_agent"
    assert out.get("fallback_used") is True
    assert out.get("summary")
