"""
Orchestrator 单元测试
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from decimal import Decimal

from finsight.orchestrator.orchestrator import Orchestrator, create_orchestrator
from finsight.orchestrator.router import Router
from finsight.domain.models import (
    Intent,
    AnalysisRequest,
    AnalysisResult,
    ResponseMode,
    RouteDecision,
    StockPrice,
    ClarifyQuestion,
    ErrorCode,
)


class TestOrchestrator:
    """Orchestrator 测试类"""

    @pytest.fixture
    def mock_ports(
        self,
        mock_market_data_port,
        mock_news_port,
        mock_sentiment_port,
        mock_search_port,
        mock_time_port,
    ):
        """创建模拟端口集合"""
        return {
            "market_data_port": mock_market_data_port,
            "news_port": mock_news_port,
            "sentiment_port": mock_sentiment_port,
            "search_port": mock_search_port,
            "time_port": mock_time_port,
        }

    @pytest.fixture
    def orchestrator(self, mock_ports):
        """创建测试用 Orchestrator"""
        return Orchestrator(**mock_ports)

    def test_orchestrator_initialization(self, mock_ports):
        """测试 Orchestrator 初始化"""
        orch = Orchestrator(**mock_ports)
        assert orch.market_data == mock_ports["market_data_port"]
        assert orch.news == mock_ports["news_port"]
        assert orch.sentiment == mock_ports["sentiment_port"]
        assert orch.search == mock_ports["search_port"]
        assert orch.time == mock_ports["time_port"]
        assert isinstance(orch.router, Router)
        assert not orch._initialized

    def test_lazy_init(self, orchestrator):
        """测试延迟初始化"""
        assert not orchestrator._initialized
        orchestrator._lazy_init()
        assert orchestrator._initialized
        assert len(orchestrator._use_cases) > 0
        assert Intent.STOCK_PRICE in orchestrator._use_cases
        assert Intent.STOCK_NEWS in orchestrator._use_cases
        assert Intent.STOCK_ANALYSIS in orchestrator._use_cases

    def test_lazy_init_idempotent(self, orchestrator):
        """测试延迟初始化幂等性"""
        orchestrator._lazy_init()
        first_use_cases = orchestrator._use_cases.copy()
        orchestrator._lazy_init()
        assert orchestrator._use_cases == first_use_cases

    def test_process_stock_price_query(self, orchestrator, mock_stock_price):
        """测试处理股票价格查询"""
        request = AnalysisRequest(
            query="AAPL 股价多少",
            mode=ResponseMode.SUMMARY,
        )

        # Mock use case execute
        with patch.object(orchestrator, '_execute_use_case') as mock_execute:
            mock_result = AnalysisResult(
                request_id="test-id",
                intent=Intent.STOCK_PRICE,
                mode=ResponseMode.SUMMARY,
                success=True,
            )
            mock_result.stock_price = mock_stock_price
            mock_result.tools_called = ["get_stock_price"]
            mock_execute.return_value = mock_result

            result = orchestrator.process(request)

            assert result is not None
            # process 方法会添加 'router' 到 tools_called
            assert "router" in result.tools_called or result.success

    def test_process_with_clarification_needed(self, orchestrator):
        """测试需要追问的情况"""
        request = AnalysisRequest(
            query="嗯",
            mode=ResponseMode.SUMMARY,
        )

        result = orchestrator.process(request)

        assert result.needs_clarification
        assert result.clarify_question is not None

    def test_process_news_query(self, orchestrator):
        """测试处理新闻查询"""
        request = AnalysisRequest(
            query="TSLA 最新新闻",
            mode=ResponseMode.SUMMARY,
        )

        with patch.object(orchestrator, '_execute_use_case') as mock_execute:
            mock_result = AnalysisResult(
                request_id="test-id",
                intent=Intent.STOCK_NEWS,
                mode=ResponseMode.SUMMARY,
                success=True,
            )
            mock_result.tools_called = ["get_stock_news"]
            mock_execute.return_value = mock_result

            result = orchestrator.process(request)
            assert result is not None

    def test_process_analysis_query(self, orchestrator):
        """测试处理分析查询"""
        request = AnalysisRequest(
            query="深度分析微软",
            mode=ResponseMode.DEEP,
        )

        with patch.object(orchestrator, '_execute_use_case') as mock_execute:
            mock_result = AnalysisResult(
                request_id="test-id",
                intent=Intent.STOCK_ANALYSIS,
                mode=ResponseMode.DEEP,
                success=True,
            )
            mock_result.tools_called = ["analyze_stock"]
            mock_execute.return_value = mock_result

            result = orchestrator.process(request)
            assert result is not None

    def test_process_market_sentiment_query(self, orchestrator, mock_market_sentiment):
        """测试处理市场情绪查询"""
        request = AnalysisRequest(
            query="市场情绪如何",
            mode=ResponseMode.SUMMARY,
        )

        with patch.object(orchestrator, '_execute_use_case') as mock_execute:
            mock_result = AnalysisResult(
                request_id="test-id",
                intent=Intent.MARKET_SENTIMENT,
                mode=ResponseMode.SUMMARY,
                success=True,
            )
            mock_result.market_sentiment = mock_market_sentiment
            mock_result.tools_called = ["get_market_sentiment"]
            mock_execute.return_value = mock_result

            result = orchestrator.process(request)
            assert result is not None

    def test_process_compare_query(self, orchestrator):
        """测试处理对比查询"""
        request = AnalysisRequest(
            query="比较 AAPL 和 GOOGL",
            mode=ResponseMode.SUMMARY,
        )

        with patch.object(orchestrator, '_execute_use_case') as mock_execute:
            mock_result = AnalysisResult(
                request_id="test-id",
                intent=Intent.COMPARE_ASSETS,
                mode=ResponseMode.SUMMARY,
                success=True,
            )
            mock_result.tools_called = ["compare_assets"]
            mock_execute.return_value = mock_result

            result = orchestrator.process(request)
            assert result is not None

    def test_process_with_exception(self, orchestrator):
        """测试处理异常情况"""
        request = AnalysisRequest(
            query="AAPL",
            mode=ResponseMode.SUMMARY,
        )

        # Mock router to raise exception
        with patch.object(orchestrator.router, 'route', side_effect=Exception("Test error")):
            result = orchestrator.process(request)

            assert not result.success
            assert result.error_code == ErrorCode.INTERNAL_ERROR
            assert "错误" in result.error_message

    def test_process_sets_latency(self, orchestrator):
        """测试延迟时间设置"""
        request = AnalysisRequest(
            query="嗯",
            mode=ResponseMode.SUMMARY,
        )

        result = orchestrator.process(request)

        assert result.latency_ms >= 0

    def test_create_orchestrator_factory(self, mock_ports):
        """测试工厂函数"""
        orch = create_orchestrator(**mock_ports)
        assert isinstance(orch, Orchestrator)


class TestOrchestratorUseCaseCreation:
    """测试用例创建"""

    @pytest.fixture
    def orchestrator(
        self,
        mock_market_data_port,
        mock_news_port,
        mock_sentiment_port,
        mock_search_port,
        mock_time_port,
    ):
        """创建测试用 Orchestrator"""
        return Orchestrator(
            market_data_port=mock_market_data_port,
            news_port=mock_news_port,
            sentiment_port=mock_sentiment_port,
            search_port=mock_search_port,
            time_port=mock_time_port,
        )

    def test_create_stock_price_use_case(self, orchestrator):
        """测试创建股票价格用例"""
        from finsight.use_cases.stock_price import GetStockPriceUseCase

        orchestrator._lazy_init()
        use_case_class = orchestrator._use_cases[Intent.STOCK_PRICE]

        use_case = orchestrator._create_use_case(use_case_class, Intent.STOCK_PRICE)
        assert isinstance(use_case, GetStockPriceUseCase)

    def test_create_stock_news_use_case(self, orchestrator):
        """测试创建股票新闻用例"""
        from finsight.use_cases.stock_news import GetStockNewsUseCase

        orchestrator._lazy_init()
        use_case_class = orchestrator._use_cases[Intent.STOCK_NEWS]

        use_case = orchestrator._create_use_case(use_case_class, Intent.STOCK_NEWS)
        assert isinstance(use_case, GetStockNewsUseCase)

    def test_create_analyze_stock_use_case(self, orchestrator):
        """测试创建股票分析用例"""
        from finsight.use_cases.analyze_stock import AnalyzeStockUseCase

        orchestrator._lazy_init()
        use_case_class = orchestrator._use_cases[Intent.STOCK_ANALYSIS]

        use_case = orchestrator._create_use_case(use_case_class, Intent.STOCK_ANALYSIS)
        assert isinstance(use_case, AnalyzeStockUseCase)

    def test_create_market_sentiment_use_case(self, orchestrator):
        """测试创建市场情绪用例"""
        from finsight.use_cases.market_sentiment import GetMarketSentimentUseCase

        orchestrator._lazy_init()
        use_case_class = orchestrator._use_cases[Intent.MARKET_SENTIMENT]

        use_case = orchestrator._create_use_case(use_case_class, Intent.MARKET_SENTIMENT)
        assert isinstance(use_case, GetMarketSentimentUseCase)

    def test_create_compare_assets_use_case(self, orchestrator):
        """测试创建资产对比用例"""
        from finsight.use_cases.compare_assets import CompareAssetsUseCase

        orchestrator._lazy_init()
        use_case_class = orchestrator._use_cases[Intent.COMPARE_ASSETS]

        use_case = orchestrator._create_use_case(use_case_class, Intent.COMPARE_ASSETS)
        assert isinstance(use_case, CompareAssetsUseCase)

    def test_create_macro_events_use_case(self, orchestrator):
        """测试创建宏观事件用例"""
        from finsight.use_cases.macro_events import GetMacroEventsUseCase

        orchestrator._lazy_init()
        use_case_class = orchestrator._use_cases[Intent.MACRO_EVENTS]

        use_case = orchestrator._create_use_case(use_case_class, Intent.MACRO_EVENTS)
        assert isinstance(use_case, GetMacroEventsUseCase)


class TestOrchestratorExecuteUseCase:
    """测试用例执行"""

    @pytest.fixture
    def orchestrator(
        self,
        mock_market_data_port,
        mock_news_port,
        mock_sentiment_port,
        mock_search_port,
        mock_time_port,
    ):
        """创建测试用 Orchestrator"""
        return Orchestrator(
            market_data_port=mock_market_data_port,
            news_port=mock_news_port,
            sentiment_port=mock_sentiment_port,
            search_port=mock_search_port,
            time_port=mock_time_port,
        )

    def test_execute_stock_price_missing_ticker(self, orchestrator):
        """测试执行股票价格用例但缺少 ticker"""
        mock_use_case = Mock()

        result = orchestrator._execute_use_case(
            use_case=mock_use_case,
            intent=Intent.STOCK_PRICE,
            params={},  # 缺少 ticker
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        assert not result.success
        assert result.error_code == ErrorCode.INVALID_INPUT
        assert result.needs_clarification

    def test_execute_compare_assets_missing_tickers(self, orchestrator):
        """测试执行资产对比用例但缺少足够 tickers"""
        mock_use_case = Mock()

        result = orchestrator._execute_use_case(
            use_case=mock_use_case,
            intent=Intent.COMPARE_ASSETS,
            params={"tickers": ["AAPL"]},  # 只有一个
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        # 应该与 SPY 默认对比
        mock_use_case.execute.assert_not_called()  # 因为只有一个，会尝试创建默认对比

    def test_execute_market_sentiment(self, orchestrator):
        """测试执行市场情绪用例"""
        mock_use_case = Mock()
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.MARKET_SENTIMENT,
            mode=ResponseMode.SUMMARY,
            success=True,
        )
        mock_use_case.execute.return_value = mock_result

        result = orchestrator._execute_use_case(
            use_case=mock_use_case,
            intent=Intent.MARKET_SENTIMENT,
            params={},
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        mock_use_case.execute.assert_called_once_with(
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

    def test_execute_macro_events(self, orchestrator):
        """测试执行宏观事件用例"""
        mock_use_case = Mock()
        mock_result = AnalysisResult(
            request_id="test-id",
            intent=Intent.MACRO_EVENTS,
            mode=ResponseMode.SUMMARY,
            success=True,
        )
        mock_use_case.execute.return_value = mock_result

        result = orchestrator._execute_use_case(
            use_case=mock_use_case,
            intent=Intent.MACRO_EVENTS,
            params={"days_ahead": 7},
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )

        mock_use_case.execute.assert_called_once_with(
            days_ahead=7,
            request_id="test-id",
            mode=ResponseMode.SUMMARY,
        )
