# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from backend.agents.fundamental_agent import FundamentalAgent
from backend.agents.news_agent import NewsAgent
from backend.agents.price_agent import PriceAgent
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


class _NewsSentimentTools(_NewsTools):
    @staticmethod
    def get_news_sentiment(_ticker: str, limit: int = 8) -> str:
        del limit
        return """News Sentiment (AAPL):
平均情绪分数: 0.31
1. [2026-05-17] Apple services revenue beats expectations (Reuters) 情绪: Bullish (0.45)
2. [2026-05-16] Apple analyst target update (Yahoo Finance) 情绪: Somewhat-Bullish (0.18)
3. [2026-05-15] Apple faces supply chain caution (CNBC) 情绪: Somewhat-Bearish (-0.16)"""

    @staticmethod
    def get_stock_historical_data(_ticker: str, period: str = "5d", interval: str = "1d") -> dict:
        del period, interval
        return {
            "source": "fixture_history",
            "kline_data": [
                {"time": "2026-05-13", "close": 205.0},
                {"time": "2026-05-17", "close": 198.0},
            ],
        }


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


class _PriceTools:
    @staticmethod
    def _fetch_with_yfinance(_ticker: str) -> dict:
        return {
            "ticker": "AAPL",
            "price": 150.0,
            "currency": "USD",
            "change": 3.2,
            "change_percent": 2.3,
            "source": "fixture_quote",
            "as_of": "2026-05-31T00:00:00Z",
        }

    @staticmethod
    def get_stock_historical_data(ticker: str, period: str = "1y", interval: str = "1d") -> dict:
        del period, interval
        rows = []
        offset = 0.0 if ticker == "AAPL" else -20.0
        step = 1.25 if ticker == "AAPL" else 0.45
        for day in range(1, 90):
            close = 100.0 + offset + day * step
            rows.append(
                {
                    "time": f"2026-05-{(day % 28) + 1:02d}",
                    "open": close - 1.0,
                    "high": close + 2.0,
                    "low": close - 2.0,
                    "close": close,
                    "volume": 1_000_000 + day * 12_000,
                }
            )
        return {"ticker": ticker, "source": "fixture_history", "kline_data": rows}

    @staticmethod
    def get_option_chain_metrics(_ticker: str) -> dict:
        return {
            "source": "fixture_options",
            "as_of": "2026-05-31T00:00:00Z",
            "iv_atm": 0.31,
            "put_call_ratio_oi": 0.85,
            "iv_skew_25d": 0.02,
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
async def test_news_agent_outputs_aggregate_sentiment_snapshot_claims() -> None:
    output = await NewsAgent(None, _Cache(), _NewsSentimentTools()).research(
        "AAPL 最近整体舆情、催化事件和价格反应怎么看？",
        "AAPL",
    )

    snapshot_evidence = [item for item in output.evidence if item.source == "news_sentiment_snapshot"]
    assert snapshot_evidence
    snapshot = snapshot_evidence[0].meta.get("snapshot")
    assert snapshot["ticker"] == "AAPL"
    assert snapshot["sentiment_bias"]["label"] == "bullish"
    assert snapshot["sentiment_bias"]["positive_ratio"] > snapshot["sentiment_bias"]["negative_ratio"]
    assert snapshot["heat"]["news_count"] >= 2
    assert snapshot["catalyst_events"]["count"] >= 1
    assert snapshot["price_transmission"]["status"] == "divergence"

    claim_types = {claim.get("metadata", {}).get("claim_type") for claim in output.claims}
    assert {"sentiment_bias", "catalyst_events", "sentiment_price_divergence"}.issubset(claim_types)
    _assert_claims_are_supported(output)


@pytest.mark.asyncio
async def test_price_agent_outputs_price_behavior_native_claims() -> None:
    output = await PriceAgent(None, _Cache(), _PriceTools()).research(
        "AAPL 价格行为、相对强弱和关键价位风险怎么看？",
        "AAPL",
    )

    claim_types = {claim.get("metadata", {}).get("claim_type") for claim in output.claims}
    assert {"price_momentum", "relative_strength", "volume_confirmation", "volatility_regime", "key_level_risk"}.issubset(claim_types)
    assert "【价格状态】" in output.summary
    assert "【风险提示】" in output.summary
    _assert_claims_are_supported(output)


@pytest.mark.asyncio
async def test_risk_agent_outputs_scenario_level_native_claims() -> None:
    output = await RiskAgent(None, _Cache(), _RiskTools()).research("NVDA 现在主要风险是什么？", "NVDA")

    claim_types = {claim.get("metadata", {}).get("claim_type") for claim in output.claims}
    assert {"risk_score", "factor_exposure", "stress_test"}.issubset(claim_types)
    assert all(claim.get("stance") == "risk" for claim in output.claims)
    _assert_claims_are_supported(output)
