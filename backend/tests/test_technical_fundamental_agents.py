import pytest
from unittest.mock import MagicMock

from backend.agents.technical_agent import TechnicalAgent
from backend.agents.fundamental_agent import FundamentalAgent


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
async def test_fundamental_agent_financials():
    mock_llm = MagicMock()
    cache = DummyCache()
    tools = MagicMock()
    tools.get_company_info = MagicMock(return_value=(
        "Company Profile (AAPL):\n"
        "- Name: Apple Inc\n"
        "- Sector: Technology\n"
        "- Industry: Consumer Electronics\n"
        "- Market Cap: $1.2T\n"
    ))

    tools.get_financial_statements = MagicMock(return_value={
        "ticker": "AAPL",
        "timestamp": "2026-01-10T00:00:00",
        "financials": {
            "columns": ["2025-12-31", "2024-12-31"],
            "index": ["Total Revenue", "Net Income", "Operating Income"],
            "data": [
                {"2025-12-31": 120000000000, "2024-12-31": 100000000000},
                {"2025-12-31": 20000000000, "2024-12-31": 18000000000},
                {"2025-12-31": 25000000000, "2024-12-31": 20000000000},
            ],
        },
        "balance_sheet": {
            "columns": ["2025-12-31", "2024-12-31"],
            "index": ["Total Assets", "Total Liabilities"],
            "data": [
                {"2025-12-31": 350000000000, "2024-12-31": 330000000000},
                {"2025-12-31": 190000000000, "2024-12-31": 180000000000},
            ],
        },
        "cashflow": {
            "columns": ["2025-12-31", "2024-12-31"],
            "index": ["Operating Cash Flow"],
            "data": [
                {"2025-12-31": 28000000000, "2024-12-31": 26000000000},
            ],
        },
        "error": None,
    })

    agent = FundamentalAgent(mock_llm, cache, tools)
    result = await agent.research("fundamental analysis", "AAPL")

    assert result.agent_name == "fundamental"
    assert "Revenue" in result.summary
    assert result.evidence
