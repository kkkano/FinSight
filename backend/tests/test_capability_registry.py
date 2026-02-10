# -*- coding: utf-8 -*-
from backend.graph.capability_registry import (
    REPORT_AGENT_CANDIDATES,
    required_agents_for_request,
    select_agents_for_request,
)


def _state(*, query: str, subject_type: str, operation: str = "generate_report") -> dict:
    return {
        "query": query,
        "output_mode": "investment_report",
        "operation": {"name": operation, "confidence": 0.9, "params": {}},
        "subject": {"subject_type": subject_type, "tickers": ["AAPL"], "selection_types": []},
    }


def test_required_agents_company_report_has_foundation_trio():
    state = _state(query="Analyze AAPL and produce an investment report", subject_type="company")
    required = required_agents_for_request(state, REPORT_AGENT_CANDIDATES)
    # company + investment_report now requires all 5 core agents (macro + technical added)
    assert required == ["price_agent", "news_agent", "fundamental_agent", "macro_agent", "technical_agent"]


def test_select_agents_company_report_does_not_default_to_deep_search():
    state = _state(query="Analyze AAPL and produce an investment report", subject_type="company")
    selected = select_agents_for_request(state, REPORT_AGENT_CANDIDATES, max_agents=4, min_agents=2)
    names = selected.get("selected") or []
    assert {"price_agent", "news_agent", "fundamental_agent"}.issubset(set(names))
    assert "deep_search_agent" not in names
    # 5 required agents (includes macro + technical), target clamps up to match
    assert len(names) <= 5


def test_select_agents_deep_hint_enables_deep_search():
    state = _state(query="Deep research on AAPL and produce a report", subject_type="company")
    selected = select_agents_for_request(state, REPORT_AGENT_CANDIDATES, max_agents=4, min_agents=2)
    names = selected.get("selected") or []
    assert "deep_search_agent" in names


def test_select_agents_filing_prioritizes_document_agents():
    state = _state(query="Read filing and create report", subject_type="filing")
    selected = select_agents_for_request(state, REPORT_AGENT_CANDIDATES, max_agents=4, min_agents=2)
    names = selected.get("selected") or []
    assert "deep_search_agent" in names
    assert "fundamental_agent" in names
    assert len(names) <= 4
