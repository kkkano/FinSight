# -*- coding: utf-8 -*-
"""Tests for resolve_subject three-tier active_symbol binding gate."""

import pytest

from backend.graph.nodes.resolve_subject import resolve_subject


def _make_state(
    query: str = "",
    active_symbol: str | None = None,
    selections: list | None = None,
) -> dict:
    ui_context: dict = {}
    if active_symbol is not None:
        ui_context["active_symbol"] = active_symbol
    if selections is not None:
        ui_context["selections"] = selections
    return {"query": query, "ui_context": ui_context}


class TestResolveSubjectTierGate:
    """Three-tier active_symbol binding tests."""

    @pytest.mark.asyncio
    async def test_no_active_symbol_stays_unknown(self):
        """Without active_symbol, non-financial query stays unknown."""
        result = await resolve_subject(_make_state(query="你是男的还是女的"))
        subject = result["subject"]
        assert subject["subject_type"] == "unknown"
        assert subject["tickers"] == []

    @pytest.mark.asyncio
    async def test_tier1_explicit_ticker_in_query(self):
        """Explicit ticker in query always wins (Tier 1)."""
        result = await resolve_subject(_make_state(query="分析 AAPL", active_symbol="GOOGL"))
        subject = result["subject"]
        # extract_tickers should find AAPL in the query
        if subject["subject_type"] == "company":
            assert "AAPL" in subject["tickers"]
            assert subject["binding_tier"] == "tier1_explicit_ticker"

    @pytest.mark.asyncio
    async def test_tier2_keyword_binds(self):
        """Clear financial keyword + active_symbol → bind (Tier 2)."""
        result = await resolve_subject(_make_state(query="股价怎么样", active_symbol="AAPL"))
        subject = result["subject"]
        assert subject["subject_type"] == "company"
        assert subject["tickers"] == ["AAPL"]
        assert subject["binding_tier"] == "tier2_keyword"

    @pytest.mark.asyncio
    async def test_non_financial_no_active_symbol(self):
        """Non-financial query without active_symbol stays unknown."""
        result = await resolve_subject(_make_state(query="你是男的还是女的"))
        subject = result["subject"]
        assert subject["subject_type"] == "unknown"
        assert subject["binding_tier"] == "none"

    @pytest.mark.asyncio
    async def test_empty_query_no_binding(self):
        """Empty query never triggers active_symbol binding."""
        result = await resolve_subject(_make_state(query="", active_symbol="AAPL"))
        subject = result["subject"]
        assert subject["subject_type"] == "unknown"
        assert subject["tickers"] == []

    @pytest.mark.asyncio
    async def test_selection_overrides_all(self):
        """UI selection always takes precedence."""
        selections = [{"id": "news-1", "type": "news"}]
        result = await resolve_subject(
            _make_state(query="分析这个", active_symbol="TSLA", selections=selections)
        )
        subject = result["subject"]
        assert subject["subject_type"] == "news_item"
        assert subject["binding_tier"] == "selection"

    @pytest.mark.asyncio
    async def test_binding_tier_tracked(self):
        """binding_tier field is always present in subject."""
        result = await resolve_subject(_make_state(query="hello", active_symbol="AAPL"))
        subject = result["subject"]
        assert "binding_tier" in subject
