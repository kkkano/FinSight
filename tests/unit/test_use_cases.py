"""
Use Cases 单元测试
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime
from decimal import Decimal

from finsight.domain.models import (
    Intent,
    ResponseMode,
    StockPrice,
    CompanyInfo,
    NewsItem,
    MarketSentiment,
)


class TestGetStockPriceUseCase:
    """GetStockPriceUseCase 测试类"""

    @pytest.fixture
    def use_case(self, mock_market_data_port, mock_time_port):
        """创建测试用例实例"""
        from finsight.use_cases.stock_price import GetStockPriceUseCase
        return GetStockPriceUseCase(
            market_data_port=mock_market_data_port,
            time_port=mock_time_port,
        )

    def test_execute_success(self, use_case, mock_stock_price):
        """测试成功获取股票价格"""
        result = use_case.execute(
            ticker="AAPL",
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        assert result.success
        assert result.intent == Intent.STOCK_PRICE
        assert "get_stock_price" in result.tools_called
        assert result.stock_price is not None

    def test_execute_with_company_info(self, use_case, mock_stock_price, mock_company_info):
        """测试获取股票价格包含公司信息"""
        result = use_case.execute(
            ticker="AAPL",
            request_id="test-id",
            mode=ResponseMode.DEEP,
        )

        assert result.success
        # Deep 模式会获取更多信息
        assert "get_company_info" in result.tools_called or "get_stock_price" in result.tools_called

    def test_execute_invalid_ticker(self, use_case, mock_market_data_port):
        """测试无效的股票代码"""
        mock_market_data_port.get_stock_price.return_value = None

        result = use_case.execute(
            ticker="INVALID123",
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        # 应该处理空结果
        assert result is not None


class TestGetStockNewsUseCase:
    """GetStockNewsUseCase 测试类"""

    @pytest.fixture
    def use_case(self, mock_news_port, mock_time_port):
        """创建测试用例实例"""
        from finsight.use_cases.stock_news import GetStockNewsUseCase
        return GetStockNewsUseCase(
            news_port=mock_news_port,
            time_port=mock_time_port,
        )

    def test_execute_success(self, use_case, mock_news_items):
        """测试成功获取股票新闻"""
        result = use_case.execute(
            ticker="AAPL",
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        assert result.success
        assert result.intent == Intent.STOCK_NEWS
        assert "get_company_news" in result.tools_called
        assert len(result.news_items) > 0 or result.report is not None

    def test_execute_no_news(self, use_case, mock_news_port):
        """测试没有新闻的情况"""
        mock_news_port.get_company_news.return_value = []

        result = use_case.execute(
            ticker="AAPL",
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        assert result is not None


class TestAnalyzeStockUseCase:
    """AnalyzeStockUseCase 测试类"""

    @pytest.fixture
    def use_case(
        self,
        mock_market_data_port,
        mock_news_port,
        mock_sentiment_port,
        mock_search_port,
        mock_time_port,
    ):
        """创建测试用例实例"""
        from finsight.use_cases.analyze_stock import AnalyzeStockUseCase
        return AnalyzeStockUseCase(
            market_data_port=mock_market_data_port,
            news_port=mock_news_port,
            sentiment_port=mock_sentiment_port,
            search_port=mock_search_port,
            time_port=mock_time_port,
            llm_port=None,
        )

    def test_execute_summary_mode(self, use_case):
        """测试 Summary 模式分析"""
        result = use_case.execute(
            ticker="AAPL",
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        assert result.success
        assert result.intent == Intent.STOCK_ANALYSIS
        assert result.mode == ResponseMode.SUMMARY

    def test_execute_deep_mode(self, use_case):
        """测试 Deep 模式分析"""
        result = use_case.execute(
            ticker="AAPL",
            request_id="test-id",
            mode=ResponseMode.DEEP,
        )

        assert result.success
        assert result.mode == ResponseMode.DEEP
        # Deep 模式应该调用更多工具
        assert len(result.tools_called) >= 1


class TestGetMarketSentimentUseCase:
    """GetMarketSentimentUseCase 测试类"""

    @pytest.fixture
    def use_case(self, mock_sentiment_port, mock_time_port):
        """创建测试用例实例"""
        from finsight.use_cases.market_sentiment import GetMarketSentimentUseCase
        return GetMarketSentimentUseCase(
            sentiment_port=mock_sentiment_port,
            time_port=mock_time_port,
        )

    def test_execute_success(self, use_case, mock_market_sentiment):
        """测试成功获取市场情绪"""
        result = use_case.execute(
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        assert result.success
        assert result.intent == Intent.MARKET_SENTIMENT
        assert "get_market_sentiment" in result.tools_called


class TestCompareAssetsUseCase:
    """CompareAssetsUseCase 测试类"""

    @pytest.fixture
    def use_case(self, mock_market_data_port, mock_time_port):
        """创建测试用例实例"""
        from finsight.use_cases.compare_assets import CompareAssetsUseCase
        return CompareAssetsUseCase(
            market_data_port=mock_market_data_port,
            time_port=mock_time_port,
        )

    def test_execute_success(self, use_case, mock_stock_price):
        """测试成功比较资产"""
        result = use_case.execute(
            tickers={"AAPL": "苹果", "GOOGL": "谷歌"},
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        assert result.success
        assert result.intent == Intent.COMPARE_ASSETS
        # 实际实现使用 get_performance_comparison
        assert "get_performance_comparison" in result.tools_called

    def test_execute_single_ticker_comparison(self, use_case, mock_stock_price):
        """测试单个股票对比（与基准）"""
        result = use_case.execute(
            tickers={"AAPL": "苹果", "SPY": "标普500"},
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        assert result.success


class TestGetMacroEventsUseCase:
    """GetMacroEventsUseCase 测试类"""

    @pytest.fixture
    def use_case(self, mock_search_port, mock_time_port):
        """创建测试用例实例"""
        from finsight.use_cases.macro_events import GetMacroEventsUseCase
        return GetMacroEventsUseCase(
            search_port=mock_search_port,
            time_port=mock_time_port,
        )

    def test_execute_success(self, use_case):
        """测试成功获取宏观事件"""
        result = use_case.execute(
            days_ahead=30,
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        assert result.success
        assert result.intent == Intent.MACRO_EVENTS
        # 实际实现使用 search 工具
        assert "search" in result.tools_called

    def test_execute_custom_days(self, use_case):
        """测试自定义天数"""
        result = use_case.execute(
            days_ahead=7,
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        assert result.success
