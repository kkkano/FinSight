import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from backend.agents.price_agent import PriceAgent, AllSourcesFailedError
from backend.agents.news_agent import NewsAgent
from backend.services.circuit_breaker import CircuitBreaker

@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.get.return_value = None
    return cache

@pytest.fixture
def mock_llm():
    return AsyncMock()

@pytest.fixture
def mock_tools():
    tools = MagicMock()
    # Mock price tool
    tools._fetch_with_yfinance = MagicMock(return_value={"price": 150.0, "currency": "USD", "source": "yfinance", "as_of": "2023-01-01"})
    # Mock news tool
    tools._fetch_with_finnhub_news = MagicMock(return_value=[
        {"headline": "Apple releases new iPhone", "url": "http://apple.com", "source": "finnhub", "datetime": "2023-01-01"}
    ])
    tools._search_company_news = MagicMock(return_value=[
        {"title": "Apple stock soars", "url": "http://news.com", "source": "tavily", "published_at": "2023-01-01"}
    ])
    return tools

@pytest.fixture
def circuit_breaker():
    return CircuitBreaker()

@pytest.mark.asyncio
async def test_price_agent_success(mock_llm, mock_cache, mock_tools, circuit_breaker):
    agent = PriceAgent(mock_llm, mock_cache, mock_tools, circuit_breaker)

    result = await agent.research("Get AAPL price", "AAPL")

    assert result.agent_name == "PriceAgent"
    assert "150.0" in result.summary
    assert result.confidence == 1.0
    mock_tools._fetch_with_yfinance.assert_called_once_with("AAPL")

@pytest.mark.asyncio
async def test_price_agent_fallback(mock_llm, mock_cache, mock_tools, circuit_breaker):
    # Simulate yfinance failure
    mock_tools._fetch_with_yfinance.side_effect = Exception("API Error")
    mock_tools._fetch_with_finnhub = MagicMock(return_value={"price": 151.0, "currency": "USD", "source": "finnhub", "as_of": "2023-01-01"})

    agent = PriceAgent(mock_llm, mock_cache, mock_tools, circuit_breaker)

    result = await agent.research("Get AAPL price", "AAPL")

    assert "151.0" in result.summary
    assert result.data_sources == ["finnhub"]
    # Should have tried yfinance first
    mock_tools._fetch_with_yfinance.assert_called_once()
    mock_tools._fetch_with_finnhub.assert_called_once()


@pytest.mark.asyncio
async def test_price_agent_enriches_option_metrics(mock_llm, mock_cache, mock_tools, circuit_breaker):
    mock_tools.get_option_chain_metrics = MagicMock(return_value={
        "ticker": "AAPL",
        "source": "yfinance_options",
        "as_of": "2026-02-18T00:00:00",
        "iv_atm": 0.28,
        "put_call_ratio_oi": 0.92,
        "iv_skew_25d": 0.03,
        "error": None,
    })

    agent = PriceAgent(mock_llm, mock_cache, mock_tools, circuit_breaker)
    result = await agent.research("Get AAPL price", "AAPL")

    assert any(item.source == "yfinance_options" for item in result.evidence)
    assert "yfinance_options" in result.data_sources


@pytest.mark.asyncio
async def test_price_agent_initial_search_returns_price_behavior_snapshot(mock_llm, mock_cache, mock_tools, circuit_breaker):
    def _history(_ticker, period="1y", interval="1d"):
        rows = []
        for day in range(1, 81):
            close = 100.0 + day
            rows.append(
                {
                    "time": f"2026-03-{(day % 28) + 1:02d}",
                    "open": close - 1.0,
                    "high": close + 2.0,
                    "low": close - 2.0,
                    "close": close,
                    "volume": 1_000_000 + day * 10_000,
                }
            )
        return {"ticker": _ticker, "period": period, "interval": interval, "source": "test_history", "kline_data": rows}

    mock_tools.get_stock_historical_data = MagicMock(side_effect=_history)
    mock_tools.get_option_chain_metrics = MagicMock(
        return_value={
            "ticker": "AAPL",
            "source": "yfinance_options",
            "as_of": "2026-05-31T00:00:00",
            "iv_atm": 0.31,
            "put_call_ratio_oi": 0.85,
            "iv_skew_25d": 0.02,
            "error": None,
        }
    )

    agent = PriceAgent(mock_llm, mock_cache, mock_tools, circuit_breaker)
    snapshot = await agent._initial_search("Analyze AAPL price behavior", "AAPL")

    assert snapshot["snapshot_type"] == "PriceBehaviorSnapshot"
    assert snapshot["quote"]["price"] == 150.0
    assert snapshot["trend"]["returns"]["1mo"] is not None
    assert snapshot["momentum"]["close_vs_sma20_pct"] is not None
    assert snapshot["volume_price"]["volume_ratio20"] is not None
    assert snapshot["relative_strength"]["benchmarks"]["SPY"]["rs_1mo"] is not None
    assert snapshot["volatility_structure"]["atr14"] is not None
    assert snapshot["key_levels"]["support_20d"] is not None
    assert snapshot["options"]["iv_atm"] == 0.31


