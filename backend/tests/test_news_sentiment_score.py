# -*- coding: utf-8 -*-
"""
get_news_sentiment_score 结构化舆情分数测试（mock HTTP）。

覆盖：
- 正常返回 N 篇文章平均分 + 分档 label
- API 限流（Note 字段）→ score=None + error
- 无数据（feed 为空）→ score=None + error
- 缺 API key → score=None + error
- ticker_sentiment 缺失时回退 overall_sentiment_score

策略：monkeypatch backend.tools.news 的 _http_get 与 ALPHA_VANTAGE_API_KEY，
不发真实网络请求。
"""

from __future__ import annotations

import pytest

from backend.tools import news


class _FakeResponse:
    """最小 requests.Response 替身，只实现 json()。"""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _feed_item(score, label="Somewhat-Bullish", ticker="AAPL"):
    return {
        "title": "Some headline",
        "source": "Reuters",
        "time_published": "20260603T120000",
        "url": "https://example.com/a",
        "overall_sentiment_score": 0.0,
        "overall_sentiment_label": "Neutral",
        "ticker_sentiment": [
            {"ticker": ticker, "ticker_sentiment_score": str(score), "ticker_sentiment_label": label}
        ],
    }


@pytest.fixture()
def with_api_key(monkeypatch):
    monkeypatch.setattr(news, "ALPHA_VANTAGE_API_KEY", "TEST_KEY")


def test_returns_average_score(with_api_key, monkeypatch):
    """两篇文章 0.4 与 0.6 → 平均 0.5，label=Bullish，article_count=2。"""
    payload = {"feed": [_feed_item(0.4), _feed_item(0.6)]}
    monkeypatch.setattr(news, "_http_get", lambda *a, **k: _FakeResponse(payload))

    result = news.get_news_sentiment_score("AAPL")
    assert result["ticker"] == "AAPL"
    assert result["score"] == 0.5
    assert result["label"] == "Bullish"
    assert result["article_count"] == 2
    assert result["error"] is None


def test_negative_average_labeled_bearish(with_api_key, monkeypatch):
    payload = {"feed": [_feed_item(-0.4), _feed_item(-0.6)]}
    monkeypatch.setattr(news, "_http_get", lambda *a, **k: _FakeResponse(payload))

    result = news.get_news_sentiment_score("AAPL")
    assert result["score"] == -0.5
    assert result["label"] == "Bearish"


def test_rate_limited_returns_none_score(with_api_key, monkeypatch):
    """API 限流（Note 字段）→ score=None + error 含 rate limited。"""
    payload = {"Note": "Thank you for using Alpha Vantage! ... 25 requests per day"}
    monkeypatch.setattr(news, "_http_get", lambda *a, **k: _FakeResponse(payload))

    result = news.get_news_sentiment_score("AAPL")
    assert result["score"] is None
    assert result["error"] is not None
    assert "rate limited" in result["error"].lower()


def test_no_data_returns_none_score(with_api_key, monkeypatch):
    """feed 为空 → score=None + error。"""
    monkeypatch.setattr(news, "_http_get", lambda *a, **k: _FakeResponse({"feed": []}))

    result = news.get_news_sentiment_score("AAPL")
    assert result["score"] is None
    assert result["error"] is not None


def test_missing_api_key_returns_none_score(monkeypatch):
    """无 API key → score=None + error，不发请求。"""
    monkeypatch.setattr(news, "ALPHA_VANTAGE_API_KEY", "")

    def boom(*a, **k):
        raise AssertionError("_http_get should not be called without API key")

    monkeypatch.setattr(news, "_http_get", boom)
    result = news.get_news_sentiment_score("AAPL")
    assert result["score"] is None
    assert "ALPHA_VANTAGE_API_KEY" in (result["error"] or "")


def test_empty_ticker_returns_error(monkeypatch):
    result = news.get_news_sentiment_score("")
    assert result["score"] is None
    assert result["error"] == "ticker is required."


def test_feed_without_sentiment_scores_returns_none(with_api_key, monkeypatch):
    """有文章但无任何可用情绪分（字段缺失）→ score=None + error，不编造 0。"""
    item = {"title": "x", "source": "y", "time_published": "20260603T120000", "ticker_sentiment": []}
    monkeypatch.setattr(news, "_http_get", lambda *a, **k: _FakeResponse({"feed": [item]}))

    result = news.get_news_sentiment_score("AAPL")
    assert result["score"] is None
    assert result["error"] is not None


def test_get_news_sentiment_text_unchanged(with_api_key, monkeypatch):
    """回归：文本版 get_news_sentiment 对外行为不变（复用同一抓取逻辑后仍返回带平均分的文本）。"""
    payload = {"feed": [_feed_item(0.25, label="Bullish")]}
    monkeypatch.setattr(news, "_http_get", lambda *a, **k: _FakeResponse(payload))

    text = news.get_news_sentiment("AAPL", limit=5)
    assert text.startswith("News Sentiment (AAPL):")
    assert "平均情绪分数" in text
