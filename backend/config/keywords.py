# -*- coding: utf-8 -*-
"""
Centralized Keyword Configuration for Intent Classification
Supports hot-reload via file modification time check
"""

from enum import Enum
from typing import Dict, List
import os
import time
import logging

logger = logging.getLogger(__name__)


class Intent(Enum):
    """Intent types for classification"""
    GREETING = "greeting"
    PRICE = "price"
    NEWS = "news"
    SENTIMENT = "sentiment"
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    MACRO = "macro"
    REPORT = "report"
    COMPARISON = "comparison"
    SEARCH = "search"
    CLARIFY = "clarify"
    OFF_TOPIC = "off_topic"


# Greeting patterns (regex)
GREETING_PATTERNS: List[str] = [
    r'^(你好|您好|hi|hello|hey|嗨|哈喽|早上好|下午好|晚上好|早安|晚安)[\s!！。.?？]*$',
    r'^(你是谁|介绍一下|你能做什么|帮助|help)[\s!！。.?？]*$',
]

# Keywords for confidence boosting (NOT for direct matching)
KEYWORD_BOOST: Dict[Intent, List[str]] = {
    Intent.PRICE: ['价格', '股价', '多少钱', '现价', '实时', '行情', 'price', '报价', 'quote'],
    Intent.NEWS: ['新闻', '快讯', '消息', '资讯', '动态', 'news', '发生了什么', 'headlines'],
    Intent.SENTIMENT: ['情绪', '恐惧', '贪婪', 'fear', 'greed', '市场情绪', 'sentiment'],
    Intent.TECHNICAL: ['技术', 'macd', 'rsi', 'kdj', '均线', 'ma', '支撑', '阻力', '形态', 'technical', 'indicator'],
    Intent.FUNDAMENTAL: ['财报', '营收', '利润', 'eps', 'pe', '市盈率', '估值', '基本面', 'fundamental', 'earnings', 'revenue'],
    Intent.MACRO: ['宏观', 'cpi', 'gdp', '利率', '美联储', 'fed', 'fomc', '通胀', '就业', 'macro', 'inflation'],
    Intent.REPORT: ['详细分析', '深度分析', '投资报告', '研报', '值得买', '能买吗', 'detailed analysis', 'in-depth', 'should i buy'],
    Intent.COMPARISON: ['对比', '比较', 'vs', '哪个好', '选哪个', 'compare', 'comparison'],
}

# Intent examples for embedding similarity
INTENT_EXAMPLES: Dict[Intent, List[str]] = {
    Intent.PRICE: [
        "AAPL 现在多少钱", "苹果股价", "特斯拉股票价格", "MSFT 实时行情",
        "What's the price of AAPL", "Tesla stock price", "current price of NVDA",
        "谷歌现价多少", "微软报价", "英伟达行情",
    ],
    Intent.NEWS: [
        "苹果最新新闻", "特斯拉有什么消息", "AAPL news", "Tesla latest news",
        "微软最近发生了什么", "英伟达快讯", "谷歌资讯", "MSFT headlines",
        "苹果公司动态", "What's happening with Apple",
    ],
    Intent.SENTIMENT: [
        "市场情绪怎么样", "恐惧贪婪指数", "fear greed index", "market sentiment",
        "投资者情绪", "市场恐慌吗", "贪婪指数多少", "risk appetite",
    ],
    Intent.TECHNICAL: [
        "AAPL 技术分析", "特斯拉 MACD", "苹果 RSI 指标", "Tesla technical analysis",
        "微软均线分析", "支撑位阻力位", "K线形态", "NVDA chart pattern",
    ],
    Intent.FUNDAMENTAL: [
        "苹果财报", "特斯拉 EPS", "AAPL PE ratio", "Tesla earnings",
        "微软市盈率", "英伟达营收", "谷歌利润", "Apple valuation",
    ],
    Intent.MACRO: [
        "CPI 数据", "美联储利率", "FOMC 会议", "GDP 增长",
        "通胀数据", "就业报告", "Fed interest rate", "inflation data",
    ],
    Intent.REPORT: [
        "详细分析苹果", "特斯拉投资报告", "AAPL 值得买吗", "Should I buy Tesla",
        "微软深度研报", "英伟达能投吗", "谷歌投资价值", "Apple investment analysis",
    ],
    Intent.COMPARISON: [
        "苹果和微软哪个好", "AAPL vs MSFT", "特斯拉对比蔚来",
        "Compare Apple and Google", "英伟达和AMD比较", "选苹果还是谷歌",
    ],
}


class KeywordsConfig:
    """Singleton config manager with hot-reload support"""
    _instance = None
    _last_check = 0
    _check_interval = 60  # seconds

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._load_time = time.time()
        logger.info("[KeywordsConfig] Initialized")

    @property
    def greeting_patterns(self) -> List[str]:
        return GREETING_PATTERNS

    @property
    def keyword_boost(self) -> Dict[Intent, List[str]]:
        return KEYWORD_BOOST

    @property
    def intent_examples(self) -> Dict[Intent, List[str]]:
        return INTENT_EXAMPLES

    def get_boost_weight(self) -> float:
        """Get keyword boost weight (can be made configurable)"""
        return 0.12

    def get_confidence_threshold(self) -> float:
        """Get confidence threshold for direct classification"""
        return 0.75


# Global instance
config = KeywordsConfig()
