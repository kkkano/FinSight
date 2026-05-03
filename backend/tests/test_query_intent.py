# -*- coding: utf-8 -*-
"""Unit tests for backend.graph.nodes.query_intent."""

import pytest

from backend.graph.nodes.query_intent import has_financial_intent, is_casual_chat, is_greeting


class TestIsGreeting:
    @pytest.mark.parametrize(
        "query",
        [
            "你好",
            "您好",
            "哈喽",
            "嗨",
            "早",
            "早上好",
            "晚上好",
            "hi",
            "hello",
            "hey",
            "Hi!",
            "Hello.",
            "HEY!",
            "yo",
            "sup",
            "good morning",
            "Good Afternoon",
            "GOOD EVENING",
        ],
    )
    def test_greeting_detected(self, query: str):
        assert is_greeting(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "分析 AAPL",
            "NVDA 最新股价",
            "帮我看看特斯拉",
            "hello world 股票分析",
            "你好帮我分析苹果",
            "hi what is the price of TSLA",
            "",
            "   ",
        ],
    )
    def test_greeting_not_detected(self, query: str):
        assert is_greeting(query) is False


class TestIsCasualChat:
    @pytest.mark.parametrize(
        "query",
        [
            "你好",
            "hello",
            "谢谢",
            "感谢",
            "thanks",
            "thx",
            "好的",
            "嗯",
            "ok",
            "收到",
            "了解",
            "再见",
            "拜拜",
            "bye",
            "你是谁",
            "你叫什么",
            "你能做什么？",
            "你几岁了",
            "who are you?",
            "what can you do",
            "",
            "   ",
            "测试",
            "test",
        ],
    )
    def test_casual_detected(self, query: str):
        assert is_casual_chat(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "分析 AAPL",
            "NVDA 最新股价和技术面分析",
            "苹果财报怎么看？",
            "帮我生成投资报告",
            "特斯拉和比亚迪对比",
            "最近美股大盘怎么样",
            "黄金价格分析",
        ],
    )
    def test_casual_not_detected(self, query: str):
        assert is_casual_chat(query) is False


class TestHasFinancialIntent:
    """P0 expansion: high-frequency Chinese tickers / macros / ops should
    trigger early-pruning so chat_respond skips the slow Tier-2 LLM call.
    """

    @pytest.mark.parametrize(
        "query",
        [
            # Top US equities (Chinese names) — pre-P0 missed all of these
            "帮我看看苹果",
            "谷歌今天怎么样",
            "微软 AI 进展如何",
            "特斯拉要不要跑",
            "英伟达涨了多少",
            "奈飞财报",
            "台积电封测",
            # China ADR / HK
            "阿里巴巴股价",
            "腾讯怎么看",
            "京东最新动态",
            "拼多多季报",
            "网易游戏业务",
            "美团外卖业务对市值影响",
            "百度自动驾驶估值",
            "小米汽车销量",
            "蔚来交付",
            "理想汽车",
            "小鹏汽车",
            # Indices
            "纳指今天涨跌",
            "标普500 走势",
            "道指收盘",
            "上证指数",
            "恒指今天",
            # Sectors
            "科技股要不要加仓",
            "中概股最近怎么样",
            "半导体板块走势",
            "新能源板块",
            "医药板块",
            # Macro
            "CPI 数据出了吗",
            "PPI 影响哪些板块",
            "PMI 上行",
            "GDP 增速",
            "非农数据",
            "就业数据",
            "通胀压力",
            "缩表节奏",
            # Trading ops
            "建仓 NVDA",
            "清仓还是补仓",
            "加仓时机",
            "减仓信号",
            "套牢了怎么办",
            "割肉离场",
            "追高风险",
            "踏空了",
        ],
    )
    def test_p0_expansion_detected(self, query: str):
        """All P0-expansion vocabulary must trigger has_financial_intent=True."""
        assert has_financial_intent(query) is True, f"missed: {query!r}"

    @pytest.mark.parametrize(
        "query",
        [
            # Pure casual / OOS — must NOT trigger financial intent
            "你好",
            "今天心情不好",
            "陪我聊聊天",
            "推荐一首歌",
            "今天天气怎么样",
            "你叫什么",
            "在吗",
            "",
            "   ",
        ],
    )
    def test_pure_casual_not_detected(self, query: str):
        """Pure casual chat must remain non-financial."""
        assert has_financial_intent(query) is False, f"false positive: {query!r}"

    def test_punctuation_tolerance(self):
        assert is_casual_chat("谢谢？") is True
        assert is_casual_chat("你好。") is True
        assert is_casual_chat("ok!") is True
        assert is_casual_chat("再见！") is True