def test_price_agent_snapshot_summary_is_multisection(mock_cache, mock_tools, circuit_breaker):
    agent = PriceAgent(None, mock_cache, mock_tools, circuit_breaker)
    snapshot = {
        "snapshot_type": "PriceBehaviorSnapshot",
        "ticker": "AAPL",
        "as_of": "2026-05-31T00:00:00",
        "quote": {
            "ticker": "AAPL",
            "price": 150.0,
            "currency": "USD",
            "change": 3.2,
            "change_percent": 2.3,
            "source": "fixture_quote",
            "as_of": "2026-05-31T00:00:00",
        },
        "trend": {
            "direction": "uptrend",
            "returns": {"1d": 2.3, "1w": 4.1, "1mo": 8.2, "3mo": 12.5},
            "history_points": 80,
        },
        "momentum": {
            "state": "positive",
            "close_vs_sma20_pct": 3.4,
            "close_vs_sma50_pct": 6.8,
        },
        "volume_price": {
            "volume_ratio20": 1.42,
            "price_change_1d": 2.3,
            "signal": "price_up_volume_confirmed",
        },
        "relative_strength": {
            "benchmarks": {
                "SPY": {"rs_1mo": 4.8, "rs_3mo": 7.1},
                "QQQ": {"rs_1mo": 2.2, "rs_3mo": 3.0},
            }
        },
        "volatility_structure": {
            "realized_volatility": {"20d": 24.2, "60d": 28.0},
            "atr14_pct": 2.1,
            "max_drawdown": -12.4,
            "drawdown_from_high": -3.6,
        },
        "options": {
            "source": "fixture_options",
            "as_of": "2026-05-31T00:00:00",
            "iv_atm": 0.31,
            "put_call_ratio": 0.85,
            "iv_skew_25d": 0.02,
        },
        "key_levels": {
            "support_20d": 142.5,
            "resistance_20d": 153.8,
            "distance_to_support_20d_pct": 5.3,
            "distance_to_resistance_20d_pct": -2.5,
        },
        "event_explanation": {
            "trigger": "large_price_move",
            "change_percent": 2.3,
            "summary": "price moved with earnings guidance",
            "source": "fixture_event",
        },
    }

    summary = agent._deterministic_summary(snapshot)

    for heading in ("价格状态", "趋势与动量", "量价关系", "相对强弱RS", "波动率与期权结构", "关键价位", "风险提示"):
        assert f"【{heading}】" in summary
    assert "\n" in summary
    assert "USD 150.0" in summary
    assert "+2.30%" in summary
    assert "1mo +8.20%" in summary
    assert "SPY: 1mo +4.80pct" in summary
    assert "ATM IV 31.00%" in summary


def test_price_agent_format_output_uses_short_summary_without_length_gate(mock_cache, mock_tools, circuit_breaker):
    agent = PriceAgent(None, mock_cache, mock_tools, circuit_breaker)

    output = agent._format_output(
        "短摘要但应保留。",
        {
            "ticker": "AAPL",
            "price": 150.0,
            "currency": "USD",
            "change_percent": 1.2,
            "source": "fixture_quote",
            "as_of": "2026-05-31T00:00:00",
        },
    )

    assert output.summary == "短摘要但应保留。"


