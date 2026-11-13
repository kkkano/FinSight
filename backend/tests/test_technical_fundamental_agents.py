import pytest
from unittest.mock import MagicMock

from backend.agents.technical_agent import TechnicalAgent


class DummyCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value


def _build_kline(count=120, start=100.0):
    data = []
    for i in range(count):
        close = start + i * 0.5
        day = (i % 28) + 1
        data.append({
            "time": f"2025-01-{day:02d} 00:00",
            "open": close - 1,
            "high": close + 1,
            "low": close - 2,
            "close": close,
            "volume": 1000,
        })
    return data


@pytest.mark.asyncio
async def test_technical_agent_indicators():
    mock_llm = MagicMock()
    cache = DummyCache()
    tools = MagicMock()
    tools.get_stock_historical_data = MagicMock(return_value={
        "ticker": "AAPL",
        "kline_data": _build_kline(),
        "source": "mock_source",
    })

    agent = TechnicalAgent(mock_llm, cache, tools)
    result = await agent.research("technical analysis", "AAPL")

    assert result.agent_name == "technical"
    assert "RSI" in result.summary
    assert result.evidence
    assert "mock_source" in result.data_sources


@pytest.mark.asyncio
async def test_technical_agent_enriches_kline_with_quote_options_and_sentiment():
    cache = DummyCache()

    class Tools:
        def get_stock_historical_data(self, ticker, period="6mo", interval="1d"):
            return {
                "ticker": ticker,
                "kline_data": _build_kline(),
                "source": "mock_kline",
            }

        def get_stock_price(self, ticker):
            return {
                "ticker": ticker,
                "price": 190.5,
                "currency": "USD",
                "change_percent": 1.25,
                "source": "mock_quote",
                "as_of": "2026-05-21T10:00:00",
            }

        def get_option_chain_metrics(self, ticker):
            return {
                "ticker": ticker,
                "iv_atm": 0.32,
                "put_call_ratio_oi": 0.74,
                "iv_skew_25d": -0.04,
                "source": "mock_options",
                "as_of": "2026-05-21T10:00:00",
            }

        def get_market_sentiment(self):
            return "Fear & Greed Index: 62 (greed)"

    agent = TechnicalAgent(None, cache, Tools())

    result = await agent.research("AAPL technical analysis with IV and market sentiment", "AAPL")

    assert "mock_kline" in result.data_sources
    assert "mock_quote" in result.data_sources
    assert "mock_options" in result.data_sources
    assert "market_sentiment" in result.data_sources
    evidence_text = "\n".join(item.text for item in result.evidence)
    assert "Current quote" in evidence_text
    assert "Option metrics" in evidence_text
    assert "Market sentiment" in evidence_text
    assert "ATM IV" in result.summary
    assert "支撑" in result.summary
    assert "阻力" in result.summary
    assert "成交量" in result.summary


@pytest.mark.asyncio
async def test_technical_agent_uses_deterministic_summary():
    agent = TechnicalAgent(MagicMock(), DummyCache(), MagicMock())

    summary = await agent._first_summary(
        {
            "ticker": "AAPL",
            "kline_data": _build_kline(),
            "source": "mock_kline",
        }
    )

    assert "RSI" in summary
    assert "MACD" in summary
    assert "支撑" in summary
