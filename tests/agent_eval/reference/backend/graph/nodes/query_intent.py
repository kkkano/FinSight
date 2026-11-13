# -*- coding: utf-8 -*-
"""Lightweight social-turn and high-precision finance signal detection.

No LLM call here. Social detection is intentionally narrow: only pure
greetings, thanks, acknowledgements, goodbyes, empty input, and smoke-test
tokens are short-circuited locally. Open-ended chat and capability questions
go to the contextual LLM router before the planner.
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
    r"测试|test"
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
    """Detect pure local social turns.

    This is a narrow superset of greeting detection. It must not absorb
    questions like "你能做什么" or "推荐一首歌"; those need the LLM router's
    context and system identity.
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

# ==================== Financial intent hinting ====================
# This is not a classifier. It is only a high-precision hint used after the
# contextual LLM router, mainly to bind an already active symbol when the
# router is disabled or unavailable. Do not grow this into a company/theme
# dictionary; company names belong in ticker_mapping and intent belongs in the
# LLM router.

_FINANCIAL_ACTION_TOKENS_HP: frozenset[str] = frozenset(
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
        # Macro indicators and operations are still safe, action-like signals.
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
    r"|(?<![A-Za-z0-9])(?-i:[A-Z]{2,5})(?![A-Za-z0-9])"
    # Chinese structure patterns
    r"|(?:分析|研究|看看|查看|查一下|帮我看).*(?:股票|股价|行情|财报|基本面|k线|走势)"
    r"|(?:股票|股价|行情|财报|基本面|k线|走势).*(?:分析|怎么看|如何看)"
    r"|目标价|评级|研报"
    r"|值得.*(?:买入?|投资|关注)|能不能买|该不该买"
    r")",
    re.IGNORECASE,
)


def has_financial_intent(query: str) -> bool:
    """Return a narrow financial-action hint.

    Open-ended chat, company-name-only requests, and follow-ups should be
    resolved by the contextual LLM router, not by extending this token list.
    """
    if not query:
        return False

    cleaned = query.strip()
    if not cleaned:
        return False

    lower = cleaned.lower()
    if any(token in lower for token in _FINANCIAL_ACTION_TOKENS_HP):
        return True

    return bool(_FINANCIAL_PATTERN_HP.search(cleaned))


__all__ = ["is_greeting", "is_casual_chat", "has_financial_intent"]
