# -*- coding: utf-8 -*-
"""
Rule-first operation parsing with multi-ticker default compare strategy.

Priority order (highest to lowest):
  1. Explicit compare keywords  → compare
  2. Guardrail-A single-task keywords (analyze_impact > technical > price >
     summarize > extract_metrics > fetch)  → corresponding op
  3. Multi-ticker default compare (len(tickers) >= 2, no guardrail-A hit)
  4. qa fallback

Design notes:
  - Guardrail A prevents multi-ticker queries with a clear single-task intent
    (e.g. "price of AAPL and TSLA") from being forced into compare.
  - ``vs`` uses explicit non-alphanumeric boundary to handle CJK adjacency
    (e.g. ``苹果vs特斯拉``) reliably.
  - ``trace.operation_decision`` is emitted for every call so that the
    decision can be replayed / audited downstream.
"""
from __future__ import annotations

import re
from typing import Any

from backend.graph.state import GraphState

# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

# Explicit compare intent (highest priority).
_COMPARE_KEYWORDS: tuple[str, ...] = (
    "vs", "versus", "compare", "comparison",
    "对比", "比較", "比较", "相比", "区别", "差异",
    "哪个更", "哪個更",
)

# Guardrail A: single-task keywords that block multi-ticker default compare.
_IMPACT_KEYWORDS: tuple[str, ...] = (
    "影响", "影響", "冲击", "衝擊", "利好", "利空", "怎么影响", "如何影响",
)
_TECHNICAL_KEYWORDS: tuple[str, ...] = (
    "技术面", "技術面", "技术分析", "技術分析", "technical analysis",
    "macd", "rsi", "kdj", "均线", "ma", "k线", "k線", "支撑", "阻力",
)
_ALERT_KEYWORDS: tuple[str, ...] = (
    # CN
    "提醒",
    "提醒我",
    "预警",
    "设置提醒",
    "价格提醒",
    "涨到",
    "跌到",
    "到达",
    "触及",
    "达到",
    # EN (fixed phrases only, no regex tokens here)
    "alert",
    "notify",
    "remind me",
    "price alert",
    "when it reaches",
    "when reaches",
    "target price",
)
_SCREEN_KEYWORDS: tuple[str, ...] = (
    "screen",
    "screener",
    "stock screener",
    "stock screen",
    "筛选",
    "选股",
    "条件选股",
)
_CN_MARKET_KEYWORDS: tuple[str, ...] = (
    "资金流向",
    "北向",
    "northbound",
    "fund flow",
    "limit-up",
    "limit up",
    "龙虎榜",
    "概念股",
    "concept board",
)
_BACKTEST_KEYWORDS: tuple[str, ...] = (
    "backtest",
    "strategy backtest",
    "回测",
    "策略回测",
    "ma cross",
    "macd strategy",
    "rsi mean reversion",
)
_PRICE_KEYWORDS: tuple[str, ...] = (
    "股价", "股價", "现价", "現價", "报价", "報價", "行情",
    "price", "quote", "多少钱", "多少錢", "现在多少钱",
)
_SUMMARIZE_KEYWORDS: tuple[str, ...] = (
    "总结", "總結", "概括", "摘要", "要点", "要點", "tl;dr",
)
_EXTRACT_METRICS_KEYWORDS: tuple[str, ...] = (
    "抽取", "提取", "指标", "指標", "营收", "收入", "利润", "毛利", "eps", "guidance",
)
_FETCH_KEYWORDS: tuple[str, ...] = (
    "获取", "列出", "有哪些", "新闻", "最新", "发生了什么", "發生了什麼",
    "news", "latest news",
)
_MORNING_BRIEF_KEYWORDS: tuple[str, ...] = (
    "晨报", "早报", "晨间", "早间", "每日简报", "今日概览",
    "morning brief", "daily brief", "morning report", "daily summary",
    "今日行情", "盘前", "开盘前",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _match_any(tokens: tuple[str, ...], lowered: str) -> list[str]:
    """Return list of matched keyword hits (empty if none)."""
    hits: list[str] = []
    for t in tokens:
        if len(t) <= 3 and t.isascii():
            # Non-alphanumeric boundary for short ASCII tokens.
            # Handles CJK adjacency like 苹果vs特斯拉 and avoids
            # substring false-positives like "ma" inside "macro".
            pattern = r"(?<![a-zA-Z0-9])" + re.escape(t) + r"(?![a-zA-Z0-9])"
            if re.search(pattern, lowered):
                hits.append(t)
        elif t in lowered:
            hits.append(t)
    return hits


# ---------------------------------------------------------------------------
# Main node
# ---------------------------------------------------------------------------

def parse_operation(state: GraphState) -> dict:
    """
    Rule-first operation parsing.

    Deterministic + testable.  A constrained LLM classifier may be added in
    later phases but must always keep a rules fallback.
    """
    query = (state.get("query") or "").strip()
    subject = state.get("subject") or {}
    subject_type = subject.get("subject_type") or "unknown"
    tickers = subject.get("tickers") or []
    is_comparison_hint = bool(subject.get("is_comparison"))

    lowered = query.lower()

    op = "qa"
    confidence = 0.4
    source = "fallback_qa"
    keyword_hits: list[str] = []
    guardrail_a_hit: str | None = None

    # ------------------------------------------------------------------
    # 1. Explicit compare keywords (highest priority)
    # ------------------------------------------------------------------
    hits = _match_any(_COMPARE_KEYWORDS, lowered)
    if hits:
        op = "compare"
        confidence = 0.85
        source = "keyword"
        keyword_hits = hits

    # ------------------------------------------------------------------
    # 2. Guardrail-A: single-task keywords (block default compare)
    # ------------------------------------------------------------------
    elif (hits := _match_any(_IMPACT_KEYWORDS, lowered)):
        op = "analyze_impact"
        confidence = 0.75
        source = "keyword"
        keyword_hits = hits
        guardrail_a_hit = "analyze_impact"

    elif (hits := _match_any(_BACKTEST_KEYWORDS, lowered)):
        op = "backtest"
        confidence = 0.86
        source = "keyword"
        keyword_hits = hits
        guardrail_a_hit = "backtest"

    elif (hits := _match_any(_ALERT_KEYWORDS, lowered)):
        op = "alert_set"
        confidence = 0.88
        source = "keyword"
        keyword_hits = hits
        guardrail_a_hit = "alert_set"

    elif (hits := _match_any(_SCREEN_KEYWORDS, lowered)):
        op = "screen"
        confidence = 0.86
        source = "keyword"
        keyword_hits = hits
        guardrail_a_hit = "screen"

    elif (hits := _match_any(_CN_MARKET_KEYWORDS, lowered)):
        op = "cn_market"
        confidence = 0.84
        source = "keyword"
        keyword_hits = hits
        guardrail_a_hit = "cn_market"

    elif (hits := _match_any(_TECHNICAL_KEYWORDS, lowered)):
        op = "technical"
        confidence = 0.85
        source = "keyword"
        keyword_hits = hits
        guardrail_a_hit = "technical"

    elif (hits := _match_any(_PRICE_KEYWORDS, lowered)):
        op = "price"
        confidence = 0.8
        source = "keyword"
        keyword_hits = hits
        guardrail_a_hit = "price"

    elif (hits := _match_any(_SUMMARIZE_KEYWORDS, lowered)):
        op = "summarize"
        confidence = 0.75
        source = "keyword"
        keyword_hits = hits
        guardrail_a_hit = "summarize"

    elif subject_type in ("filing", "research_doc") and (
        hits := _match_any(_EXTRACT_METRICS_KEYWORDS, lowered)
    ):
        op = "extract_metrics"
        confidence = 0.7
        source = "keyword"
        keyword_hits = hits
        guardrail_a_hit = "extract_metrics"

    elif (hits := _match_any(_FETCH_KEYWORDS, lowered)):
        op = "fetch"
        confidence = 0.65
        source = "keyword"
        keyword_hits = hits
        guardrail_a_hit = "fetch"

    # ------------------------------------------------------------------
    # 2.5. Morning brief keywords (between fetch and multi-ticker default)
    # ------------------------------------------------------------------
    elif (hits := _match_any(_MORNING_BRIEF_KEYWORDS, lowered)):
        op = "morning_brief"
        confidence = 0.85
        source = "keyword"
        keyword_hits = hits
        guardrail_a_hit = "morning_brief"

    # ------------------------------------------------------------------
    # 3. Multi-ticker default compare (no guardrail-A hit)
    # ------------------------------------------------------------------
    elif len(tickers) >= 2:
        op = "compare"
        confidence = 0.7
        source = "multi_ticker_default"
        keyword_hits = []

    # ------------------------------------------------------------------
    # 4. qa fallback
    # ------------------------------------------------------------------
    else:
        if re.search(r"[?？]$", query) or _match_any(
            ("吗", "嗎", "什么", "什麼", "为何", "為何"), lowered
        ):
            confidence = 0.55

    # ------------------------------------------------------------------
    # Build trace for auditability
    # ------------------------------------------------------------------
    trace: dict[str, Any] = dict(state.get("trace") or {})
    trace["operation_decision"] = {
        "op": op,
        "confidence": confidence,
        "source": source,
        "keyword_hits": keyword_hits,
        "multi_ticker": len(tickers) >= 2,
        "comparison_hint_used": is_comparison_hint,
        "guardrail_a_hit": guardrail_a_hit,
    }

    return {
        "operation": {"name": op, "confidence": confidence, "params": {}},
        "trace": trace,
    }
