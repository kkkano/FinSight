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
async def test_news_agent_success(mock_llm, mock_cache, mock_tools, circuit_breaker):
    agent = NewsAgent(mock_llm, mock_cache, mock_tools, circuit_breaker)

    result = await agent.research("News for AAPL", "AAPL")

    assert result.agent_name == "NewsAgent"
    assert "Apple releases new iPhone" in result.summary
    assert len(result.evidence) >= 1
    assert result.evidence[0].source == "finnhub"

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
