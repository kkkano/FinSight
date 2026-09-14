# -*- coding: utf-8 -*-
"""客观信号提取（WP2 Task 2 / D2a）——无路由决策，只回答"query 里有什么"。

与 keywords.py 一样是意图层的地基：T3 的意图管线（LLM 主导 + 规则兜底）
统一从这里取信号，不再各自散装 grep。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.config.ticker_mapping import dedup_tickers, extract_tickers
from backend.graph.intent.keywords import (
    _MACRO_HINTS,
    _NON_ASSET_TOKENS,
    _PORTFOLIO_HINTS,
    _THEME_HINTS,
    _URL_RE,
)
from backend.graph.nodes.query_intent import has_financial_intent, is_casual_chat


def contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(h in lowered for h in hints if h)


@dataclass
class QuerySignals:
    tickers: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    has_macro: bool = False
    has_portfolio: bool = False
    has_theme: bool = False
    has_financial_intent: bool = False
    is_casual: bool = False


def extract_signals(query: str, *, ui_context: dict | None = None) -> QuerySignals:
    """从 query 提取客观信号。ticker 提取先剥 URL（与 understand_request 现状一致）。"""
    text = str(query or "").strip()
    if not text:
        return QuerySignals()

    urls = [m.group(0) for m in _URL_RE.finditer(text)]
    text_wo_urls = _URL_RE.sub(" ", text)
    ticker_meta = extract_tickers(text_wo_urls)
    tickers = dedup_tickers(
        [str(t) for t in (ticker_meta.get("tickers") or []) if str(t).strip().upper() not in _NON_ASSET_TOKENS]
    )

    return QuerySignals(
        tickers=tickers,
        urls=urls,
        has_macro=contains_any(text, _MACRO_HINTS),
        has_portfolio=contains_any(text, _PORTFOLIO_HINTS),
        has_theme=contains_any(text, _THEME_HINTS),
        has_financial_intent=bool(has_financial_intent(text)),
        is_casual=bool(is_casual_chat(text)),
    )


__all__ = ["QuerySignals", "contains_any", "extract_signals"]
