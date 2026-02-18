# -*- coding: utf-8 -*-
"""RAG query router — decides when to use RAG vs Live Tools.

Routes queries into one of four priorities:

- **SKIP**: Pure real-time queries (live quotes, current prices) → no RAG
- **SECONDARY**: Fresh-news-first queries → Live Tools primary, RAG supplements
- **PRIMARY**: Historical analysis queries → RAG primary, Live Tools supplement
- **PARALLEL**: Deep research → both RAG and Live Tools in parallel
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class RAGPriority(Enum):
    """RAG retrieval priority relative to live tools."""
    SKIP = "skip"           # Pure real-time, no RAG
    SECONDARY = "secondary"  # Live primary, RAG supplements
    PRIMARY = "primary"      # RAG primary, Live supplements
    PARALLEL = "parallel"    # Both in parallel


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

_REALTIME_PATTERNS = re.compile(
    r"(最新价格|现在多少钱|实时|current\s+price|live\s+quote|real.?time)",
    re.IGNORECASE,
)

_FRESH_NEWS_PATTERNS = re.compile(
    r"(今天新闻|最新消息|刚刚|breaking|latest\s+news|today'?s?\s+news|just\s+announced)",
    re.IGNORECASE,
)

_HISTORICAL_PATTERNS = re.compile(
    r"(去年|上季|Q[1-4]\s*\d{4}|财报|年报|10-K|10-Q|历史|同比|环比|"
    r"last\s+year|previous\s+quarter|historical|year.over.year|quarter.over.quarter|"
    r"earnings\s+report|annual\s+report|compare|comparison|trend)",
    re.IGNORECASE,
)

_DEEP_RESEARCH_OPERATIONS = frozenset({
    "investment_report", "deep_analysis", "research", "comparison",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decide_rag_priority(
    *,
    query: str,
    output_mode: str | None = None,
    operation: str | None = None,
    subject_type: str | None = None,
) -> RAGPriority:
    """Determine RAG retrieval priority based on query characteristics.

    Parameters
    ----------
    query : str
        The user's query text.
    output_mode : str | None
        The requested output mode (e.g. ``investment_report``).
    operation : str | None
        The operation type from routing (e.g. ``quote``, ``news``).
    subject_type : str | None
        The subject type (e.g. ``stock``, ``crypto``).

    Returns
    -------
    RAGPriority
        One of SKIP, SECONDARY, PRIMARY, PARALLEL.
    """
    q = (query or "").strip().lower()
    op = (operation or "").strip().lower()
    mode = (output_mode or "").strip().lower()

    # Deep research always uses both
    if mode in _DEEP_RESEARCH_OPERATIONS:
        return RAGPriority.PARALLEL

    # Pure real-time: skip RAG entirely
    if op == "quote" or _REALTIME_PATTERNS.search(q):
        return RAGPriority.SKIP

    # Fresh news: live first, RAG supplements
    if op == "news" or _FRESH_NEWS_PATTERNS.search(q):
        return RAGPriority.SECONDARY

    # Historical analysis: RAG first
    if _HISTORICAL_PATTERNS.search(q):
        return RAGPriority.PRIMARY

    # Default: parallel (safest — equivalent to current behavior)
    return RAGPriority.PARALLEL


__all__ = [
    "RAGPriority",
    "decide_rag_priority",
]
