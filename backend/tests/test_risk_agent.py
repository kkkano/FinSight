# -*- coding: utf-8 -*-
"""Tests for RiskAgent rule engine."""

from __future__ import annotations

import pytest

from backend.agents.base_agent import AgentOutput
from backend.agents.risk_agent import RiskAgent, RiskLevel


def _output(agent_name: str, risks: list[str]) -> AgentOutput:
    return AgentOutput(
        agent_name=agent_name,
        summary="ok",
        evidence=[],
        confidence=0.8,
        data_sources=["test"],
        as_of="2026-02-16T00:00:00+00:00",
        risks=risks,
    )


def test_assess_risk_classifies_technical_signal():
    assessment = RiskAgent.assess_risk("AAPL", [_output("technical_agent", ["RSI is overbought and bearish"])])
    assert len(assessment.signals) == 1
    assert assessment.signals[0].category == "technical"


def test_assess_risk_classifies_fundamental_signal():
    assessment = RiskAgent.assess_risk("AAPL", [_output("fundamental_agent", ["Debt level remains high"])])
    assert len(assessment.signals) == 1
    assert assessment.signals[0].category == "fundamental"


def test_assess_risk_classifies_macro_signal():
    assessment = RiskAgent.assess_risk("AAPL", [_output("macro_agent", ["Yield curve inversion risk rising"])])
    assert len(assessment.signals) == 1
    assert assessment.signals[0].category == "macro"


def test_assess_risk_classifies_news_signal():
    assessment = RiskAgent.assess_risk("AAPL", [_output("news_agent", ["Company faces lawsuit investigation"])])
    assert len(assessment.signals) == 1
    assert assessment.signals[0].category == "news"


def test_assess_risk_classifies_unknown_as_data_quality():
    assessment = RiskAgent.assess_risk("AAPL", [_output("x_agent", ["Something odd but unspecified"])])
    assert len(assessment.signals) == 1
    assert assessment.signals[0].category == "data_quality"


def test_assess_risk_empty_outputs_score_zero():
    assessment = RiskAgent.assess_risk("AAPL", [])
    assert assessment.risk_score == 0.0
    assert assessment.risk_level == RiskLevel.LOW
    assert assessment.signals == []


def test_assess_risk_multi_category_reaches_high():
    outputs = [
        _output("technical_agent", ["RSI overbought severe warning"]),
        _output("fundamental_agent", ["Debt is significant and leverage is high"]),
        _output("macro_agent", ["Fed rate hike risk remains high"]),
    ]
    assessment = RiskAgent.assess_risk("AAPL", outputs)
    assert assessment.risk_score > 50.0
    assert assessment.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}


def test_assess_risk_category_score_is_capped():
    outputs = [
        _output("technical_agent", ["critical bearish risk"]),
        _output("technical_agent", ["critical overbought risk"]),
        _output("technical_agent", ["critical support break risk"]),
    ]
    assessment = RiskAgent.assess_risk("AAPL", outputs)
    assert assessment.risk_score <= 25.0
    assert assessment.risk_level == RiskLevel.LOW


def test_level_mapping_boundaries():
    assert RiskAgent._level_from_score(0.0) == RiskLevel.LOW
    assert RiskAgent._level_from_score(25.0) == RiskLevel.LOW
    assert RiskAgent._level_from_score(26.0) == RiskLevel.MEDIUM
    assert RiskAgent._level_from_score(50.0) == RiskLevel.MEDIUM
    assert RiskAgent._level_from_score(51.0) == RiskLevel.HIGH
    assert RiskAgent._level_from_score(75.0) == RiskLevel.HIGH
    assert RiskAgent._level_from_score(76.0) == RiskLevel.CRITICAL


def test_risk_level_meets_threshold():
    assert RiskAgent.risk_level_meets_threshold(RiskLevel.HIGH, RiskLevel.MEDIUM) is True
    assert RiskAgent.risk_level_meets_threshold(RiskLevel.MEDIUM, RiskLevel.HIGH) is False


def test_lightweight_large_drop_triggers_high_or_above():
    assessment = RiskAgent.evaluate_ticker_risk_lightweight(
        "AAPL",
        {"price": 100.0, "change_percent": -8.6},
    )
    assert assessment.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
    assert assessment.risk_score > 50.0


def test_lightweight_stable_market_is_low():
    assessment = RiskAgent.evaluate_ticker_risk_lightweight(
        "AAPL",
        {"price": 100.0, "change_percent": 0.2},
    )
    assert assessment.risk_level == RiskLevel.LOW
    assert assessment.risk_score <= 25.0


def test_lightweight_missing_price_creates_data_quality_signal():
    assessment = RiskAgent.evaluate_ticker_risk_lightweight(
        "AAPL",
        {"price": None, "change_percent": None},
    )
    assert any(signal.category == "data_quality" for signal in assessment.signals)
    assert assessment.risk_score > 0.0


@pytest.mark.asyncio
async def test_risk_agent_research_returns_agent_output():
    class _Tools:
        @staticmethod
        def get_stock_price(_ticker: str):
            return {"price": 100.0, "change_percent": -6.0}

    agent = RiskAgent(llm=None, cache=None, tools_module=_Tools())
    output = await agent.research(query="analyze risk", ticker="AAPL")
    assert output.agent_name == "risk_agent"
    assert output.summary
    assert isinstance(output.risks, list)
    assert output.data_sources
