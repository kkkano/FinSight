# -*- coding: utf-8 -*-
"""Tests for DashboardData schema — validates news field accepts ranking_meta."""

import pytest

from backend.dashboard.schemas import DashboardData


class TestDashboardDataSchema:
    """Bug 1 fix: DashboardData.news must accept ranking_meta dict."""

    def test_news_with_ranking_meta_accepted(self):
        """fetch_news() returns ranking_meta (a dict, not a list).
        DashboardData.news must accept this mixed structure."""
        news = {
            "market": [{"title": "headline", "url": "http://x"}],
            "impact": [],
            "market_raw": [{"title": "raw"}],
            "impact_raw": [],
            "ranking_meta": {
                "version": "v2",
                "formula": "sum(w*f) - penalty",
                "weights": {"market": {"time_decay": 0.45}},
                "notes": ["test"],
            },
        }
        data = DashboardData(snapshot={}, charts={}, news=news)
        assert data.news["ranking_meta"]["version"] == "v2"
        assert isinstance(data.news["market"], list)

    def test_news_empty_accepted(self):
        """Empty news dict is valid."""
        data = DashboardData(snapshot={}, charts={}, news={})
        assert data.news == {}

    def test_news_simple_lists_accepted(self):
        """Simple list-only news (no ranking_meta) still works."""
        news = {"market": [{"title": "a"}], "impact": []}
        data = DashboardData(snapshot={}, charts={}, news=news)
        assert len(data.news["market"]) == 1

    def test_news_fallback_structure(self):
        """Timeout fallback structure (market/impact only) is valid."""
        news = {"market": [], "impact": []}
        data = DashboardData(snapshot={}, charts={}, news=news)
        assert data.news == {"market": [], "impact": []}

    def test_macro_snapshot_field_accepted(self):
        """DashboardData accepts optional macro_snapshot payload."""
        data = DashboardData(
            snapshot={},
            charts={},
            news={},
            macro_snapshot={
                "fear_greed_index": 62.0,
                "fear_greed_label": "greed",
                "sentiment_text": "CNN Fear & Greed Index: 62 (Greed)",
                "status": "ok",
                "as_of": "2026-02-18T00:00:00+00:00",
            },
        )
        assert data.macro_snapshot is not None
        assert data.macro_snapshot.fear_greed_index == 62.0
