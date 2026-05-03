# -*- coding: utf-8 -*-
"""Lightweight, rule-based query intent detection.

No LLM call here: only token and regex matching.
Used by `chat_respond` to short-circuit greetings/casual chat
before `resolve_subject` processes the query.
"""

from __future__ import annotations

import re

# ==================== Greeting tokens ====================
_GREETING_TOKENS: frozenset[str] = frozenset(
    {
        # English
        "hi",
        "hello",
        "hey",
        "yo",
        "sup",
        "greetings",
        "howdy",
        "good morning",
        "good afternoon",
        "good evening",
        # Chinese
        "你好",
        "您好",
        "哈喽",
        "嗨",
        "早",
        "早上好",
        "上午好",
        "下午好",
        "晚上好",
        "晚安",
    }
)

_GREETING_RE = re.compile(
    r"^(hi|hello|hey|yo|sup|howdy|greetings|good\s*(morning|afternoon|evening))[!.\s]*$",
    re.IGNORECASE,
)

# ==================== Casual chat tokens ====================
_CASUAL_EXACT: frozenset[str] = frozenset(
    {
        # Chinese
        "谢谢",
        "感谢",
        "多谢",
        "辛苦了",
        "好的",
        "好",
        "嗯",
        "啊",
        "在吗",
        "行",
        "了解",
        "明白",
        "收到",
        "知道了",
        "再见",
        "拜拜",
        "晚安",
        # English
        "bye",
        "goodbye",
        "thanks",
        "thank you",
        "thx",
        "ty",
        "got it",
        "okay",
        "ok",
        "sure",
        "cool",
        "nice",
        "great",
    }
)

_CASUAL_PATTERNS = re.compile(
    r"^("
    r"你是谁|你叫什么|你是做什么的|你能做什么|你会什么|你几岁了|你多大了"
    r"|who\s+are\s+you|what\s+can\s+you\s+do|what\s+are\s+you|how\s+old\s+are\s+you"
    r"|今天天气|天气怎么样|几点了|现在几点"
    r"|测试|test"
    r")[？?!。！，,\s]*$",
    re.IGNORECASE,
)

_TRAILING_PUNCT_RE = re.compile(r"[？?!。！，,\s]+$")


def is_greeting(query: str) -> bool:
    """Detect pure greetings, e.g. `你好`, `hello`, `hey`."""
    cleaned = (query or "").strip().lower()
    if not cleaned:
        return False
    stripped = _TRAILING_PUNCT_RE.sub("", cleaned)
    if stripped in _GREETING_TOKENS:
        return True
    return bool(_GREETING_RE.fullmatch(cleaned))


def is_casual_chat(query: str) -> bool:
    """Detect casual/non-analytical queries.

    This is a superset of greeting detection.
    """
    if is_greeting(query):
        return True

    cleaned = (query or "").strip().lower()
    if not cleaned:
        return True

    stripped = _TRAILING_PUNCT_RE.sub("", cleaned)
    if stripped in _CASUAL_EXACT:
        return True

    return bool(_CASUAL_PATTERNS.fullmatch(cleaned))


# ==================== Financial intent detection (Tier 2) ====================
# Precision > Recall:
# - False negative: acceptable (route to clarify)
# - False positive: unacceptable (binds wrong active_symbol)

