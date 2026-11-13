# -*- coding: utf-8 -*-
"""Tests for has_financial_intent (Tier 2) and resolve_subject three-tier gate."""

import pytest

from backend.graph.nodes.query_intent import has_financial_intent


class TestHasFinancialIntent:
    """Tier 2: high-precision keyword detection."""

    @pytest.mark.parametrize(
        "query",
        [
            # Unambiguous Chinese
            "股票分析",
            "AAPL 股价多少",
            "看看行情",
            "市盈率太高了",
            "这个季报怎么样",
            "K线看起来不错",
            "成交量放大了",
            "要不要止损",
            "美联储加息了",
            "现在牛市还是熊市",
            # Unambiguous English
            "stock price today",
            "earnings report looks good",
            "what's the P/E ratio",
            "NASDAQ is down",
            # Structural patterns
            "分析一下股票走势",
            "帮我看看基本面",
            "值得买入吗",
            "这个股价怎么看",
        ],
    )
    def test_financial_detected(self, query: str):
        assert has_financial_intent(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            # Clearly non-financial
            "你是男的还是女的",
            "你好吗",
            "今天天气怎么样",
            "讲个笑话",
            "你从哪里来",
            "帮我写个作文",
            "什么是人工智能",
            "1+1等于几",
            "你喜欢什么颜色",
            "推荐一本书",
            "how are you",
            "tell me a joke",
            "what is love",
            "",
            "   ",
        ],
    )
    def test_financial_not_detected(self, query: str):
        assert has_financial_intent(query) is False

    @pytest.mark.parametrize(
        "query",
        [
            # Ambiguous — these are NOT matched by Tier 2 (by design).
            # They'll fall through to Tier 3 LLM classification.
            "它最近怎么样",
            "帮我分析一下",
            "有什么风险",
            "收益如何",
        ],
    )
    def test_ambiguous_not_matched_tier2(self, query: str):
        """Ambiguous queries should NOT match Tier 2 (high precision only)."""
        assert has_financial_intent(query) is False
