# -*- coding: utf-8 -*-
"""Tests for Dashboard Insights Engine — Scorers, Orchestrator, Prompts."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.dashboard.cache import DashboardCache
from backend.dashboard.insights_engine import (
    DashboardScorer,
    DigestAgent,
    FinancialScorer,
    FinancialDigest,
    InsightsOrchestrator,
    NewsScorer,
    NewsDigest,
    OverviewScorer,
    OverviewDigest,
    PeersScorer,
    PeersDigest,
    TechnicalScorer,
    TechnicalDigest,
    _compute_cache_age,
    _deserialize_insights,
    _ensure_str_list,
    _label_from_score,
    get_insights_orchestrator,
)
from backend.dashboard.insights_prompts import (
    build_financial_prompt,
    build_news_prompt,
    build_overview_prompt,
    build_peers_prompt,
    build_technical_prompt,
)
from backend.dashboard.insights_scorer import (
    clamp_score,
    score_financial,
    score_news,
    score_overview,
    score_peers,
    score_technical,
)
from backend.dashboard.schemas import DashboardInsightsResponse, InsightCard


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    """Tests for module-level helper functions."""

    def test_label_from_score_strong(self):
        assert _label_from_score(9.0) == "强势"

    def test_label_from_score_bullish(self):
        assert _label_from_score(7.0) == "偏多"

    def test_label_from_score_neutral(self):
        assert _label_from_score(5.0) == "中性"

    def test_label_from_score_bearish(self):
        assert _label_from_score(3.5) == "偏空"

    def test_label_from_score_weak(self):
        assert _label_from_score(2.0) == "弱势"

    def test_ensure_str_list_normal(self):
        assert _ensure_str_list(["a", "b"]) == ["a", "b"]

    def test_ensure_str_list_non_list(self):
        assert _ensure_str_list("not a list") == []

    def test_ensure_str_list_mixed(self):
        assert _ensure_str_list([1, None, "ok", "", 3.5]) == ["1", "ok", "3.5"]

    def test_compute_cache_age_valid(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        age = _compute_cache_age(now_iso)
        assert 0 <= age < 2  # within 2 seconds

    def test_compute_cache_age_empty(self):
        assert _compute_cache_age("") == 0

    def test_compute_cache_age_invalid(self):
        assert _compute_cache_age("not-a-date") == 0

    def test_deserialize_insights_valid(self):
        card_data = {
            "agent_name": "test",
            "tab": "overview",
            "score": 7.0,
            "score_label": "偏多",
            "summary": "test summary",
            "key_points": ["point1"],
            "risks": ["risk1"],
            "confidence": 0.8,
            "as_of": "2025-01-01T00:00:00+00:00",
            "model_generated": True,
        }
        result = _deserialize_insights({"overview": card_data})
        assert "overview" in result
        assert isinstance(result["overview"], InsightCard)
        assert result["overview"].score == 7.0

    def test_deserialize_insights_invalid_skips(self):
        result = _deserialize_insights({"bad": {"score": "not-a-number"}})
        assert "bad" not in result

    def test_deserialize_insights_non_dict(self):
        result = _deserialize_insights({"x": "not a dict"})
        assert len(result) == 0


class TestNamingCompatibility:
    """Phase 1 compatibility checks for Agent→Scorer semantic refactor."""

    def test_base_alias_points_to_same_class(self):
        assert DashboardScorer is DigestAgent

    def test_concrete_aliases_point_to_same_class(self):
        assert TechnicalScorer is TechnicalDigest
        assert FinancialScorer is FinancialDigest
        assert NewsScorer is NewsDigest
        assert PeersScorer is PeersDigest
        assert OverviewScorer is OverviewDigest

    def test_legacy_identifiers_remain_stable(self):
        assert TechnicalScorer.AGENT_NAME == "technical_digest"
        assert FinancialScorer.AGENT_NAME == "financial_digest"
        assert NewsScorer.AGENT_NAME == "news_digest"
        assert PeersScorer.AGENT_NAME == "peers_digest"
        assert OverviewScorer.AGENT_NAME == "overview_digest"


# ---------------------------------------------------------------------------
# insights_scorer
# ---------------------------------------------------------------------------

class TestClampScore:
    """Tests for clamp_score utility."""

    def test_clamp_within_range(self):
        assert clamp_score(5.0) == 5.0

    def test_clamp_below_min(self):
        assert clamp_score(-2.0) == 1.0

    def test_clamp_above_max(self):
        assert clamp_score(15.0) == 10.0

    def test_clamp_rounds_to_one_decimal(self):
        assert clamp_score(5.555) == 5.6

    def test_clamp_boundary_min(self):
        assert clamp_score(1.0) == 1.0

    def test_clamp_boundary_max(self):
        assert clamp_score(10.0) == 10.0


class TestScoreTechnical:
    """Tests for deterministic technical scoring."""

    def test_empty_data_returns_neutral(self):
        score, label, points = score_technical({})
        assert 4.0 <= score <= 6.0
        assert isinstance(points, list)

    def test_bullish_signals(self):
        data = {
            "rsi": 55.0,
            "trend": "bullish",
            "ma20": 200.0,
            "ma50": 180.0,
            "macd": 2.0,
            "macd_signal": 1.0,
        }
        score, label, points = score_technical(data)
        assert score >= 7.0
        assert len(points) >= 3

    def test_bearish_signals(self):
        data = {
            "rsi": 75.0,
            "trend": "bearish",
            "ma20": 150.0,
            "ma50": 180.0,
        }
        score, label, points = score_technical(data)
        assert score <= 5.0

    def test_rsi_oversold(self):
        data = {"rsi": 25.0}
        score, label, points = score_technical(data)
        assert any("超卖" in p for p in points)

    def test_rsi_overbought(self):
        data = {"rsi": 80.0}
        score, label, points = score_technical(data)
        assert any("超买" in p for p in points)


class TestScoreFinancial:
    """Tests for deterministic financial scoring."""

    def test_empty_data_returns_base(self):
        score, label, points = score_financial({})
        assert score == 4.0

    def test_healthy_company(self):
        data = {
            "trailing_pe": 20.0,
            "revenue_growth": 0.15,
            "net_income": 1_000_000,
            "debt_to_equity": 0.3,
            "free_cash_flow": 500_000,
        }
        score, label, points = score_financial(data)
        assert score >= 8.0
        assert len(points) >= 4

    def test_distressed_company(self):
        data = {
            "trailing_pe": 50.0,
            "net_income": -100_000,
            "revenue_growth": -0.2,
            "debt_to_equity": 2.0,
        }
        score, label, points = score_financial(data)
        assert score <= 4.0

    def test_nested_valuation_pe(self):
        """PE can be nested under 'valuation' key."""
        data = {"valuation": {"trailing_pe": 15.0}}
        score, label, points = score_financial(data)
        assert any("市盈率" in p for p in points)


class TestScoreNews:
    """Tests for deterministic news scoring."""

    def test_no_news(self):
        score, label, points = score_news({})
        assert score == 5.0
        assert "暂无近期新闻数据" in points[0]

    def test_positive_news(self):
        data = {
            "market": [
                {"title": "Stock surges on record earnings", "summary": "beat expectations"},
                {"title": "Analyst upgrade to buy", "summary": "bullish outlook"},
                {"title": "Company breakthrough", "summary": "positive"},
            ],
            "impact": [],
        }
        score, label, points = score_news(data)
        assert score >= 6.0

    def test_negative_news(self):
        data = {
            "market": [
                {"title": "Stock drops on downgrade", "summary": "risk of sell-off"},
                {"title": "Bearish outlook", "summary": "risk factors increase"},
            ],
            "impact": [],
        }
        score, label, points = score_news(data)
        assert score <= 5.0

    def test_mixed_news(self):
        data = {
            "market": [
                {"title": "surge", "summary": "positive"},
                {"title": "drop risk", "summary": "bearish"},
            ],
        }
        score, label, points = score_news(data)
        assert 3.0 <= score <= 7.0


class TestScorePeers:
    """Tests for deterministic peer scoring."""

    def test_no_peers(self):
        score, label, points = score_peers({})
        assert score == 5.0
        assert "暂无同行对比数据" in points[0]

    def test_outperforming_peers(self):
        data = {
            "company": {"trailing_pe": 12.0, "revenue_growth": 0.25, "profit_margin": 0.2},
            "peers": [
                {"trailing_pe": 20.0, "revenue_growth": 0.1, "profit_margin": 0.1},
                {"trailing_pe": 25.0, "revenue_growth": 0.08, "profit_margin": 0.12},
            ],
        }
        score, label, points = score_peers(data)
        assert score >= 7.0

    def test_underperforming_peers(self):
        data = {
            "company": {"trailing_pe": 40.0, "revenue_growth": -0.05},
            "peers": [
                {"trailing_pe": 15.0, "revenue_growth": 0.15},
                {"trailing_pe": 18.0, "revenue_growth": 0.12},
            ],
        }
        score, label, points = score_peers(data)
        assert score <= 5.0


class TestScoreOverview:
    """Tests for composite overview scoring."""

    def test_neutral_scores(self):
        score, label, points = score_overview(
            tech_score=5.0, fin_score=5.0, news_score=5.0, peers_score=5.0
        )
        assert score == 5.0
        assert any("中性" in p for p in points)

    def test_bullish_scores(self):
        score, label, points = score_overview(
            tech_score=9.0, fin_score=9.0, news_score=8.0, peers_score=8.0
        )
        assert score >= 8.0
        assert any("偏多" in p for p in points)

    def test_weighted_average(self):
        """financial 35%, technical 25%, news 20%, peers 20%."""
        score, _, _ = score_overview(
            tech_score=10.0, fin_score=10.0, news_score=10.0, peers_score=10.0
        )
        assert score == 10.0


# ---------------------------------------------------------------------------
# insights_prompts
# ---------------------------------------------------------------------------

class TestPrompts:
    """Tests for prompt template builders."""

    def test_build_technical_prompt(self):
        prompt = build_technical_prompt("AAPL", {"rsi": 55.0, "trend": "bullish"})
        assert "AAPL" in prompt
        assert "技术分析" in prompt
        assert "JSON" in prompt

    def test_build_financial_prompt(self):
        prompt = build_financial_prompt("AAPL", {"trailing_pe": 28.5})
        assert "AAPL" in prompt
        assert "财务" in prompt

    def test_build_news_prompt(self):
        prompt = build_news_prompt("TSLA", {"market": [{"title": "test"}]})
        assert "TSLA" in prompt
        assert "新闻" in prompt

    def test_build_peers_prompt(self):
        prompt = build_peers_prompt("MSFT", {"peers": [{"symbol": "GOOG"}]})
        assert "MSFT" in prompt
        assert "同行" in prompt

    def test_build_overview_prompt_with_sub_scores(self):
        prompt = build_overview_prompt(
            "NVDA",
            {"valuation": {"trailing_pe": 50}},
            sub_scores={"technical": 7.0, "financial": 6.5, "news": 5.0, "peers": 6.0},
        )
        assert "NVDA" in prompt
        assert "7.0" in prompt
        assert "6.5" in prompt

    def test_build_overview_prompt_without_sub_scores(self):
        prompt = build_overview_prompt("AAPL", {}, sub_scores=None)
        assert "AAPL" in prompt
        assert "dimension_scores" not in prompt

    def test_truncate_data_in_prompt(self):
        """Large data should be truncated."""
        large_data = {"key": "x" * 5000}
        prompt = build_technical_prompt("TEST", large_data)
        assert "truncated" in prompt


# ---------------------------------------------------------------------------
# DigestAgent (base class)
# ---------------------------------------------------------------------------

class TestDigestAgent:
    """Tests for DigestAgent base class via TechnicalDigest."""

    @pytest.mark.asyncio
    async def test_digest_llm_unavailable_uses_fallback(self):
        """When LLM is None, should use deterministic fallback."""
        agent = TechnicalDigest()
        data = {"rsi": 55.0, "trend": "bullish"}

        with patch("backend.dashboard.scorers._get_llm", return_value=None):
            card = await agent.digest("AAPL", data)

        assert isinstance(card, InsightCard)
        assert card.agent_name == "technical_digest"
        assert card.tab == "technical"
        assert card.model_generated is False
        assert card.confidence == 0.4
        assert 1.0 <= card.score <= 10.0
        assert len(card.score_breakdown) >= 3

    @pytest.mark.asyncio
    async def test_digest_llm_success(self):
        """When LLM returns valid JSON, should parse correctly."""
        agent = TechnicalDigest()
        data = {"rsi": 55.0}

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "score": 7.5,
            "score_label": "偏多",
            "summary": "RSI 55 处于正常区间，技术面整体偏多。",
            "key_points": ["RSI 正常", "均线多头"],
            "risks": ["上方阻力"],
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("backend.dashboard.scorers._get_llm", return_value=mock_llm):
            card = await agent.digest("AAPL", data)

        assert isinstance(card, InsightCard)
        assert card.model_generated is True
        assert card.confidence == 0.8
        assert card.score_label == "偏多"
        assert len(card.key_points) == 2
        assert len(card.risks) == 1
        assert len(card.score_breakdown) >= 3

    @pytest.mark.asyncio
    async def test_digest_llm_timeout_falls_back(self):
        """When LLM times out, should use deterministic fallback."""
        agent = TechnicalDigest()
        data = {"rsi": 55.0}

        mock_llm = AsyncMock()

        async def slow_invoke(_prompt):
            await asyncio.sleep(100)

        mock_llm.ainvoke = slow_invoke

        with patch("backend.dashboard.scorers._get_llm", return_value=mock_llm):
            with patch("backend.dashboard.scorers._DIGEST_TIMEOUT_SECONDS", 0.01):
                card = await agent.digest("AAPL", data)

        assert card.model_generated is False

    @pytest.mark.asyncio
    async def test_digest_llm_returns_invalid_json(self):
        """When LLM returns invalid JSON, should fall back to deterministic."""
        agent = FinancialDigest()
        data = {"trailing_pe": 20.0}

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "This is not JSON at all"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("backend.dashboard.scorers._get_llm", return_value=mock_llm):
            card = await agent.digest("AAPL", data)

        assert card.model_generated is False

    @pytest.mark.asyncio
    async def test_digest_llm_returns_markdown_fenced_json(self):
        """LLM sometimes returns JSON wrapped in markdown fences."""
        agent = NewsDigest()
        data = {"market": [{"title": "Good news"}], "impact": []}

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '```json\n{"score": 6.0, "score_label": "中性", "summary": "新闻中性。", "key_points": ["test"], "risks": ["none"]}\n```'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("backend.dashboard.scorers._get_llm", return_value=mock_llm):
            card = await agent.digest("AAPL", data)

        assert card.model_generated is True
        assert card.score == 6.0

    @pytest.mark.asyncio
    async def test_digest_score_divergence_averaging(self):
        """When LLM score diverges >3 from deterministic, they should be averaged."""
        agent = TechnicalDigest()
        data = {}  # neutral base → score ~5.0

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "score": 10.0,  # diverges >3 from base ~5.0
            "score_label": "强势",
            "summary": "Extremely bullish",
            "key_points": ["point"],
            "risks": [],
        })
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch("backend.dashboard.scorers._get_llm", return_value=mock_llm):
            card = await agent.digest("AAPL", data)

        # Should be averaged: (10 + 5) / 2 = 7.5
        assert card.score < 10.0
        assert card.model_generated is True


# ---------------------------------------------------------------------------
# OverviewDigest
# ---------------------------------------------------------------------------

class TestOverviewDigest:
    """Tests for OverviewDigest specific behavior."""

    @pytest.mark.asyncio
    async def test_overview_includes_sub_scores(self):
        """Overview card should include sub_scores from dimensions."""
        agent = OverviewDigest()
        agent.set_sub_scores({
            "technical": 7.0,
            "financial": 6.5,
            "news": 5.0,
            "peers": 6.0,
        })

        with patch("backend.dashboard.scorers._get_llm", return_value=None):
            card = await agent.digest("AAPL", {})

        assert card.sub_scores is not None
        assert card.sub_scores["technical"] == 7.0
        assert card.sub_scores["financial"] == 6.5

    @pytest.mark.asyncio
    async def test_overview_deterministic_score(self):
        """Overview deterministic fallback uses weighted average."""
        agent = OverviewDigest()
        agent.set_sub_scores({
            "technical": 8.0,
            "financial": 8.0,
            "news": 8.0,
            "peers": 8.0,
        })

        with patch("backend.dashboard.scorers._get_llm", return_value=None):
            card = await agent.digest("AAPL", {})

        assert card.score == 8.0


# ---------------------------------------------------------------------------
# InsightsOrchestrator
# ---------------------------------------------------------------------------

class TestInsightsOrchestrator:
    """Tests for InsightsOrchestrator caching and parallel execution."""

    @pytest.mark.asyncio
    async def test_generate_with_insights_disabled(self):
        """When INSIGHTS_ENABLED is false, returns empty insights."""
        cache = DashboardCache()
        orchestrator = InsightsOrchestrator(cache=cache)

        with patch("backend.dashboard.insights_engine._INSIGHTS_ENABLED", False):
            response = await orchestrator.generate("AAPL")

        assert isinstance(response, DashboardInsightsResponse)
        assert response.insights == {}
        assert response.cached is False

    @pytest.mark.asyncio
    async def test_generate_fresh_all_fallback(self):
        """Generate with no LLM produces all fallback cards."""
        cache = DashboardCache()
        # Pre-populate dashboard data cache so orchestrator can read it
        cache.set("AAPL", "technicals", {"rsi": 55.0, "trend": "bullish"})
        cache.set("AAPL", "financials", {"trailing_pe": 20.0})
        cache.set("AAPL", "valuation", {"trailing_pe": 20.0})
        cache.set("AAPL", "news", {"market": [{"title": "test"}], "impact": []})
        cache.set("AAPL", "peers", {"company": {}, "peers": []})
        cache.set("AAPL", "snapshot", {"price": 180.0})

        orchestrator = InsightsOrchestrator(cache=cache)

        with patch("backend.dashboard.scorers._get_llm", return_value=None):
            response = await orchestrator.generate("AAPL", force=True)

        assert response.symbol == "AAPL"
        assert response.cached is False
        assert "overview" in response.insights
        assert "financial" in response.insights
        assert "technical" in response.insights
        assert "news" in response.insights
        assert "peers" in response.insights

        for tab_name, card in response.insights.items():
            assert isinstance(card, InsightCard)
            assert card.model_generated is False
            assert 1.0 <= card.score <= 10.0

    @pytest.mark.asyncio
    async def test_generate_uses_cache(self):
        """Second call should return cached result."""
        cache = DashboardCache()
        cache.set("AAPL", "technicals", {"rsi": 55.0})
        cache.set("AAPL", "financials", {})
        cache.set("AAPL", "valuation", {})
        cache.set("AAPL", "news", {"market": [], "impact": []})
        cache.set("AAPL", "peers", {})
        cache.set("AAPL", "snapshot", {})

        orchestrator = InsightsOrchestrator(cache=cache)

        with patch("backend.dashboard.scorers._get_llm", return_value=None):
            first = await orchestrator.generate("AAPL", force=True)
            second = await orchestrator.generate("AAPL")

        assert first.cached is False
        assert second.cached is True
        assert second.cache_age_seconds >= 0

    @pytest.mark.asyncio
    async def test_generate_force_bypasses_cache(self):
        """force=True should bypass cache and regenerate."""
        cache = DashboardCache()
        cache.set("AAPL", "technicals", {})
        cache.set("AAPL", "financials", {})
        cache.set("AAPL", "valuation", {})
        cache.set("AAPL", "news", {"market": [], "impact": []})
        cache.set("AAPL", "peers", {})
        cache.set("AAPL", "snapshot", {})

        orchestrator = InsightsOrchestrator(cache=cache)

        with patch("backend.dashboard.scorers._get_llm", return_value=None):
            first = await orchestrator.generate("AAPL", force=True)
            second = await orchestrator.generate("AAPL", force=True)

        assert first.cached is False
        assert second.cached is False

    @pytest.mark.asyncio
    async def test_generate_overview_has_sub_scores(self):
        """Overview card should contain sub_scores from dimensions."""
        cache = DashboardCache()
        cache.set("AAPL", "technicals", {"rsi": 55.0, "trend": "bullish"})
        cache.set("AAPL", "financials", {"trailing_pe": 20.0})
        cache.set("AAPL", "valuation", {"trailing_pe": 20.0})
        cache.set("AAPL", "news", {"market": [], "impact": []})
        cache.set("AAPL", "peers", {"company": {}, "peers": []})
        cache.set("AAPL", "snapshot", {})

        orchestrator = InsightsOrchestrator(cache=cache)

        with patch("backend.dashboard.scorers._get_llm", return_value=None):
            response = await orchestrator.generate("AAPL", force=True)

        overview = response.insights["overview"]
        assert overview.sub_scores is not None
        assert "technical" in overview.sub_scores
        assert "financial" in overview.sub_scores
        assert "news" in overview.sub_scores
        assert "peers" in overview.sub_scores


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    """Tests for module-level singleton."""

    def test_get_insights_orchestrator_returns_same_instance(self):
        o1 = get_insights_orchestrator()
        o2 = get_insights_orchestrator()
        assert o1 is o2
        assert isinstance(o1, InsightsOrchestrator)


# ---------------------------------------------------------------------------
# InsightCard Schema
# ---------------------------------------------------------------------------

class TestInsightCardSchema:
    """Tests for InsightCard Pydantic model."""

    def test_valid_card(self):
        card = InsightCard(
            agent_name="test",
            tab="technical",
            score=7.5,
            score_label="偏多",
            summary="Test summary",
            key_points=["point1", "point2"],
            risks=["risk1"],
            confidence=0.8,
            as_of="2025-01-01T00:00:00+00:00",
            model_generated=True,
        )
        assert card.score == 7.5
        assert card.model_generated is True

    def test_score_clamped_by_schema(self):
        """Score must be between 0 and 10."""
        with pytest.raises(Exception):
            InsightCard(
                agent_name="test",
                tab="test",
                score=15.0,
                score_label="invalid",
            )

    def test_card_with_sub_scores(self):
        card = InsightCard(
            agent_name="overview_digest",
            tab="overview",
            score=6.0,
            score_label="中性",
            sub_scores={"technical": 7.0, "financial": 5.0},
        )
        assert card.sub_scores["technical"] == 7.0

    def test_card_serialization(self):
        card = InsightCard(
            agent_name="test",
            tab="test",
            score=5.0,
            score_label="中性",
        )
        data = card.model_dump()
        assert data["agent_name"] == "test"
        assert data["score"] == 5.0
        restored = InsightCard(**data)
        assert restored.score == card.score
