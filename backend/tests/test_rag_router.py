# -*- coding: utf-8 -*-
"""Tests for backend.rag.rag_router — query routing logic."""
from __future__ import annotations

from backend.rag.rag_router import RAGPriority, decide_rag_priority


def test_realtime_quote_skips_rag():
    result = decide_rag_priority(query="AAPL 最新价格", operation="quote")
    assert result == RAGPriority.SKIP


def test_realtime_pattern_skips_rag():
    result = decide_rag_priority(query="what is the current price of TSLA?")
    assert result == RAGPriority.SKIP


def test_news_query_secondary():
    result = decide_rag_priority(query="今天新闻 AAPL", operation="news")
    assert result == RAGPriority.SECONDARY


def test_latest_news_secondary():
    result = decide_rag_priority(query="latest news about Microsoft")
    assert result == RAGPriority.SECONDARY


def test_historical_query_primary():
    result = decide_rag_priority(query="分析苹果去年Q3财报表现")
    assert result == RAGPriority.PRIMARY


def test_earnings_report_primary():
    result = decide_rag_priority(query="Apple 10-K annual report analysis")
    assert result == RAGPriority.PRIMARY


def test_yoy_comparison_primary():
    result = decide_rag_priority(query="MSFT revenue year over year trend")
    assert result == RAGPriority.PRIMARY


def test_deep_research_parallel():
    result = decide_rag_priority(
        query="comprehensive analysis of Tesla",
        output_mode="investment_report",
    )
    assert result == RAGPriority.PARALLEL


def test_generic_query_defaults_parallel():
    result = decide_rag_priority(query="tell me about Apple stock")
    assert result == RAGPriority.PARALLEL


def test_empty_query_defaults_parallel():
    result = decide_rag_priority(query="")
    assert result == RAGPriority.PARALLEL


def test_operation_override():
    """Operation 'quote' should override even if query mentions historical."""
    result = decide_rag_priority(query="历史价格", operation="quote")
    assert result == RAGPriority.SKIP
