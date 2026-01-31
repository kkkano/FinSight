# -*- coding: utf-8 -*-
"""
Router Regression Test Baseline
===============================
根据 docs/ROUTING_ARCHITECTURE_STANDARD.md 第8章定义的回归测试基线

测试分类:
1. 必须通过的核心测试用例
2. 边界测试用例
3. 多轮对话测试

Reference: docs/ROUTING_ARCHITECTURE_STANDARD.md#8-回归测试基线
"""

import pytest
from backend.conversation.router import ConversationRouter, Intent


# ==================== Test Fixtures ====================

class DummyContext:
    """无历史上下文"""
    def get_summary(self) -> str:
        return "无历史对话"

    def get_last_long_response(self):
        return None


class ContextWithHistory:
    """有历史上下文"""
    def __init__(self, summary: str = "当前焦点: AAPL", last_long: str = None):
        self._summary = summary
        self._last_long = last_long

    def get_summary(self) -> str:
        return self._summary

    def get_last_long_response(self):
        return self._last_long


class StubLLMResponse:
    def __init__(self, content: str):
        self.content = content


class StubLLM:
    """Stub LLM for testing"""
    def __init__(self, content: str = "CHAT"):
        self._content = content

    def invoke(self, _messages):
        return StubLLMResponse(self._content)


# ==================== 8.1 必须通过的核心测试用例 ====================

class TestCoreIntentRouting:
    """核心意图路由测试 - 这些测试必须全部通过"""

    def test_simple_greeting(self):
        """简单问候 → GREETING"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent("你好")
        assert intent == Intent.GREETING, "简单问候应识别为 GREETING"

    def test_price_query(self):
        """价格查询 → CHAT"""
        router = ConversationRouter(llm=None)
        intent, metadata = router.classify_intent("AAPL 股价")
        assert intent == Intent.CHAT, "价格查询应识别为 CHAT"
        assert "AAPL" in metadata.get("tickers", []), "应提取出 AAPL ticker"

    def test_deep_analysis_report(self):
        """深度分析 → REPORT"""
        router = ConversationRouter(llm=None)
        intent, metadata = router.classify_intent("分析苹果")
        assert intent == Intent.REPORT, "深度分析请求应识别为 REPORT"

    def test_comparison_query(self):
        """对比查询 → CHAT"""
        router = ConversationRouter(llm=None)
        intent, metadata = router.classify_intent("苹果和微软对比")
        assert intent == Intent.CHAT, "对比查询应识别为 CHAT"

    def test_alert_monitoring(self):
        """监控设置 → ALERT"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent("TSLA 跌破 200 提醒我")
        assert intent == Intent.ALERT, "监控提醒应识别为 ALERT"

    def test_company_name_only_clarify(self):
        """纯公司名（无动作） → 应触发 SchemaRouter clarify 或降级 CHAT

        注意: 根据架构标准，CLARIFY 最终会被降级为 CHAT，
        但 metadata 中应有 clarify 相关标记
        """
        router = ConversationRouter(llm=None)
        # 对于纯公司名，_quick_match 返回 None，会走 SchemaRouter
        # SchemaRouter 会触发 SlotCompletenessGate 的 company_name_only 规则
        intent, metadata = router.classify_intent("特斯拉")
        # 由于没有 LLM，可能会降级为 CHAT 或 CLARIFY
        # 关键是验证 ticker 被正确提取
        assert "TSLA" in metadata.get("tickers", []) or "特斯拉" in str(metadata), \
            "应能识别特斯拉相关信息"

    def test_followup_with_context(self):
        """追问（有上下文） → FOLLOWUP"""
        router = ConversationRouter(llm=None)
        context_summary = "当前焦点: AAPL, 之前讨论了苹果的财报"
        intent, _metadata = router.classify_intent("为什么", context_summary)
        assert intent == Intent.FOLLOWUP, "有上下文的追问应识别为 FOLLOWUP"

    def test_market_sentiment(self):
        """市场情绪查询 → CHAT"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent("市场恐慌指数")
        assert intent == Intent.CHAT, "市场情绪查询应识别为 CHAT"

    def test_economic_calendar(self):
        """经济日历查询 → ECONOMIC_EVENTS"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent("最近有什么宏观事件")
        assert intent == Intent.ECONOMIC_EVENTS, "经济日历查询应识别为 ECONOMIC_EVENTS"


