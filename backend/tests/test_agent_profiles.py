# -*- coding: utf-8 -*-
from __future__ import annotations

import re

import pytest

from backend.agents.profiles import (
    AGENT_PROFILES,
    lead_agent_for_operation,
    profile,
)
from backend.dashboard.agent_bridge import _TAB_AGENTS
from backend.graph.capability_registry import AGENT_CAPABILITIES, REPORT_AGENT_CANDIDATES


EXPECTED_AGENTS = {
    "price_agent",
    "news_agent",
    "fundamental_agent",
    "technical_agent",
    "macro_agent",
    "risk_agent",
    "deep_search_agent",
}


def test_profiles_cover_every_report_agent_with_complete_identity():
    assert set(AGENT_PROFILES) == EXPECTED_AGENTS == set(REPORT_AGENT_CANDIDATES)
    assert set(AGENT_PROFILES) == set(AGENT_CAPABILITIES)

    glyphs: set[str] = set()
    for key, item in AGENT_PROFILES.items():
        assert item.key == key
        assert item.name_zh
        assert 1 <= len(item.short_zh) <= 4
        assert len(item.glyph) == 1
        assert item.glyph not in glyphs
        glyphs.add(item.glyph)
        assert re.fullmatch(r"t-[a-z0-9-]+", item.color_token)
        assert item.mandate_zh
        assert item.tools


def test_profile_dashboard_tabs_are_exact_inverse_of_bridge_registry():
    expected = {
        key: tuple(tab for tab, agents in _TAB_AGENTS.items() if key in agents)
        for key in AGENT_PROFILES
    }
    actual = {key: item.dashboard_tabs for key, item in AGENT_PROFILES.items()}
    assert actual == expected


def test_profile_lookup_and_operation_leads_are_deterministic():
    assert profile("technical_agent").name_zh == "技术面分析师"
    with pytest.raises(KeyError):
        profile("missing_agent")

    assert lead_agent_for_operation("investment_opinion") == "fundamental_agent"
    assert lead_agent_for_operation("generate_report") == "fundamental_agent"
    assert lead_agent_for_operation("technical") == "technical_agent"
    assert lead_agent_for_operation("price") == "price_agent"
    assert lead_agent_for_operation("fetch") == "news_agent"
    assert lead_agent_for_operation("news_impact") == "news_agent"
    assert lead_agent_for_operation("analyze_impact") == "news_agent"
    assert lead_agent_for_operation("earnings_impact") == "fundamental_agent"
    assert lead_agent_for_operation("earnings_performance") == "fundamental_agent"
    assert lead_agent_for_operation("compare") == "fundamental_agent"
    assert lead_agent_for_operation("macro_snapshot") == "macro_agent"
    assert lead_agent_for_operation("portfolio_review") == "risk_agent"
    assert lead_agent_for_operation("rebalance_check") == "risk_agent"
    assert lead_agent_for_operation("qa") == "deep_search_agent"
    assert lead_agent_for_operation("unknown") == "fundamental_agent"
