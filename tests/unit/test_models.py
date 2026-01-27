"""
Domain 模型测试
"""

import pytest
from datetime import datetime
from decimal import Decimal

from finsight.domain.models import (
    Intent,
    ResponseMode,
    ErrorCode,
    StockPrice,
    CompanyInfo,
    NewsItem,
    MarketSentiment,
    EconomicEvent,
    AnalysisRequest,
    AnalysisResult,
    RouteDecision,
    ClarifyQuestion,
)
from finsight.presentation.report_writer import ReportFormat
from finsight.orchestrator.router import TickerExtraction


class TestEnums:
    """枚举测试"""

    def test_intent_enum(self):
        """测试意图枚举"""
        assert Intent.STOCK_PRICE.value == "stock_price"
        assert Intent.STOCK_NEWS.value == "stock_news"
        assert Intent.STOCK_ANALYSIS.value == "stock_analysis"
        assert Intent.COMPANY_INFO.value == "company_info"
        assert Intent.COMPARE_ASSETS.value == "compare_assets"
        assert Intent.MARKET_SENTIMENT.value == "market_sentiment"
        assert Intent.MACRO_EVENTS.value == "macro_events"
        assert Intent.UNCLEAR.value == "unclear"

    def test_response_mode_enum(self):
        """测试响应模式枚举"""
        assert ResponseMode.SUMMARY.value == "summary"
        assert ResponseMode.DEEP.value == "deep"

    def test_error_code_enum(self):
        """测试错误码枚举"""
        # 使用小写值
        assert ErrorCode.SUCCESS.value == "success"
        assert ErrorCode.INVALID_INPUT.value == "invalid_input"
        assert ErrorCode.TICKER_NOT_FOUND.value == "ticker_not_found"
        assert ErrorCode.DATA_UNAVAILABLE.value == "data_unavailable"
        assert ErrorCode.RATE_LIMITED.value == "rate_limited"
        assert ErrorCode.LLM_ERROR.value == "llm_error"
        assert ErrorCode.TIMEOUT.value == "timeout"
        assert ErrorCode.INTERNAL_ERROR.value == "internal_error"

    def test_report_format_enum(self):
        """测试报告格式枚举"""
        assert ReportFormat.MARKDOWN.value == "markdown"
        assert ReportFormat.TEXT.value == "text"
        assert ReportFormat.HTML.value == "html"


