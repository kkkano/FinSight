"""
测试配置 - pytest 配置和公共 fixtures
"""

import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, MagicMock

from finsight.domain.models import (
    StockPrice,
    CompanyInfo,
    NewsItem,
    MarketSentiment,
    AnalysisRequest,
    AnalysisResult,
    Intent,
    ResponseMode,
    PerformanceMetric,
    PerformanceComparison,
)


# ==================== Fixtures ====================

@pytest.fixture
def mock_stock_price():
    """模拟股票价格数据"""
    return StockPrice(
        ticker="AAPL",
        current_price=Decimal("175.50"),
        change=Decimal("2.30"),
        change_percent=Decimal("1.33"),
        currency="USD",
        high_52w=Decimal("199.62"),
        low_52w=Decimal("124.17"),
        volume=55000000,
        market_cap=Decimal("2800000000000"),
        pe_ratio=Decimal("28.5"),
        timestamp=datetime.now(),
    )


@pytest.fixture
def mock_company_info():
    """模拟公司信息"""
    return CompanyInfo(
        ticker="AAPL",
        name="Apple Inc.",
        sector="Technology",
        industry="Consumer Electronics",
        description="Apple Inc. designs, manufactures, and markets smartphones...",
        website="https://www.apple.com",
        employees=164000,
        headquarters="Cupertino, California",
    )


@pytest.fixture
def mock_news_items():
    """模拟新闻列表"""
    return [
        NewsItem(
            title="Apple announces new iPhone",
            summary="Apple unveiled its latest iPhone model...",
            url="https://example.com/news/1",
            publisher="TechNews",
            published_at=datetime.now(),
        ),
        NewsItem(
            title="Apple stock rises on earnings beat",
            summary="Shares of Apple rose after the company...",
            url="https://example.com/news/2",
            publisher="MarketWatch",
            published_at=datetime.now(),
        ),
    ]


@pytest.fixture
def mock_market_sentiment():
    """模拟市场情绪"""
    return MarketSentiment(
        fear_greed_index=55,
        label="Neutral",
        previous_close=52,
        week_ago=48,
        month_ago=45,
        year_ago=60,
    )


@pytest.fixture
def mock_analysis_request():
    """模拟分析请求"""
    return AnalysisRequest(
        query="分析苹果股票",
        mode=ResponseMode.DEEP,
        request_id="test-request-001",
    )


@pytest.fixture
def mock_performance_metrics():
    """模拟绩效指标列表"""
    return [
        PerformanceMetric(
            ticker="AAPL",
            name="Apple Inc.",
            period_return=Decimal("15.5"),
            period="1y",
        ),
        PerformanceMetric(
            ticker="GOOGL",
            name="Alphabet Inc.",
            period_return=Decimal("12.3"),
            period="1y",
        ),
    ]


@pytest.fixture
def mock_performance_comparison(mock_performance_metrics):
    """模拟资产对比结果"""
    return PerformanceComparison(
        assets=mock_performance_metrics,
        period="1y",
        timestamp=datetime.now(),
    )


@pytest.fixture
def mock_market_data_port(mock_stock_price, mock_company_info, mock_performance_comparison):
    """模拟市场数据端口"""
    port = Mock()
    port.get_stock_price.return_value = mock_stock_price
    port.get_company_info.return_value = mock_company_info
    port.get_performance_comparison.return_value = mock_performance_comparison
    return port


@pytest.fixture
def mock_news_port(mock_news_items):
    """模拟新闻端口"""
    port = Mock()
    port.get_company_news.return_value = mock_news_items
    return port


@pytest.fixture
def mock_sentiment_port(mock_market_sentiment):
    """模拟情绪端口"""
    port = Mock()
    port.get_market_sentiment.return_value = mock_market_sentiment
    return port


@pytest.fixture
def mock_search_port():
    """模拟搜索端口"""
    port = Mock()
    port.search.return_value = [
        {"title": "Search Result 1", "body": "Content 1"},
        {"title": "Search Result 2", "body": "Content 2"},
    ]
    return port


@pytest.fixture
def mock_time_port():
    """模拟时间端口"""
    port = Mock()
    port.get_current_datetime.return_value = datetime.now()
    port.get_formatted_datetime.return_value = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return port


@pytest.fixture
def mock_llm_port():
    """模拟 LLM 端口"""
    from finsight.domain.models import RouteDecision

    port = Mock()
    port.classify_intent.return_value = RouteDecision(
        intent=Intent.STOCK_ANALYSIS,
        confidence=0.95,
        extracted_params={"ticker": "AAPL"},
    )
    port.generate_report.return_value = "# 测试报告\n\n这是一份测试生成的报告。"
    return port
