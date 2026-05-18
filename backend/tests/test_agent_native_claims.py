# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from backend.agents.fundamental_agent import FundamentalAgent
from backend.agents.news_agent import NewsAgent
from backend.agents.risk_agent import RiskAgent


class _Cache:
    def __init__(self) -> None:
        self.store = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value, ttl=None) -> None:
        del ttl
        self.store[key] = value


class _FundamentalTools:
    @staticmethod
    def get_company_info(_ticker: str) -> str:
        return "- Name: Apple Inc.\n- Sector: Technology\n- Industry: Consumer Electronics\n- Market Cap: $3.0T"

    @staticmethod
    def get_financial_statements(_ticker: str) -> dict:
        return {
            "financials": {
                "columns": ["2026-03-31", "2025-03-31"],
                "index": ["Total Revenue", "Net Income", "Operating Income"],
                "data": [
                    {"2026-03-31": 92000000000, "2025-03-31": 88000000000},
                    {"2026-03-31": 24000000000, "2025-03-31": 23000000000},
                    {"2026-03-31": 30000000000, "2025-03-31": 28500000000},
                ],
            },
            "balance_sheet": {
                "columns": ["2026-03-31", "2025-03-31"],
                "index": ["Total Assets", "Total Liabilities"],
                "data": [
                    {"2026-03-31": 360000000000, "2025-03-31": 350000000000},
                    {"2026-03-31": 210000000000, "2025-03-31": 205000000000},
                ],
            },
            "cashflow": {
                "columns": ["2026-03-31", "2025-03-31"],
                "index": ["Operating Cash Flow"],
                "data": [{"2026-03-31": 28000000000, "2025-03-31": 26000000000}],
            },
        }

    @staticmethod
    def get_earnings_estimates(_ticker: str) -> dict:
        return {"revision_signal": "positive", "as_of": "2026-05-18T00:00:00Z", "eps_revisions": [{"period": "0q"}]}

    @staticmethod
    def get_eps_revisions(_ticker: str) -> dict:
        return {"revision_signal": "positive", "as_of": "2026-05-18T00:00:00Z", "eps_revisions": [{"period": "0q"}]}


class _NewsTools:
    @staticmethod
    def get_company_news(_ticker: str) -> list[dict]:
        return [
            {
                "headline": "Apple services revenue beats expectations",
                "url": "https://www.reuters.com/technology/apple-services-revenue",
                "source": "Reuters",
                "datetime": "2026-05-17T12:00:00Z",
                "confidence": 0.9,
            },
            {
                "headline": "Apple shares move after analyst target update",
                "url": "https://finance.yahoo.com/news/apple-analyst-target",
                "source": "Yahoo Finance",
                "datetime": "2026-05-17T14:00:00Z",
                "confidence": 0.78,
            },
        ]

    @staticmethod
    def get_event_calendar(ticker: str, days_ahead: int = 30) -> dict:
        del ticker, days_ahead
        return {"as_of": "2026-05-18T00:00:00Z", "earnings_events": [{"date": "2026-07-25", "event": "earnings"}]}

    @staticmethod
    def score_news_source_reliability(source: str = "", url: str = "") -> dict:
        text = f"{source} {url}".lower()
        score = 0.9 if "reuters" in text else 0.78
        return {"reliability_score": score, "reliability_tier": "high" if score >= 0.85 else "medium"}


class _RiskTools:
    @staticmethod
    def get_stock_price(_ticker: str) -> dict:
        return {"price": 920.0, "change_percent": -5.4, "source": "fixture_quote"}

    @staticmethod
    def get_factor_exposure(_positions, lookback_days: int = 252) -> dict:
        del _positions, lookback_days
        return {
            "source": "fixture_factor_model",
            "factor_beta": {"market": 1.35, "growth": 1.55},
            "annualized_volatility": 0.42,
        }

    @staticmethod
    def run_portfolio_stress_test(_positions, lookback_days: int = 252) -> dict:
        del _positions, lookback_days
        return {
            "source": "fixture_stress_model",
            "worst_case_return": -0.16,
            "scenarios": [{"name": "rate shock", "return": -0.16}],
        }


def _evidence_ids(output) -> set[str]:
    return {
        item.meta.get("source_id")
        for item in output.evidence
        if isinstance(item.meta, dict) and item.meta.get("source_id")
    }


def _assert_claims_are_supported(output) -> None:
    evidence_ids = _evidence_ids(output)
    assert output.claims
    for claim in output.claims:
        assert claim.get("claim")
        assert set(claim.get("evidence_ids") or []).intersection(evidence_ids)
    assert output.evidence_quality["agent_quality"]["status"] == "pass"
    assert output.evidence_quality["agent_self_check"]["status"] == "pass"
    assert output.evidence_quality["agent_quality"]["metrics"]["claim_source_ratio"] == 1.0


@pytest.mark.asyncio
async def test_fundamental_agent_outputs_supported_native_claims() -> None:
    output = await FundamentalAgent(None, _Cache(), _FundamentalTools()).research(
        "AAPL 估值、风险、未来三个月看什么？",
        "AAPL",
    )

    assert len(output.claims) >= 3
    assert any(claim.get("metadata", {}).get("claim_type") == "growth_quality" for claim in output.claims)
    assert any(claim.get("metadata", {}).get("claim_type") == "eps_revision" for claim in output.claims)
    _assert_claims_are_supported(output)


@pytest.mark.asyncio
async def test_news_agent_outputs_catalyst_noise_and_calendar_claims() -> None:
    output = await NewsAgent(None, _Cache(), _NewsTools()).research(
        "AAPL 最近新闻哪些是真的催化剂，哪些只是噪音？",
        "AAPL",
    )

    claim_types = {claim.get("metadata", {}).get("claim_type") for claim in output.claims}
    assert {"catalyst_candidate", "noise_or_secondary_signal", "event_calendar"}.issubset(claim_types)
    _assert_claims_are_supported(output)


@pytest.mark.asyncio
async def test_risk_agent_outputs_scenario_level_native_claims() -> None:
    output = await RiskAgent(None, _Cache(), _RiskTools()).research("NVDA 现在主要风险是什么？", "NVDA")

    claim_types = {claim.get("metadata", {}).get("claim_type") for claim in output.claims}
    assert {"risk_score", "factor_exposure", "stress_test"}.issubset(claim_types)
    assert all(claim.get("stance") == "risk" for claim in output.claims)
    _assert_claims_are_supported(output)