class TestStockPrice:
    """StockPrice 测试"""

    def test_stock_price_creation(self):
        """测试股票价格创建"""
        price = StockPrice(
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

        assert price.ticker == "AAPL"
        assert price.current_price == Decimal("175.50")
        assert price.currency == "USD"

    def test_stock_price_required_fields(self):
        """测试股票价格必填字段"""
        price = StockPrice(
            ticker="AAPL",
            current_price=Decimal("175.50"),
            change=Decimal("2.30"),
            change_percent=Decimal("1.33"),
        )

        assert price.ticker == "AAPL"
        assert price.change == Decimal("2.30")
        assert price.high_52w is None
        assert price.pe_ratio is None


class TestCompanyInfo:
    """CompanyInfo 测试"""

    def test_company_info_creation(self):
        """测试公司信息创建"""
        info = CompanyInfo(
            ticker="AAPL",
            name="Apple Inc.",
            sector="Technology",
            industry="Consumer Electronics",
            description="Apple Inc. designs, manufactures...",
            website="https://www.apple.com",
            employees=164000,
            headquarters="Cupertino, California",
        )

        assert info.ticker == "AAPL"
        assert info.name == "Apple Inc."
        assert info.sector == "Technology"


class TestNewsItem:
    """NewsItem 测试"""

    def test_news_item_creation(self):
        """测试新闻项创建"""
        news = NewsItem(
            title="Apple announces new iPhone",
            summary="Apple unveiled its latest iPhone model...",
            url="https://example.com/news/1",
            publisher="TechNews",
            published_at=datetime.now(),
        )

        assert news.title == "Apple announces new iPhone"
        assert news.publisher == "TechNews"


class TestMarketSentiment:
    """MarketSentiment 测试"""

    def test_market_sentiment_creation(self):
        """测试市场情绪创建"""
        sentiment = MarketSentiment(
            fear_greed_index=55,
            label="Neutral",
            previous_close=52,
            week_ago=48,
            month_ago=45,
            year_ago=60,
        )

        assert sentiment.fear_greed_index == 55
        assert sentiment.label == "Neutral"


class TestEconomicEvent:
    """EconomicEvent 测试"""

    def test_economic_event_creation(self):
        """测试经济事件创建"""
        event = EconomicEvent(
            date="2024-01-15",
            event="FOMC Meeting",
            time="14:00",
            country="US",
            impact="high",
        )

        assert event.date == "2024-01-15"
        assert event.event == "FOMC Meeting"
        assert event.impact == "high"


class TestAnalysisRequest:
    """AnalysisRequest 测试"""

    def test_analysis_request_creation(self):
        """测试分析请求创建"""
        request = AnalysisRequest(
            query="分析苹果股票",
            mode=ResponseMode.DEEP,
            request_id="test-001",
        )

        assert request.query == "分析苹果股票"
        assert request.mode == ResponseMode.DEEP
        assert request.request_id == "test-001"

    def test_analysis_request_defaults(self):
        """测试分析请求默认值"""
        request = AnalysisRequest(
            query="AAPL",
        )

        # 默认模式是 DEEP
        assert request.mode == ResponseMode.DEEP
        assert request.request_id is None
        assert request.intent_hint is None

    def test_analysis_request_with_intent_hint(self):
        """测试带意图提示的分析请求"""
        request = AnalysisRequest(
            query="AAPL",
            mode=ResponseMode.SUMMARY,
            intent_hint=Intent.STOCK_PRICE,
        )

        assert request.intent_hint == Intent.STOCK_PRICE


class TestAnalysisResult:
    """AnalysisResult 测试"""

    def test_analysis_result_success(self):
        """测试成功分析结果"""
        result = AnalysisResult(
            request_id="test-001",
            intent=Intent.STOCK_PRICE,
            mode=ResponseMode.SUMMARY,
            success=True,
            stock_price=StockPrice(
                ticker="AAPL",
                current_price=Decimal("175.50"),
                change=Decimal("2.30"),
                change_percent=Decimal("1.33"),
            ),
            tools_called=["get_stock_price"],
            latency_ms=150,
        )

        assert result.success
        assert result.intent == Intent.STOCK_PRICE
        assert result.stock_price is not None

    def test_analysis_result_failure(self):
        """测试失败分析结果"""
        result = AnalysisResult(
            request_id="test-001",
            intent=Intent.STOCK_PRICE,
            mode=ResponseMode.SUMMARY,
            success=False,
            error_code=ErrorCode.TICKER_NOT_FOUND,
            error_message="股票代码不存在",
        )

        assert not result.success
        assert result.error_code == ErrorCode.TICKER_NOT_FOUND

    def test_analysis_result_needs_clarification(self):
        """测试需要追问的分析结果"""
        result = AnalysisResult(
            request_id="test-001",
            intent=Intent.UNCLEAR,
            mode=ResponseMode.SUMMARY,
            needs_clarification=True,
            clarify_question=ClarifyQuestion(
                question="请问您想查询哪只股票？",
                field_name="ticker",
                reason="缺少股票代码",
            ),
        )

        assert result.needs_clarification
        assert result.clarify_question is not None
        assert result.clarify_question.question == "请问您想查询哪只股票？"


class TestRouteDecision:
    """RouteDecision 测试"""

    def test_route_decision_creation(self):
        """测试路由决策创建"""
        decision = RouteDecision(
            intent=Intent.STOCK_PRICE,
            confidence=0.95,
            extracted_params={"ticker": "AAPL"},
        )

        assert decision.intent == Intent.STOCK_PRICE
        assert decision.confidence == 0.95
        assert decision.extracted_params.get("ticker") == "AAPL"
        assert not decision.needs_clarification

    def test_route_decision_with_clarification(self):
        """测试需要追问的路由决策"""
        decision = RouteDecision(
            intent=Intent.UNCLEAR,
            confidence=0.3,
            needs_clarification=True,
            clarify_question=ClarifyQuestion(
                question="请提供更多信息",
                field_name="query",
                reason="输入不明确",
            ),
        )

        assert decision.needs_clarification
        assert decision.clarify_question is not None


class TestTickerExtraction:
    """TickerExtraction 测试"""

    def test_ticker_extraction_creation(self):
        """测试 ticker 提取结果创建"""
        extraction = TickerExtraction(
            tickers=["AAPL", "GOOGL"],
            confidence=0.95,
            method="regex",
        )

        assert "AAPL" in extraction.tickers
        assert "GOOGL" in extraction.tickers
        assert extraction.confidence == 0.95
        assert extraction.method == "regex"

    def test_ticker_extraction_empty(self):
        """测试空 ticker 提取"""
        extraction = TickerExtraction(
            tickers=[],
            confidence=0.0,
            method="regex",
        )

        assert len(extraction.tickers) == 0
        assert extraction.confidence == 0.0


class TestClarifyQuestion:
    """ClarifyQuestion 测试"""

    def test_clarify_question_creation(self):
        """测试追问问题创建"""
        question = ClarifyQuestion(
            question="请问您想查询哪只股票？",
            field_name="ticker",
            reason="输入中未提取到股票代码",
            options=["AAPL", "GOOGL", "MSFT"],
        )

        assert question.question == "请问您想查询哪只股票？"
        assert question.field_name == "ticker"
        assert "AAPL" in question.options

    def test_clarify_question_without_options(self):
        """测试无选项的追问问题"""
        question = ClarifyQuestion(
            question="请提供更多信息",
            field_name="query",
            reason="输入不明确",
        )

        assert question.options is None
