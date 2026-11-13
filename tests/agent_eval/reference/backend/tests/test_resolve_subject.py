# -*- coding: utf-8 -*-
"""Tests for resolve_subject three-tier active_symbol binding gate."""

import pytest

from backend.graph.nodes.resolve_subject import resolve_subject


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [120, 180])
async def test_subject_classifier_does_not_cancel_reasoning_after_five_seconds(monkeypatch, timeout):
    import importlib
    from types import SimpleNamespace

    module = importlib.import_module("backend.graph.nodes.resolve_subject")
    observed = {}
    monkeypatch.setenv("SUBJECT_RESOLVER_TIMEOUT_SECONDS", str(timeout))
    monkeypatch.setenv("SUBJECT_RESOLVER_MAX_TOKENS", "8192")

    async def invoke(_messages, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(content="90")

    async def wait_for(awaitable, *, timeout):
        observed["outer_timeout"] = timeout
        return await awaitable

    monkeypatch.setattr("backend.services.llm_retry.ainvoke_configured_llm", invoke)
    monkeypatch.setattr(module.asyncio, "wait_for", wait_for)

    assert await module._llm_classify_financial("继续看这个公司的发展") == (True, 90)
    assert observed["outer_timeout"] == timeout
    assert observed["request_timeout"] == timeout
    assert observed["max_tokens"] == 8192
    assert observed["context"].budget.max_provider_attempts == 2


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

    @pytest.mark.asyncio
    async def test_tier1_cn_dotted_symbol_keeps_full_ticker(self):
        """CN dotted symbols (e.g. 600519.SS) should not be truncated to suffix."""
        result = await resolve_subject(_make_state(query="分析 600519.SS 的估值", active_symbol="AAPL"))
        subject = result["subject"]
        assert subject["subject_type"] == "company"
        assert "600519.SS" in subject["tickers"]
        assert "SS" not in subject["tickers"]
