"""WP2 确定性金融术语解析器。"""

from __future__ import annotations

import asyncio

import pytest

from backend.graph.intent.financial_terms import (
    build_financial_term_direct_result,
    render_financial_term_definition,
    resolve_financial_term_definition,
)


@pytest.mark.parametrize(
    ("query", "terms", "language"),
    [
        ("PE 是什么？", ("pe",), "zh"),
        ("p/e 怎么算", ("pe",), "zh"),
        ("PB、ROE 和 EPS 分别是什么意思", ("pb", "roe", "eps"), "zh"),
        ("请问 PE 是什么？用一句话解释。", ("pe",), "zh"),
        ("What is EV/EBITDA?", ("ev_ebitda",), "en"),
    ],
)
def test_resolver_positive_examples(query, terms, language):
    match = resolve_financial_term_definition(query, "chat")
    assert match is not None
    assert match.terms == terms
    assert match.language == language


@pytest.mark.parametrize(
    "query",
    [
        "AAPL 的 PE 是多少",
        "这只股票的 PB 是什么",
        "NVDA 和 AMD 哪个 PE 更合理",
        "PE 和 PB 有什么区别",
        "PE 20 意味着什么",
        "PE",
    ],
)
def test_resolver_negative_examples(query):
    assert resolve_financial_term_definition(query, "chat") is None


def test_report_and_forced_agent_do_not_short_circuit():
    assert resolve_financial_term_definition("PE 是什么", "investment_report") is None
    assert resolve_financial_term_definition("PE 是什么", "chat", forced_agent=True) is None


def test_builder_preserves_state_and_uses_same_rendered_text():
    match = resolve_financial_term_definition("PE 是什么", "chat")
    assert match is not None
    state = {
        "query": "PE 是什么", "output_mode": "brief", "artifacts": {"kept": 1},
        "trace": {"events": [{"event": "kept"}], "kept": True},
    }
    result = build_financial_term_direct_result(state, match)
    rendered = render_financial_term_definition(match)
    assert result["messages"][0].content == rendered == result["artifacts"]["draft_markdown"]
    assert result["artifacts"]["kept"] == 1
    assert result["trace"]["events"][0] == {"event": "kept"}
    assert result["understanding"]["intent_frame"]["source"] == "deterministic_term_resolver"
    assert result["output_mode"] == "brief"


def test_understand_request_short_circuits_before_context_and_router(monkeypatch):
    import backend.graph.nodes.understand_request as understand_module

    monkeypatch.setenv("FINSIGHT_FINANCIAL_TERM_RESOLVER", "on")
    state = {"query": "PE 是什么？", "ui_context": {"active_symbol": "NVDA"}, "trace": {}, "artifacts": {}}
    result = asyncio.run(understand_module(state))
    assert result["chat_responded"] is True
    assert result["tasks"] == []
    assert result["understanding"]["intent_frame"]["source"] == "deterministic_term_resolver"
