# -*- coding: utf-8 -*-
"""Unit tests for backend.graph.nodes.query_intent"""

import pytest

from backend.graph.nodes.query_intent import is_casual_chat, is_greeting


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
            "苹果财报怎么看",
            "帮我生成投资报告",
            "特斯拉和比亚迪对比",
            "最近美股大盘怎么样",
            "黄金价格分析",
        ],
    )
    def test_casual_not_detected(self, query: str):
        assert is_casual_chat(query) is False

    def test_punctuation_tolerance(self):
        assert is_casual_chat("谢谢！") is True
        assert is_casual_chat("你好。") is True
        assert is_casual_chat("ok!") is True
        assert is_casual_chat("再见？") is True