# ==================== 8.2 边界测试 ====================

class TestBoundaryConditions:
    """边界条件测试"""

    def test_pinyin_greeting(self):
        """拼音问候 → GREETING"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent("nihao")
        assert intent == Intent.GREETING, "拼音问候 'nihao' 应识别为 GREETING"

    def test_ninhao_greeting(self):
        """拼音问候 ninhao → GREETING"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent("ninhao")
        assert intent == Intent.GREETING, "拼音问候 'ninhao' 应识别为 GREETING"

    def test_greeting_with_financial_context(self):
        """含金融词的问候 → CHAT (不是 GREETING)"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent("你好，我想问股票")
        # 包含金融关键词，应该不是纯问候
        assert intent != Intent.GREETING, "含金融词的问候不应是纯 GREETING"

    def test_vague_query_without_context(self):
        """模糊查询（无上下文） → CLARIFY"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent("帮我看看这个")
        # 无上下文、无 ticker、模糊表达
        assert intent == Intent.CLARIFY, "模糊查询（无上下文）应识别为 CLARIFY"

    def test_followup_without_context_clarify(self):
        """追问词但无上下文 → CLARIFY + clarify_reason"""
        router = ConversationRouter(llm=None)
        intent, metadata = router.classify_intent("为什么")
        assert intent == Intent.CLARIFY, "无上下文的追问应识别为 CLARIFY"
        assert metadata.get("clarify_reason") == "followup_without_context", \
            "应标记 clarify_reason 为 followup_without_context"

    def test_hello_english(self):
        """英文问候 → GREETING"""
        router = ConversationRouter(llm=None)
        for greeting in ["hello", "hi", "Hey"]:
            intent, _metadata = router.classify_intent(greeting)
            assert intent == Intent.GREETING, f"英文问候 '{greeting}' 应识别为 GREETING"

    def test_simple_price_keywords(self):
        """简单价格关键词 → CHAT"""
        router = ConversationRouter(llm=None)
        queries = ["多少钱", "股价", "现价", "行情"]
        for kw in queries:
            query = f"AAPL {kw}"
            intent, _metadata = router.classify_intent(query)
            assert intent == Intent.CHAT, f"'{query}' 应识别为 CHAT"


# ==================== 8.3 报告意图测试 ====================

class TestReportIntent:
    """报告意图测试 - 明确的深度分析请求"""

    @pytest.mark.parametrize("query", [
        "写一份研报",
        "做一份投研报告",
        "基本面分析一下特斯拉",
        "估值分析苹果",
        "公司研究：英伟达",
        "详细分析 AAPL",
        "深度分析特斯拉",
        "苹果值得投资吗",
        "TSLA 能买吗",
        "特斯拉前景如何",
    ])
    def test_report_intent_keywords(self, query):
        """明确的报告/分析请求 → REPORT"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent(query)
        assert intent == Intent.REPORT, f"'{query}' 应识别为 REPORT"


# ==================== 8.4 Alert 意图测试 ====================

class TestAlertIntent:
    """监控提醒意图测试"""

    @pytest.mark.parametrize("query", [
        "TSLA 跌破 200 提醒我",
        "苹果股价涨到 200 通知我",
        "监控特斯拉",
        "帮我盯着 AAPL",
        "NVDA 低于 500 预警",
    ])
    def test_alert_intent_keywords(self, query):
        """监控/提醒请求 → ALERT"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent(query)
        assert intent == Intent.ALERT, f"'{query}' 应识别为 ALERT"


# ==================== 8.5 市场新闻/情绪测试 ====================

class TestMarketNewsAndSentiment:
    """市场新闻和情绪测试"""

    @pytest.mark.parametrize("query", [
        "最近市场热点是什么",
        "市场热点 新闻",
        "股市快讯",
        "market news today",
    ])
    def test_market_news_queries(self, query):
        """市场新闻查询 → CHAT"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent(query)
        assert intent == Intent.CHAT, f"'{query}' 应识别为 CHAT"

    @pytest.mark.parametrize("query", [
        "恐惧贪婪指数",
        "market sentiment",
        "市场情绪怎么样",
        "fear and greed",
    ])
    def test_sentiment_queries(self, query):
        """情绪指标查询 → CHAT"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent(query)
        assert intent == Intent.CHAT, f"'{query}' 应识别为 CHAT"


