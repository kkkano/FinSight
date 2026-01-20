# -*- coding: utf-8 -*-
"""
IntentClassifier 测试
验证混合意图分类器：规则 -> Embedding -> LLM
"""

import pytest
from backend.orchestration.intent_classifier import IntentClassifier, Intent, ClassificationResult


def _embedding_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
    except Exception:
        return False
    return True


class TestIntentClassifierRules:
    """测试规则快速通道"""

    def setup_method(self):
        self.classifier = IntentClassifier(llm=None)

    def test_greeting_intent(self):
        """测试问候意图 - 规则直接处理"""
        test_cases = ["你好", "您好", "hello", "Hi", "你是谁", "介绍一下"]
        for query in test_cases:
            result = self.classifier.classify(query, [])
            assert result.intent == Intent.GREETING, f"Failed for: {query}"
            assert result.method == "rule"

    def test_comparison_with_multiple_tickers(self):
        """测试多标的自动识别为对比"""
        result = self.classifier.classify("分析一下", ["AAPL", "MSFT"])
        assert result.intent == Intent.COMPARISON
        assert result.method == "rule"


class TestIntentClassifierEmbedding:
    """测试 Embedding 分类（需要 sentence-transformers）"""

    def setup_method(self):
        self.classifier = IntentClassifier(llm=None)

    @pytest.mark.skipif(
        not _embedding_available(),
        reason="sentence-transformers not installed"
    )
    def test_price_intent_embedding(self):
        """测试价格查询 - Embedding 相似度"""
        test_cases = [
            ("AAPL 价格", ["AAPL"]),
            ("苹果股价多少", ["AAPL"]),
            ("特斯拉现价", ["TSLA"]),
        ]
        for query, tickers in test_cases:
            result = self.classifier.classify(query, tickers)
            assert result.intent == Intent.PRICE, f"Failed for: {query}"
            assert "embedding" in result.method

    @pytest.mark.skipif(
        not _embedding_available(),
        reason="sentence-transformers not installed"
    )
    def test_news_intent_embedding(self):
        """测试新闻查询 - Embedding 相似度"""
        test_cases = [
            ("AAPL 新闻", ["AAPL"]),
            ("特斯拉最新消息", ["TSLA"]),
            ("苹果快讯", ["AAPL"]),
        ]
        for query, tickers in test_cases:
            result = self.classifier.classify(query, tickers)
            assert result.intent == Intent.NEWS, f"Failed for: {query}"

    @pytest.mark.skipif(
        not _embedding_available(),
        reason="sentence-transformers not installed"
    )
    def test_technical_intent_embedding(self):
        """测试技术分析 - Embedding 相似度"""
        test_cases = [
            ("AAPL 技术分析", ["AAPL"]),
            ("特斯拉 MACD", ["TSLA"]),
            ("苹果 RSI 指标", ["AAPL"]),
        ]
        for query, tickers in test_cases:
            result = self.classifier.classify(query, tickers)
            assert result.intent == Intent.TECHNICAL, f"Failed for: {query}"

    @pytest.mark.skipif(
        not _embedding_available(),
        reason="sentence-transformers not installed"
    )
    def test_fundamental_intent_embedding(self):
        """测试基本面 - Embedding 相似度"""
        test_cases = [
            ("AAPL 财报", ["AAPL"]),
            ("特斯拉 EPS", ["TSLA"]),
            ("苹果市盈率", ["AAPL"]),
        ]
        for query, tickers in test_cases:
            result = self.classifier.classify(query, tickers)
            assert result.intent == Intent.FUNDAMENTAL, f"Failed for: {query}"

    @pytest.mark.skipif(
        not _embedding_available(),
        reason="sentence-transformers not installed"
    )
    def test_report_intent_embedding(self):
        """测试深度报告 - 只有明确要求时才触发"""
        test_cases = [
            ("详细分析 AAPL", ["AAPL"]),
            ("TSLA 投资报告", ["TSLA"]),
            ("苹果值得买吗", ["AAPL"]),
        ]
        for query, tickers in test_cases:
            result = self.classifier.classify(query, tickers)
            assert result.intent == Intent.REPORT, f"Failed for: {query}"

    @pytest.mark.skipif(
        not _embedding_available(),
        reason="sentence-transformers not installed"
    )
    def test_sentiment_intent_embedding(self):
        """测试市场情绪"""
        test_cases = ["市场情绪怎么样", "恐惧贪婪指数", "fear greed index"]
        for query in test_cases:
            result = self.classifier.classify(query, [])
            assert result.intent == Intent.SENTIMENT, f"Failed for: {query}"

    @pytest.mark.skipif(
        not _embedding_available(),
        reason="sentence-transformers not installed"
    )
    def test_macro_intent_embedding(self):
        """测试宏观经济"""
        test_cases = ["CPI 数据", "美联储利率", "FOMC 会议"]
        for query in test_cases:
            result = self.classifier.classify(query, [])
            assert result.intent == Intent.MACRO, f"Failed for: {query}"


class TestIntentClassifierKeywordFallback:
    """测试关键词回退（Embedding 不可用时）"""

    def setup_method(self):
        self.classifier = IntentClassifier(llm=None)
        # 强制禁用 embedding
        self.classifier._embedding_classifier._model = False

    def test_price_keyword_fallback(self):
        """价格关键词回退"""
        result = self.classifier.classify("AAPL 价格", ["AAPL"])
        assert result.intent == Intent.PRICE

    def test_news_keyword_fallback(self):
        """新闻关键词回退"""
        result = self.classifier.classify("AAPL 新闻", ["AAPL"])
        assert result.intent == Intent.NEWS


class TestIntentClassifierCostSaving:
    """测试省钱特性"""

    def setup_method(self):
        self.classifier = IntentClassifier(llm=None)

    def test_simple_queries_no_llm(self):
        """简单查询不调用 LLM"""
        simple_queries = [
            ("你好", []),
            ("AAPL 价格", ["AAPL"]),
            ("特斯拉新闻", ["TSLA"]),
            ("市场情绪", []),
        ]
        for query, tickers in simple_queries:
            result = self.classifier.classify(query, tickers)
            assert result.method != "llm", f"Should not use LLM for: {query}"


class TestClassificationResult:
    """测试分类结果结构"""

    def setup_method(self):
        self.classifier = IntentClassifier(llm=None)

    def test_result_has_scores(self):
        """结果应包含各意图得分"""
        result = self.classifier.classify("AAPL 价格", ["AAPL"])
        assert hasattr(result, 'scores')
        assert isinstance(result.scores, dict)

    def test_result_has_method(self):
        """结果应包含分类方法"""
        result = self.classifier.classify("你好", [])
        assert result.method in ["rule", "embedding", "embedding+keyword", "llm", "fallback"]


def _embedding_available() -> bool:
    """检查 sentence-transformers 是否可用"""
    try:
        from sentence_transformers import SentenceTransformer
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
