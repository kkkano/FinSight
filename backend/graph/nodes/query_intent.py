# -*- coding: utf-8 -*-
"""
Lightweight, rule-based query intent detection.

Zero LLM — pure token / regex matching.
Used by `chat_respond` node to short-circuit greetings and casual chat
before `resolve_subject` ever touches the query.
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
        # Legacy mojibake compatibility
        "浣犲ソ",
        "鍡?",
        "鍝堝柦",
        "鏃?",
        "鏃╀笂濂?",
        "涓婂崍濂?",
        "涓嬪崍濂?",
        "鏅氫笂濂?",
        "鏅氬ソ",
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
        "ok",
        "行",
        "了解",
        "明白",
        "收到",
        "知道了",
        "再见",
        "拜拜",
        "拜",
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
        "sure",
        "cool",
        "nice",
        "great",
        # Legacy mojibake compatibility
        "璋㈣阿",
        "鎰熻阿",
        "澶氳阿",
        "杈涜嫤浜?",
        "濂界殑",
        "鍡?",
        "鍡棷",
        "鍝?",
        "琛?",
        "浜嗚В",
        "鏄庣櫧",
        "鏀跺埌",
        "鐭ラ亾浜?",
        "鍐嶈",
        "鎷滄嫓",
        "鎷?",
    }
)

_CASUAL_PATTERNS = re.compile(
    r"^("
    r"你是谁|你叫什么|你是做什么的|你能做什么|你会什么|你几岁了|你多大了"
    r"|who\s+are\s+you|what\s+can\s+you\s+do|what\s+are\s+you|how\s+old\s+are\s+you"
    r"|今天天气|天气怎么样|几点了|现在几点"
    r"|测试|test"
    r")[？?!.。\s]*$",
    re.IGNORECASE,
)


def is_greeting(query: str) -> bool:
    """Detect pure greetings (e.g. 你好, hello, hey)."""
    cleaned = (query or "").strip().lower()
    if not cleaned:
        return False
    stripped = re.sub(r"[!?？?。！，,\s]+$", "", cleaned)
    if stripped in _GREETING_TOKENS:
        return True
    return bool(_GREETING_RE.fullmatch(cleaned))


def is_casual_chat(query: str) -> bool:
    """
    Detect casual / non-analytical queries.
    Superset of greeting — also covers thanks, meta questions, etc.
    """
    if is_greeting(query):
        return True
    cleaned = (query or "").strip().lower()
    if not cleaned:
        return True
    stripped = re.sub(r"[!?？?。！，,\s]+$", "", cleaned)
    if stripped in _CASUAL_EXACT:
        return True
    return bool(_CASUAL_PATTERNS.fullmatch(cleaned))


# ==================== Financial intent detection (Tier 2) ====================
#
# Architecture for active_symbol binding decision:
#   Tier 1 — Strong signal: explicit ticker in query / UI selection  (handled
#            by extract_tickers in resolve_subject, not here)
#   Tier 2 — High-precision rules: unambiguous financial vocabulary  (this fn)
#   Tier 3 — Small-model classifier: binary intent (TODO: future)
#   Default — Don't bind active_symbol → let clarify handle it
#
# Design: HIGH PRECISION, not high recall.  Only tokens/patterns that are
# *unambiguously* financial in any context.  Anything ambiguous (e.g. "趋势",
# "分析", "风险", "收益") is deliberately excluded — better to clarify than
# to run a wrong analysis pipeline.

_FINANCIAL_TOKENS_HP: frozenset[str] = frozenset(
    {
        # -- Unambiguous Chinese financial terms --
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
        "K线",
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
        "IPO",
        "ipo",
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
        # -- Unambiguous English financial terms --
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
    }
)

_FINANCIAL_PATTERN_HP = re.compile(
    r"("
    # English unambiguous financial
    r"stock\s*price|share\s*price|bull\s*market|bear\s*market"
    r"|earnings\s*report|revenue\s*growth|profit\s*margin"
    r"|dividend|portfolio|hedge\s*fund"
    # Ticker-like standalone (2-5 UPPERCASE letters only — disable IGNORECASE locally)
    r"|(?:^|\s)(?-i:[A-Z]{2,5})(?:\s|$)"
    # Chinese action + financial object
    r"|(?:分析|研究|看看|查看|查一下|帮我看).*(?:股票|股价|行情|财报|基本面|K线|走势)"
    r"|(?:股票|股价|行情|财报|基本面|K线|走势).*(?:分析|怎么[看样])"
    r"|目标价|评级|研报"
    r"|值得.*(?:买入?|投资|关注)|能不能买|该不该买"
    r")",
    re.IGNORECASE,
)


def has_financial_intent(query: str) -> bool:
    """
    HIGH-PRECISION financial intent detection (Tier 2).

    Returns True ONLY when the query contains unambiguously financial
    vocabulary.  Used by ``resolve_subject`` to decide whether
    ``active_symbol`` fallback is safe.

    Design: Precision > Recall.  False negatives (missing a financial query)
    are acceptable — the query simply goes to ``clarify`` for disambiguation.
    False positives (binding active_symbol to a non-financial query) are NOT
    acceptable — they trigger a wrong analysis pipeline.
    """
    if not query:
        return False
    cleaned = query.strip()
    if not cleaned:
        return False

    # Token match — unambiguous financial keywords only
    lower = cleaned.lower()
    for token in _FINANCIAL_TOKENS_HP:
        if token in lower:
            return True

    # Pattern match — structural patterns that imply financial analysis
    if _FINANCIAL_PATTERN_HP.search(cleaned):
        return True

    return False


__all__ = ["is_greeting", "is_casual_chat", "has_financial_intent"]