def test_price_agent_snapshot_output_adds_metric_evidence_and_native_claims(mock_cache, mock_tools, circuit_breaker):
    agent = PriceAgent(None, mock_cache, mock_tools, circuit_breaker)
    snapshot = {
        "snapshot_type": "PriceBehaviorSnapshot",
        "ticker": "AAPL",
        "as_of": "2026-05-31T00:00:00",
        "quote": {
            "ticker": "AAPL",
            "price": 150.0,
            "currency": "USD",
            "change_percent": 2.3,
            "source": "fixture_quote",
            "as_of": "2026-05-31T00:00:00",
        },
        "trend": {"direction": "uptrend", "returns": {"1mo": 8.2, "3mo": 12.5}},
        "momentum": {"state": "positive", "close_vs_sma20_pct": 3.4},
        "volume_price": {"volume_ratio20": 1.42, "price_change_1d": 2.3, "signal": "price_up_volume_confirmed"},
        "relative_strength": {"benchmarks": {"SPY": {"rs_1mo": 4.8, "rs_3mo": 7.1}}},
        "volatility_structure": {"atr14_pct": 2.1, "max_drawdown": -12.4, "drawdown_from_high": -3.6},
        "options": {"source": "fixture_options", "as_of": "2026-05-31T00:00:00", "iv_atm": 0.31, "put_call_ratio": 0.85},
        "key_levels": {
            "support_20d": 142.5,
            "resistance_20d": 153.8,
            "distance_to_support_20d_pct": 5.3,
            "distance_to_resistance_20d_pct": -2.5,
        },
    }

    output = agent._format_output("ignored one-line summary", snapshot)

    metric_keys = {item.meta.get("metric_key") for item in output.evidence if isinstance(item.meta, dict)}
    assert {"price_quote", "price_momentum", "volume_confirmation", "relative_strength", "volatility_regime", "key_level_risk"}.issubset(metric_keys)
    claim_types = {claim.get("metadata", {}).get("claim_type") for claim in output.claims}
    assert {"price_momentum", "relative_strength", "volume_confirmation", "volatility_regime", "key_level_risk"}.issubset(claim_types)
    evidence_ids = {
        item.meta.get("source_id")
        for item in output.evidence
        if isinstance(item.meta, dict) and item.meta.get("source_id")
    }
    assert all(set(claim.get("evidence_ids") or []).intersection(evidence_ids) for claim in output.claims)

@pytest.mark.asyncio
async def test_news_agent_success(mock_llm, mock_cache, mock_tools, circuit_breaker):
    agent = NewsAgent(mock_llm, mock_cache, mock_tools, circuit_breaker)

    result = await agent.research("News for AAPL", "AAPL")

    assert result.agent_name == "NewsAgent"
    assert "Apple releases new iPhone" in result.summary
    assert len(result.evidence) >= 1
    assert result.evidence[0].source == "finnhub"


@pytest.mark.asyncio
async def test_news_agent_adds_event_calendar_evidence(mock_llm, mock_cache, mock_tools, circuit_breaker):
    mock_tools.get_event_calendar = MagicMock(return_value={
        "ticker": "AAPL",
        "as_of": "2026-02-18T00:00:00",
        "earnings_events": [{"date": "2026-03-01", "title": "Earnings Date"}],
        "dividend_events": [],
        "macro_events": [{"date": None, "title": "Monitor CPI release window"}],
    })
    mock_tools.score_news_source_reliability = MagicMock(return_value={
        "reliability_score": 0.9,
        "reliability_tier": "high",
        "reason": "domain:reuters.com",
    })

    agent = NewsAgent(mock_llm, mock_cache, mock_tools, circuit_breaker)
    result = await agent.research("News for AAPL", "AAPL")

    assert any(item.source == "event_calendar" for item in result.evidence)

@pytest.mark.asyncio
async def test_news_agent_deduplication(mock_llm, mock_cache, mock_tools, circuit_breaker):
    # Setup tools to return same URL from both sources
    mock_tools._fetch_with_finnhub_news.return_value = [
        {"headline": "News A", "url": "http://same.com", "source": "finnhub"}
    ]
    mock_tools._search_company_news.return_value = [
        {"title": "News A Duplicate", "url": "http://same.com", "source": "tavily"}
    ]

    # Ensure fallback triggers
    agent = NewsAgent(mock_llm, mock_cache, mock_tools, circuit_breaker)

    # We force fallback logic by making finnhub return only 1 item (less than 3)
    # so it tries tavily too.

    result = await agent.research("News for AAPL", "AAPL")

    # Should only have 1 evidence due to deduplication on URL
    assert len(result.evidence) == 1
    assert result.evidence[0].url == "http://same.com"


@pytest.mark.asyncio
async def test_news_agent_finance_query_prefers_authoritative_domains(
    mock_llm,
    mock_cache,
    mock_tools,
    circuit_breaker,
    monkeypatch,
):
    monkeypatch.setenv("NEWS_STRICT_FINANCE_SOURCES", "true")
    mock_tools._fetch_with_finnhub_news.return_value = [
        {
            "headline": "Apple revenue beat estimates",
            "url": "https://www.reuters.com/technology/apple-reports-quarterly-results-2026-02-13/",
            "source": "Reuters",
            "datetime": "2026-02-13",
        },
        {
            "headline": "Random finance blog post",
            "url": "https://random-finance.cc/apple-aapl-hot-take",
            "source": "Blog",
            "datetime": "2026-02-13",
        },
    ]

    agent = NewsAgent(mock_llm, mock_cache, mock_tools, circuit_breaker)
    result = await agent.research(
        "请做 Apple 深度投资报告（deep report，重点引用 10-K 与业绩电话会）",
        "AAPL",
    )

    urls = [item.url or "" for item in result.evidence]
    assert any("reuters.com" in url for url in urls)
    assert all("random-finance.cc" not in url for url in urls)
