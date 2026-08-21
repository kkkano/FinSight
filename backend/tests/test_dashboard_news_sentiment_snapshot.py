"""Dashboard 新闻舆情快照测试（确定性聚合，零额外 API 调用）。"""
from __future__ import annotations

from backend.dashboard.news_sentiment import (
    attach_dashboard_news_sentiment,
    build_dashboard_sentiment_snapshot,
)


def _item(title: str, ts: str = "", summary: str = "", impact_score=None) -> dict:
    item = {
        "title": title,
        "url": "https://example.com/news",
        "source": "Reuters",
        "ts": ts,
        "summary": summary,
    }
    if impact_score is not None:
        item["impact_score"] = impact_score
    return item


def test_snapshot_bias_catalysts_heat_and_truthful_price_todo() -> None:
    news = [
        _item("Apple Q2 earnings beat expectations", "2026-08-20T08:00:00Z", "strong revenue growth", 0.9),
        _item("Apple announces new product launch", "2026-08-20T09:00:00Z", "", 0.7),
        _item("Routine commentary", "2026-08-20T10:00:00Z"),
    ]
    snap = build_dashboard_sentiment_snapshot("AAPL", news, [])

    assert snap["ticker"] == "AAPL"
    assert snap["source"] == "dashboard_light_snapshot"
    assert snap["sentiment_bias"]["sample_size"] == 3
    assert snap["sentiment_bias"]["label"] == "bullish"
    assert snap["sentiment_bias"]["basis"] == "keyword_estimation"
    assert snap["heat"]["news_count"] == 3
    assert snap["catalyst_events"]["count"] >= 2
    # 数据真实性防线：未做价格校准，绝不推断共振/背离
    assert snap["price_transmission"]["status"] == "todo"
    assert snap["price_transmission"]["price_change_pct"] is None


def test_sentiment_trend_improving() -> None:
    news = [
        _item("Stock slumps after weak guidance", "2026-08-19T08:00:00Z"),
        _item("Company misses earnings forecast", "2026-08-19T09:00:00Z"),
        _item("Shares surge on record profit", "2026-08-20T08:00:00Z"),
        _item("Strong revenue growth beat", "2026-08-20T09:00:00Z"),
    ]
    snap = build_dashboard_sentiment_snapshot("AAPL", news, [])
    assert snap["sentiment_trend"]["direction"] == "improving"
    assert snap["sentiment_trend"]["delta"] is not None


def test_sentiment_trend_deteriorating() -> None:
    news = [
        _item("Record profit and strong guidance", "2026-08-19T08:00:00Z"),
        _item("Company beats earnings expectations", "2026-08-19T09:00:00Z"),
        _item("Shares slump after downgrade", "2026-08-20T08:00:00Z"),
        _item("Loss warning and weak outlook", "2026-08-20T09:00:00Z"),
    ]
    snap = build_dashboard_sentiment_snapshot("AAPL", news, [])
    assert snap["sentiment_trend"]["direction"] == "deteriorating"
    assert snap["sentiment_trend"]["delta"] is not None


def test_empty_news_snapshot_is_honest() -> None:
    snap = build_dashboard_sentiment_snapshot("TSLA", [], [])
    assert snap["sentiment_bias"]["sample_size"] == 0
    assert snap["sentiment_bias"]["label"] == "neutral"
    assert snap["sentiment_trend"]["direction"] == "unknown"
    assert snap["heat"]["level"] == "thin"
    assert snap["catalyst_events"]["count"] == 0
    assert snap["price_transmission"]["status"] == "todo"


def test_attach_keeps_cached_news_untouched() -> None:
    news = {
        "market": [_item("Apple Q2 earnings beat", "2026-08-20T08:00:00Z")],
        "impact": [_item("Analyst upgrades AAPL", "2026-08-20T09:00:00Z")],
    }
    original = dict(news)
    payload = attach_dashboard_news_sentiment(news, "AAPL")

    assert payload is not news
    assert "sentiment_snapshot" in payload
    assert payload["sentiment_snapshot"]["ticker"] == "AAPL"
    assert "sentiment_snapshot" not in news
    assert news == original


def test_market_and_impact_are_merged_without_duplicates() -> None:
    same = _item("Apple earnings beat", "2026-08-20T08:00:00Z")
    snap = build_dashboard_sentiment_snapshot("AAPL", [same], [same])
    assert snap["heat"]["news_count"] == 1
