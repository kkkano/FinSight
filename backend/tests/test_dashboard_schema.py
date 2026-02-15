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
