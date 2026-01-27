"""
Router 单元测试
"""

import pytest
from finsight.orchestrator.router import Router, TickerExtraction
from finsight.domain.models import Intent, AnalysisRequest, ResponseMode


class TestRouter:
    """Router 测试类"""

    @pytest.fixture
    def router(self):
        """创建不带 LLM 的 Router"""
        return Router(llm_port=None)

    def test_extract_ticker_from_code(self, router):
        """测试从代码提取 ticker"""
        result = router._extract_tickers("AAPL 怎么样")
        assert "AAPL" in result.tickers

    def test_extract_ticker_from_alias(self, router):
        """测试从别名提取 ticker"""
        result = router._extract_tickers("苹果股票")
        assert "AAPL" in result.tickers

    def test_extract_ticker_with_dollar_sign(self, router):
        """测试带 $ 符号的 ticker"""
        result = router._extract_tickers("$TSLA 价格")
        assert "TSLA" in result.tickers

    def test_extract_multiple_tickers(self, router):
        """测试提取多个 ticker"""
        result = router._extract_tickers("比较 AAPL 和 MSFT")
        assert "AAPL" in result.tickers
        assert "MSFT" in result.tickers

    def test_rule_based_classify_price(self, router):
        """测试规则分类 - 价格查询"""
        intent, confidence = router._rule_based_classify("AAPL 股价多少")
        assert intent == Intent.STOCK_PRICE

    def test_rule_based_classify_news(self, router):
        """测试规则分类 - 新闻查询"""
        intent, confidence = router._rule_based_classify("特斯拉最新新闻")
        assert intent == Intent.STOCK_NEWS

    def test_rule_based_classify_analysis(self, router):
        """测试规则分类 - 分析请求"""
        intent, confidence = router._rule_based_classify("深度分析微软")
        assert intent == Intent.STOCK_ANALYSIS

    def test_rule_based_classify_sentiment(self, router):
        """测试规则分类 - 市场情绪"""
        intent, confidence = router._rule_based_classify("市场情绪如何")
        assert intent == Intent.MARKET_SENTIMENT

    def test_rule_based_classify_compare(self, router):
        """测试规则分类 - 资产对比"""
        intent, confidence = router._rule_based_classify("比较 AAPL 和 GOOGL")
        assert intent == Intent.COMPARE_ASSETS

    def test_rule_based_classify_macro(self, router):
        """测试规则分类 - 宏观事件"""
        intent, confidence = router._rule_based_classify("FOMC 会议日期")
        assert intent == Intent.MACRO_EVENTS

    def test_route_with_ticker(self, router):
        """测试完整路由 - 有 ticker"""
        request = AnalysisRequest(
            query="AAPL 股价",
            mode=ResponseMode.SUMMARY,
        )
        decision = router.route(request)
        assert decision.intent == Intent.STOCK_PRICE
        assert "ticker" in decision.extracted_params
        assert decision.extracted_params["ticker"] == "AAPL"

    def test_route_with_intent_hint(self, router):
        """测试带意图提示的路由"""
        request = AnalysisRequest(
            query="AAPL",
            mode=ResponseMode.SUMMARY,
            intent_hint=Intent.STOCK_ANALYSIS,
        )
        decision = router.route(request)
        assert decision.intent == Intent.STOCK_ANALYSIS
        assert decision.confidence == 1.0

    def test_route_unclear_needs_clarification(self, router):
        """测试不明确请求需要追问"""
        request = AnalysisRequest(
            query="嗯",
            mode=ResponseMode.SUMMARY,
        )
        decision = router.route(request)
        assert decision.needs_clarification
        assert decision.clarify_question is not None

    def test_route_missing_ticker(self, router):
        """测试缺少 ticker 需要追问"""
        request = AnalysisRequest(
            query="股票价格",
            mode=ResponseMode.SUMMARY,
        )
        decision = router.route(request)
        # 应该识别为价格查询但缺少 ticker
        assert decision.needs_clarification or "ticker" not in decision.extracted_params
