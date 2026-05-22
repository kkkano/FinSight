# -*- coding: utf-8 -*-
"""规则化识别投资观点类问题。

这里避免维护一长串固定短语，而是识别几个稳定语义结构：
价格/趋势对象 + 观点问法，或买卖/持仓决策问法。
"""
from __future__ import annotations

import re


_MARKET_OBJECT_RE = re.compile(
    r"(走势|趋势|后市|後市|行情|表现|方向|短线|短期|中线|中期|前景|机会|风险|估值|股价|价格|"
    r"\btrend\b|\boutlook\b|\bupside\b|\bdownside\b|\brisk\b|\bvaluation\b)",
    re.IGNORECASE,
)

_VIEW_QUESTION_RE = re.compile(
    r"(怎么看|怎麼看|如何看|怎么走|怎麼走|怎么操作|怎麼操作|看法|观点|觀點|判断|判斷|结论|結論|"
    r"看好|看坏|看壞|看多|看空|偏多|偏空|"
    r"\bview\b|\btake\b|\bopinion\b|\bthink\b|\bbullish\b|\bbearish\b)",
    re.IGNORECASE,
)

_TRADE_DECISION_RE = re.compile(
    r"("
    r"(值不值得|值得|能不能|可不可以|是否|该不该|該不該|要不要|适不适合|適不適合).{0,8}"
    r"(买|買|卖|賣|持有|加仓|加倉|减仓|減倉|追|抄底|入场|入場|出场|出場)"
    r"|"
    r"(买|買|卖|賣|持有|加仓|加倉|减仓|減倉|追|抄底|入场|入場|出场|出場).{0,8}"
    r"(吗|嗎|么|麼|不|合适|合適|可以|适合|適合)"
    r"|"
    r"\b(should\s+i|worth|buy|sell|hold|add|trim)\b.{0,24}\b(stock|shares?|position|buy|sell|hold|add|trim)\b"
    r")",
    re.IGNORECASE,
)


def query_requests_investment_opinion(query: str) -> bool:
    """Return whether the query asks for a directional investment view."""
    text = str(query or "").strip()
    if not text:
        return False
    compact = re.sub(r"\s+", " ", text)
    has_market_object = bool(
        _MARKET_OBJECT_RE.search(compact)
        or re.search(r"(?<![A-Za-z0-9])[A-Z]{1,6}(?![A-Za-z0-9])", text)
        or re.search(r"\b(stocks?|shares?|position|ticker)\b", compact, re.IGNORECASE)
    )
    if _TRADE_DECISION_RE.search(compact):
        return True
    return bool(has_market_object and _VIEW_QUESTION_RE.search(compact))


__all__ = ["query_requests_investment_opinion"]