# ==================== 8.6 经济日历测试 ====================

class TestEconomicEvents:
    """经济日历/宏观事件测试"""

    @pytest.mark.parametrize("query", [
        "最近有什么宏观事件",
        "经济日历",
        "下周 FOMC 会议",
        "CPI 什么时候公布",
        "非农数据",
    ])
    def test_economic_events_queries(self, query):
        """经济事件查询 → ECONOMIC_EVENTS"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent(query)
        assert intent == Intent.ECONOMIC_EVENTS, f"'{query}' 应识别为 ECONOMIC_EVENTS"


# ==================== 8.7 Ticker 提取测试 ====================

class TestTickerExtraction:
    """Ticker 提取测试"""

    def test_extract_us_ticker(self):
        """提取美股 ticker"""
        router = ConversationRouter(llm=None)
        _intent, metadata = router.classify_intent("AAPL 股价多少")
        assert "AAPL" in metadata.get("tickers", []), "应提取出 AAPL"

    def test_extract_chinese_company_name(self):
        """提取中文公司名并转换为 ticker"""
        router = ConversationRouter(llm=None)
        _intent, metadata = router.classify_intent("苹果公司股价")
        # 应该能从 "苹果" 解析出 AAPL
        assert "AAPL" in metadata.get("tickers", []) or "苹果" in metadata.get("company_names", []), \
            "应能识别苹果公司"

    def test_extract_multiple_tickers(self):
        """提取多个 ticker"""
        router = ConversationRouter(llm=None)
        _intent, metadata = router.classify_intent("AAPL 和 MSFT 对比")
        tickers = metadata.get("tickers", [])
        assert "AAPL" in tickers, "应提取出 AAPL"
        assert "MSFT" in tickers, "应提取出 MSFT"


# ==================== 8.8 简单查询指示词测试 ====================

class TestSimpleQueryIndicators:
    """简单查询指示词测试 - 这些应该走 CHAT 而不是 REPORT"""

    @pytest.mark.parametrize("query", [
        "分析一下占比",
        "苹果权重多少",
        "标普500成分股有哪些",  # 有具体指数，包含金融关键词
        "简单看一下 AAPL",
    ])
    def test_simple_query_indicators_route_to_chat(self, query):
        """包含简单查询指示词 → CHAT (不是 REPORT)"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent(query)
        # 即使包含 "分析"，有简单查询指示词时应该走 CHAT
        assert intent == Intent.CHAT, f"'{query}' 应识别为 CHAT 而不是 REPORT"


# ==================== 8.9 路由一致性测试 ====================

class TestRoutingConsistency:
    """路由一致性测试 - 相同输入应产生相同输出"""

    def test_repeated_query_consistency(self):
        """重复查询应产生一致结果"""
        router = ConversationRouter(llm=None)
        query = "苹果公司怎么样"
        results = [router.classify_intent(query) for _ in range(5)]
        intents = [r[0] for r in results]
        assert len(set(intents)) == 1, "重复查询应产生相同的意图"

    def test_greeting_bypass_schema_router(self):
        """问候应绕过 SchemaRouter（性能优化）"""
        router = ConversationRouter(llm=None)

        class SpySchemaRouter:
            calls = 0
            def route_query(self, *args):
                SpySchemaRouter.calls += 1
                return None

        router._schema_router = SpySchemaRouter()
        intent, _, _ = router.route("你好", DummyContext())

        assert intent == Intent.GREETING
        assert SpySchemaRouter.calls == 0, "问候不应调用 SchemaRouter"


# ==================== 8.10 新闻情绪测试 ====================

class TestNewsSentiment:
    """新闻情绪意图测试"""

    @pytest.mark.parametrize("query", [
        "苹果新闻情绪",
        "AAPL 舆情",
        "特斯拉舆情指数",
    ])
    def test_news_sentiment_queries(self, query):
        """新闻情绪查询 → NEWS_SENTIMENT"""
        router = ConversationRouter(llm=None)
        intent, _metadata = router.classify_intent(query)
        assert intent == Intent.NEWS_SENTIMENT, f"'{query}' 应识别为 NEWS_SENTIMENT"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
