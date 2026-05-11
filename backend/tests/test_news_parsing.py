#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for news parsing utilities.
"""

from datetime import datetime

from backend import tools


def test_format_search_news_items_detects_recent_items():
    text = (
        "Search Results (Exa):\n"
        "1. Old headline\n"
        "   July 28, 2025 market move\n"
        "   https://example.com/old\n"
        "2. Fresh headline\n"
        "   2 hours ago market move\n"
        "   https://example.com/new\n"
    )
    now = datetime(2026, 1, 9, 12, 0, 0)
    lines, has_recent = tools._format_search_news_items(text, limit=5, max_age_days=7, now=now)
    assert has_recent is True
    assert any("example.com/new" in line for line in lines)


def test_format_search_news_items_handles_unknown_dates():
    text = (
        "Search Results (Exa):\n"
        "1. Headline without date\n"
        "   Some snippet without date\n"
        "   https://example.com/unknown\n"
    )
    now = datetime(2026, 1, 9, 12, 0, 0)
    lines, has_recent = tools._format_search_news_items(text, limit=3, max_age_days=7, now=now)
    assert has_recent is False
    assert any("example.com/unknown" in line for line in lines)


def test_format_search_news_items_parses_date_from_url():
    text = (
        "Search Results (Exa):\n"
        "1. Reuters headline\n"
        "   Some snippet\n"
        "   https://www.reuters.com/world/markets/some-title-2026-01-08/\n"
    )
    now = datetime(2026, 1, 9, 12, 0, 0)
    lines, has_recent = tools._format_search_news_items(text, limit=3, max_age_days=7, now=now)
    assert has_recent is True
    assert any("2026-01-08" in line for line in lines)


def test_build_search_news_items_returns_structured():
    text = (
        "Search Results (Exa):\n"
        "1. Sample headline\n"
        "   Sample snippet\n"
        "   https://example.com/sample\n"
    )
    items = tools._build_search_news_items(text, limit=2, max_age_days=7, now=datetime(2026, 1, 9, 12, 0, 0))
    assert isinstance(items, list)
    assert items
    assert items[0]["headline"] == "Sample headline"


def test_format_news_items_from_structured():
    items = [
        {
            "headline": "Structured headline",
            "source": "Reuters",
            "url": "https://example.com/structured",
            "published_at": "2026-01-09",
        }
    ]
    formatted = tools.format_news_items(items, title="Latest News (AAPL)")
    assert "Latest News (AAPL)" in formatted
    assert "Structured headline" in formatted


def test_get_company_news_extracts_yfinance_nested_article_url(monkeypatch):
    from backend.tools import news as news_mod

    class _Ticker:
        @property
        def news(self):
            return [
                {
                    "content": {
                        "title": "Nvidia nested Yahoo article title",
                        "provider": {"displayName": "Yahoo"},
                        "canonicalUrl": {"url": "https://finance.yahoo.com/news/nested-article.html"},
                        "pubDate": "2026-05-03T12:00:00Z",
                        "summary": "A nested yfinance article summary about NVDA with enough useful words.",
                    }
                }
            ]

    monkeypatch.setattr(news_mod.yf, "Ticker", lambda _ticker: _Ticker())
    monkeypatch.setattr(news_mod, "finnhub_client", None)
    monkeypatch.setattr(news_mod, "search_authoritative_feeds", lambda *args, **kwargs: [])
    monkeypatch.setattr(news_mod, "ALPHA_VANTAGE_API_KEY", "")

    items = news_mod.get_company_news("NVDA", limit=1)

    assert items
    assert items[0]["title"] == "Nvidia nested Yahoo article title"
    assert items[0]["url"] == "https://finance.yahoo.com/news/nested-article.html"


def test_get_company_news_leaves_url_empty_when_source_has_no_article_url(monkeypatch):
    from backend.tools import news as news_mod

    class _Ticker:
        @property
        def news(self):
            return [
                {
                    "content": {
                        "title": "Nvidia Yahoo article without canonical url",
                        "provider": {"displayName": "Yahoo"},
                        "pubDate": "2026-05-03T12:00:00Z",
                        "summary": "A yfinance article summary about NVDA with enough useful words.",
                    }
                }
            ]

    monkeypatch.setattr(news_mod.yf, "Ticker", lambda _ticker: _Ticker())
    monkeypatch.setattr(news_mod, "finnhub_client", None)
    monkeypatch.setattr(news_mod, "search_authoritative_feeds", lambda *args, **kwargs: [])
    monkeypatch.setattr(news_mod, "ALPHA_VANTAGE_API_KEY", "")

    items = news_mod.get_company_news("NVDA", limit=1)

    assert items
    assert items[0]["url"] == ""


def test_get_company_news_filters_yfinance_items_not_related_to_ticker(monkeypatch):
    from backend.tools import news as news_mod

    class _Ticker:
        @property
        def news(self):
            return [
                {
                    "content": {
                        "title": "SLRC faces rate headwinds yet keeps dividend flat",
                        "provider": {"displayName": "Yahoo"},
                        "pubDate": "2026-05-03T12:00:00Z",
                        "summary": "Solar Capital dividend article unrelated to Nvidia.",
                    }
                },
                {
                    "content": {
                        "title": "Nvidia data center demand remains strong",
                        "provider": {"displayName": "Yahoo"},
                        "canonicalUrl": {"url": "https://finance.yahoo.com/news/nvidia-data-center.html"},
                        "pubDate": "2026-05-03T13:00:00Z",
                        "summary": "NVDA AI chip demand and data center revenue remain in focus.",
                    }
                },
            ]

    monkeypatch.setattr(news_mod.yf, "Ticker", lambda _ticker: _Ticker())
    monkeypatch.setattr(news_mod, "finnhub_client", None)
    monkeypatch.setattr(news_mod, "search_authoritative_feeds", lambda *args, **kwargs: [])
    monkeypatch.setattr(news_mod, "ALPHA_VANTAGE_API_KEY", "")

    items = news_mod.get_company_news("NVDA", limit=5)

    assert [item["title"] for item in items] == ["Nvidia data center demand remains strong"]


def test_get_company_news_cools_down_yfinance_after_timeout(monkeypatch):
    from backend.tools import news as news_mod

    attempts = []

    class _Ticker:
        def __init__(self, ticker):
            attempts.append(ticker)

        @property
        def news(self):
            raise TimeoutError("timed out")

    monkeypatch.setattr(news_mod, "_YFINANCE_NEWS_DISABLED_UNTIL", 0.0)
    monkeypatch.setattr(news_mod, "_YFINANCE_NEWS_COOLDOWN_SEC", 900)
    monkeypatch.setattr(news_mod.yf, "Ticker", lambda ticker: _Ticker(ticker))
    monkeypatch.setattr(news_mod, "finnhub_client", None)
    monkeypatch.setattr(news_mod, "search_authoritative_feeds", lambda *args, **kwargs: [])
    monkeypatch.setattr(news_mod, "ALPHA_VANTAGE_API_KEY", "")
    monkeypatch.setattr(news_mod, "_http_get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(news_mod, "search", lambda _query: "")

    first = news_mod.get_company_news("NVDA", limit=1)
    second = news_mod.get_company_news("NVDA", limit=1)

    assert first == []
    assert second == []
    assert attempts == ["NVDA"]


def test_get_company_news_prefers_finnhub_when_configured(monkeypatch):
    from backend.tools import news as news_mod

    class _Ticker:
        @property
        def news(self):  # pragma: no cover - should not be called
            raise AssertionError("yfinance should not be called before Finnhub")

    class _Finnhub:
        def company_news(self, ticker, _from, to):
            return [
                {
                    "headline": f"Nvidia {ticker} data center news remains relevant",
                    "summary": "NVDA AI chip demand and data center revenue remain in focus.",
                    "source": "Finnhub",
                    "datetime": 1770000000,
                    "url": "https://example.com/nvda",
                }
            ]

    monkeypatch.setattr(news_mod, "_YFINANCE_NEWS_DISABLED_UNTIL", 0.0)
    monkeypatch.setattr(news_mod.yf, "Ticker", lambda _ticker: _Ticker())
    monkeypatch.setattr(news_mod, "finnhub_client", _Finnhub())

    items = news_mod.get_company_news("NVDA", limit=1)

    assert items
    assert items[0]["source"] == "Finnhub"


def test_get_company_news_prefers_authoritative_links_over_unlinked_finnhub(monkeypatch):
    from backend.tools import news as news_mod

    class _Ticker:
        @property
        def news(self):  # pragma: no cover - should not be called when authoritative links exist
            raise AssertionError("yfinance should not be called before authoritative linked news")

    class _Finnhub:
        def company_news(self, ticker, _from, to):
            return [
                {
                    "headline": "Apple supply chain update mentions AAPL",
                    "summary": "Apple AAPL supply chain story without a direct article URL.",
                    "source": "Finnhub",
                    "datetime": 1770000000,
                    "url": "",
                }
            ]

    monkeypatch.setattr(news_mod, "_YFINANCE_NEWS_DISABLED_UNTIL", 0.0)
    monkeypatch.setattr(news_mod.yf, "Ticker", lambda _ticker: _Ticker())
    monkeypatch.setattr(news_mod, "finnhub_client", _Finnhub())
    monkeypatch.setattr(
        news_mod,
        "search_authoritative_feeds",
        lambda *args, **kwargs: [
            {
                "title": "Apple AAPL supplier story with direct link",
                "snippet": "Apple and AAPL supply chain details are discussed.",
                "source": "finance.yahoo.com",
                "url": "https://finance.yahoo.com/news/apple-supplier-story.html",
                "published_date": "2026-05-10T12:00:00Z",
            }
        ],
    )

    items = news_mod.get_company_news("AAPL", limit=1)

    assert items
    assert items[0]["title"] == "Apple AAPL supplier story with direct link"
    assert items[0]["url"] == "https://finance.yahoo.com/news/apple-supplier-story.html"