_FINANCIAL_TOKENS_HP: frozenset[str] = frozenset(
    {
        # Chinese
        "股票",
        "股价",
        "行情",
        "涨停",
        "跌停",
        "涨幅",
        "跌幅",
        "基本面",
        "技术面",
        "估值",
        "市盈率",
        "市净率",
        "市值",
        "营收",
        "财报",
        "k线",
        "均线",
        "成交量",
        "换手率",
        "资金流",
        "持仓",
        "仓位",
        "买入",
        "卖出",
        "看涨",
        "看跌",
        "做空",
        "做多",
        "多头",
        "空头",
        "大盘",
        "增持",
        "减持",
        "回购",
        "分红",
        "配股",
        "新股",
        "季报",
        "年报",
        "半年报",
        "毛利率",
        "净利率",
        "美联储",
        "加息",
        "降息",
        "牛市",
        "熊市",
        "止损",
        "止盈",
        "抄底",
        "对冲",
        "套利",
        "目标价",
        "评级",
        "研报",
        # ----- P0 expansion (2026-05-03): high-frequency Chinese tickers/macros/ops -----
        # Top US equities (Chinese names) — 跑测发现「苹果/谷歌/微软/英伟达」等
        # 高频中文公司名缺席导致 has_financial_intent 不命中，让 chat_respond
        # 误进 Tier-2 LLM 跑 5-12s。这些词进白名单后 0ms 直通业务管道。
        # 风险评估：「苹果」「小米」等有水果/粮食歧义，但下游 understand_request
        # 仍会做 LLM 语义判别，误命中至多让正常闲聊多走一次 LLM，不绑错 ticker。
        "苹果",
        "谷歌",
        "微软",
        "特斯拉",
        "英伟达",
        "奈飞",
        "台积电",
        # Top China ADR / HK
        "阿里巴巴",
        "阿里",
        "腾讯",
        "京东",
        "拼多多",
        "网易",
        "美团",
        "百度",
        "小米",
        "蔚来",
        "理想汽车",
        "小鹏汽车",
        # US indices (Chinese names)
        "纳指",
        "标普",
        "标普500",
        "道指",
        "道琼斯",
        "罗素",
        # A-share / HK indices
        "上证",
        "深证",
        "恒指",
        "恒生",
        # Sectors / themes
        "科技股",
        "白马股",
        "蓝筹股",
        "中概股",
        "半导体板块",
        "新能源板块",
        "医药板块",
        # Macro indicators (high-frequency abbreviations)
        "cpi",
        "ppi",
        "pmi",
        "gdp",
        "非农",
        "就业数据",
        "通胀",
        "通缩",
        "滞胀",
        "衰退",
        "qe",
        "缩表",
        # Trading operations
        "建仓",
        "清仓",
        "补仓",
        "加仓",
        "减仓",
        "套牢",
        "割肉",
        "追高",
        "踏空",
        # English
        "ipo",
        "eps",
        "roe",
        "roa",
        "p/e",
        "p/b",
        "ebitda",
        "nasdaq",
        "nyse",
        "s&p",
        "10-k",
        "10-q",
        "sec filing",
        "dividend",
        "portfolio",
        "hedge fund",
    }
)

_FINANCIAL_PATTERN_HP = re.compile(
    r"("
    # English unambiguous terms
    r"stock\s*price|share\s*price|bull\s*market|bear\s*market"
    r"|earnings\s*report|revenue\s*growth|profit\s*margin"
    r"|dividend|portfolio|hedge\s*fund"
    # Standalone uppercase ticker-like token (2~5 chars)
    r"|(?:^|\s)(?-i:[A-Z]{2,5})(?:\s|$)"
    # Chinese structure patterns
    r"|(?:分析|研究|看看|查看|查一下|帮我看).*(?:股票|股价|行情|财报|基本面|k线|走势)"
    r"|(?:股票|股价|行情|财报|基本面|k线|走势).*(?:分析|怎么看|如何看)"
    r"|目标价|评级|研报"
    r"|值得.*(?:买入?|投资|关注)|能不能买|该不该买"
    r")",
    re.IGNORECASE,
)


def has_financial_intent(query: str) -> bool:
    """High-precision financial intent detection."""
    if not query:
        return False

    cleaned = query.strip()
    if not cleaned:
        return False

    lower = cleaned.lower()
    if any(token in lower for token in _FINANCIAL_TOKENS_HP):
        return True

    return bool(_FINANCIAL_PATTERN_HP.search(cleaned))


__all__ = ["is_greeting", "is_casual_chat", "has_financial_intent"]

