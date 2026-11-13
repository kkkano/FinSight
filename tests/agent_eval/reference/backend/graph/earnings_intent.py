# -*- coding: utf-8 -*-
"""规则化识别“财报/业绩表现”类问题。

这里识别稳定语义结构：财务报告对象 + 结果/表现问法。它不是公司名或
新闻关键词表，目的是把财报表现请求路由到基本面证据链，而不是价格链。
"""
from __future__ import annotations

import re


_REPORT_OBJECT_RE = re.compile(
    r"("
    r"财报|业绩|季报|年报|季度|营收|收入|利润|毛利|净利|指引|"
    r"\bearnings\b|\bearnings\s+report\b|\bquarterly\s+(?:results?|earnings|report)\b|"
    r"\bresults?\b|\brevenue\b|\bprofit\b|\bmargin\b|\beps\b|\bguidance\b"
    r")",
    re.IGNORECASE,
)

_RESULT_QUESTION_RE = re.compile(
    r"("
    r"表现|怎么样|怎麼樣|如何|怎么看|怎麼看|解读|解讀|分析|复盘|復盤|"
    r"超预期|不及预期|好于预期|低于预期|增长|下滑|"
    r"\bperformance\b|\bbeat\b|\bmiss\b|\bhow\s+(?:did|was|were)\b|"
    r"\bwhat\s+(?:were|are)\s+the\s+results\b"
    r")",
    re.IGNORECASE,
)

_REPORT_RESULT_NOUN_PHRASE_RE = re.compile(
    r"("
    r"最新.{0,4}(?:财报|业绩|季报)|"
    r"\blatest\s+(?:quarterly\s+)?(?:earnings|results?|earnings\s+report)\b"
    r")",
    re.IGNORECASE,
)

_CALENDAR_ONLY_RE = re.compile(
    r"(发布日期|什么时候发布|何时发布|哪天发布|财报日期|\bcalendar\b|\bearnings\s+date\b|\brelease\s+date\b)",
    re.IGNORECASE,
)

_PRICE_TARGET_RE = re.compile(
    r"("
    r"股价|走势|价格|盘后|盘前|市场反应|利好|利空|"
    r"\bstock\s+price\b|\bshare\s+price\b|\bshares?\b|\bprice\b|\bmarket\s+reaction\b|"
    r"\bpre[-\s]?market\b|\bafter[-\s]?hours\b"
    r")",
    re.IGNORECASE,
)

_IMPACT_RELATION_RE = re.compile(
    r"("
    r"影响|冲击|反应|带动|拖累|利好|利空|催化|"
    r"\bimpact\b|\baffect(?:ed|s)?\b|\breaction\b|\bmove(?:d|s)?\b|\bdrive(?:s|n)?\b"
    r")",
    re.IGNORECASE,
)


def query_requests_earnings_performance(query: str) -> bool:
    """Return whether the query asks how reported/expected earnings performed."""
    text = str(query or "").strip()
    if not text:
        return False

    compact = re.sub(r"\s+", " ", text)
    has_report_object = bool(_REPORT_OBJECT_RE.search(compact))
    if not has_report_object:
        return False

    has_result_question = bool(_RESULT_QUESTION_RE.search(compact))
    if _CALENDAR_ONLY_RE.search(compact) and not has_result_question:
        return False

    return has_result_question or bool(_REPORT_RESULT_NOUN_PHRASE_RE.search(compact))


def query_requests_earnings_price_impact(query: str) -> bool:
    """Return whether the query asks how an earnings event affects price."""
    text = str(query or "").strip()
    if not text:
        return False

    compact = re.sub(r"\s+", " ", text)
    if _CALENDAR_ONLY_RE.search(compact):
        return False
    return bool(
        _REPORT_OBJECT_RE.search(compact)
        and _PRICE_TARGET_RE.search(compact)
        and _IMPACT_RELATION_RE.search(compact)
    )


__all__ = ["query_requests_earnings_performance", "query_requests_earnings_price_impact"]
