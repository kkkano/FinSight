"""事件质量回归：重复采集、旧闻、搜索时间与传闻不能变成当前事实。"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.research import news_event_quality as quality
from backend.services.market_data_gateway import validate_news_items
from backend.tools import news

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(quality, "utc_now", lambda: NOW)


def article(**fields):
    return {"title": "Apple announces new product launch", "source": "Reuters",
            "url": "https://www.reuters.com/technology/apple-launch",
            "published_at": "2026-10-03T10:00:00Z", **fields}


def test_separately_listed_companies_cannot_share_a_short_brand_match():
    assert quality.news_subject_match("GE", "GE Vernova announces a new turbine order") == "none"
    assert quality.news_subject_match("GE", "GE HealthCare reports quarterly earnings") == "none"
    assert quality.news_subject_match("GEV", "GE Vernova announces a new turbine order") == "headline"
    assert quality.news_subject_match("GE", "GE Aerospace announces an engine order") == "headline"
    assert quality.news_subject_match("GE", "GE Vernova and GE Aerospace announce a partnership") == "headline"
    assert quality.news_source_tier("https://www.geaerospace.com/news/order", "GE") == "primary"


def test_three_clocks_are_not_interchangeable():
    row = quality.prepare_news_items([article(published_at=None, as_of=NOW.isoformat())], ticker="AAPL")[0]
    meta = row["event_quality"]
    assert meta["published_at"] is None
    assert meta["occurred_at"] is None
    assert meta["observed_at"] == "2026-10-03T12:00:00Z"
    assert meta["freshness"] == "unknown"
    assert meta["usable_as_catalyst"] is False
    assert "发布时间未知" in news.format_news_items([row])


def test_cached_items_age_without_inventing_a_new_observation():
    initial = quality.prepare_news_items([article()], ticker="AAPL", now=NOW)
    later = quality.prepare_news_items(initial, ticker="AAPL", now=datetime(2026, 10, 12, tzinfo=UTC))
    assert later[0]["event_quality"]["observed_at"] == initial[0]["event_quality"]["observed_at"]
    assert later[0]["event_quality"]["freshness"] == "stale"


@pytest.mark.parametrize("published,expected", [
    ("2026-08-01T12:00:00Z", "stale"),
    ("2026-10-04T12:00:00Z", "future"),
    ("2026-10-03T10:00:00Z", "fresh"),
    ("Recent", "unknown"),
    (0, "unknown"),
])
def test_source_time_determines_freshness(published, expected):
    row = quality.prepare_news_items([article(published_at=published)], ticker="AAPL")[0]
    assert row["event_quality"]["freshness"] == expected
    assert row["event_quality"]["usable_as_catalyst"] is (expected == "fresh")


def test_timestamp_precision_survives_provider_and_gateway():
    provider = news._build_news_item("Apple launches a new product", "Reuters",
                                    "https://www.reuters.com/apple", "2026-10-03T11:30:00+02:00")
    rows, _ = validate_news_items([provider])
    row = quality.prepare_news_items(rows, ticker="AAPL")[0]
    assert row["published_at"] == "2026-10-03T09:30:00Z"
    assert row["event_quality"]["published_precision"] == "timestamp"
    assert row["event_quality"]["occurred_at"] is None


def test_date_precision_does_not_gain_midnight_precision_from_gateway():
    provider = news._build_news_item("Apple launches a new product", "Reuters",
                                    "https://www.reuters.com/apple", "2026-10-03")
    rows, _ = validate_news_items([provider])
    row = quality.prepare_news_items(rows, ticker="AAPL")[0]
    assert row["published_at"] == "2026-10-03"
    assert row["event_quality"]["published_precision"] == "date"


def test_search_retrieval_kind_survives_gateway():
    provider = news._build_news_item("Apple releases a product", "Reuters", "https://www.reuters.com/apple",
                                    "2026-10-03", retrieval_kind="search_snippet")
    rows, _ = validate_news_items([provider])
    row = quality.prepare_news_items(rows, ticker="AAPL")[0]
    assert row["event_quality"]["content_kind"] == "discovery"
    assert row["event_quality"]["usable_as_catalyst"] is False


def test_search_date_hint_cannot_become_publication_or_occurrence_date():
    rows = news._build_search_news_items(
        "1. Apple plans a product launch on 2026-10-05\n"
        "A product announcement mentioned in a search snippet.\n"
        "https://www.reuters.com/technology/apple-launch-2026-10-02/",
        now=NOW.replace(tzinfo=None),
    )
    assert rows[0]["published_at"] is None
    assert rows[0]["date_hint"] == "2026-10-05"
    assert rows[0]["event_quality"]["occurred_at"] is None
    assert rows[0]["event_quality"]["verification"] == "discovery_only"


@pytest.mark.parametrize("url", ["https://reuters.com.evil.example/item", "https://notreuters.com/item", "https://reuters.com@evil.example/item"])
def test_source_name_or_url_substring_cannot_impersonate_reuters(url):
    row = quality.prepare_news_items([article(url=url)], ticker="AAPL")[0]
    assert row["event_quality"]["source_tier"] == "unknown"
    assert row["event_quality"]["usable_as_catalyst"] is False
    assert news.score_news_source_reliability("Reuters", url)["reason"] != "domain:reuters.com"


def test_summary_mention_cannot_turn_nike_news_into_nvidia_catalyst():
    row = quality.prepare_news_items([article(title="Nike earnings beat estimates", snippet="NVDA was mentioned in the market wrap")], ticker="NVDA")[0]
    assert row["event_quality"]["subject_match"] == "summary_only"
    assert row["event_quality"]["usable_as_catalyst"] is False


@pytest.mark.parametrize("title", ["Apple acquisition rumor circulates", "Apple could launch a new product", "苹果或将并购芯片公司"])
def test_rumor_and_opinion_are_not_occurrences(title):
    row = quality.prepare_news_items([article(title=title)], ticker="AAPL")[0]
    assert row["event_quality"]["content_kind"] in {"rumor", "opinion"}
    assert row["event_quality"]["usable_as_catalyst"] is False


def test_primary_statement_is_attributed_and_not_independently_verified():
    row = quality.prepare_news_items([article(url="https://www.apple.com/newsroom/launch")], ticker="AAPL")[0]
    assert row["event_quality"]["source_tier"] == "primary"
    assert row["event_quality"]["verification"] == "headline_only"
    assert row["event_quality"]["independence"] == "unverified"


def test_duplicate_tracking_urls_and_cross_source_headlines_count_once():
    rows = quality.prepare_news_items([
        article(url="https://www.reuters.com/technology/apple-launch?utm_source=a"),
        article(url="https://www.reuters.com/technology/apple-launch?utm_source=b#top"),
        article(url="https://www.cnbc.com/apple-launch", source="CNBC"),
    ], ticker="AAPL")
    assert len(rows) == 1
    assert rows[0]["event_quality"]["report_count"] == 2
    assert rows[0]["event_quality"]["source_count"] == 2
    assert rows[0]["event_quality"]["independence"] == "unverified"
    again = quality.prepare_news_items(rows, ticker="AAPL")
    assert len(again[0]["supporting_reports"]) == 2
    assert again[0]["event_quality"]["report_count"] == 2


def test_canonicalization_preserves_article_identity_query():
    assert quality.canonical_news_url("https://www.cninfo.com.cn/detail?id=1&utm_campaign=x") != quality.canonical_news_url("https://www.cninfo.com.cn/detail?id=2")


def test_followup_and_next_day_republication_remain_distinct():
    rows = quality.prepare_news_items([
        article(),
        article(title="Apple recalls the new product", url="https://www.reuters.com/apple-recall"),
        article(published_at="2026-10-02T10:00:00Z"),
    ], ticker="AAPL")
    assert len(rows) == 3
    assert len({row["event_quality"]["event_id"] for row in rows}) == 3


def test_empty_calendar_does_not_invent_three_macro_events(monkeypatch):
    monkeypatch.setattr(news, "create_ticker", lambda _ticker: SimpleNamespace(calendar={}, earnings_dates=None))
    monkeypatch.setattr(news, "search", lambda _query: "")
    calendar = news.get_event_calendar("AAPL")
    assert calendar["macro_events"] == []
    assert calendar["discovery_candidates"] == []
    assert calendar["error"] == "no_calendar_events"


def test_unverified_macro_calendar_search_is_only_a_discovery(monkeypatch):
    monkeypatch.setattr(news, "create_ticker", lambda _ticker: SimpleNamespace(calendar={}, earnings_dates=None))
    monkeypatch.setattr(news, "search", lambda _query: "CPI FOMC economic calendar, date still unknown")
    calendar = news.get_event_calendar("AAPL")
    assert calendar["macro_events"] == []
    assert calendar["discovery_candidates"][0]["verification"] == "discovery_only"
    assert calendar["discovery_candidates"][0]["date"] is None


def test_rss_future_item_is_not_recent_and_timezone_is_utc():
    rss = """<rss><channel><item><title>Apple reports quarterly earnings</title><link>https://www.reuters.com/apple</link><pubDate>Sat, 03 Oct 2026 10:30:00 -0400</pubDate></item></channel></rss>"""
    lines, fresh = news._parse_rss_items(rss, now=NOW.replace(tzinfo=None))
    assert lines == [] and fresh is False


def test_sentiment_excludes_old_or_unknown_samples_and_duplicate_weight():
    base = {**article(), "ticker_sentiment": [{"ticker": "AAPL", "ticker_sentiment_score": "0.8"}]}
    rows = news._current_sentiment_feed([base, base, {**base, "url": "https://www.reuters.com/old", "published_at": "2026-08-01"},
                                         {**base, "published_at": None}], "AAPL")
    assert len(rows) == 1
    assert rows[0]["event_quality"]["freshness"] == "fresh"


def test_another_tickers_sentiment_does_not_fall_back_to_overall():
    score, label = news._extract_ticker_sentiment({"overall_sentiment_score": 0.9, "ticker_sentiment": [{"ticker": "NKE", "ticker_sentiment_score": -0.5}]}, "NVDA")
    assert score is None and label is None


def test_authoritative_wrapper_classifies_analysis_questions_and_search_fallback(monkeypatch):
    from backend.tools import authoritative_feeds

    question = "Is Applied Optoelectronics (AAOI) Quietly Reframing Its Edge Around AI-Driven DOCSIS Network Intelligence?"
    rows = [
        {"title": question, "url": "https://finance.yahoo.com/news/aaoi-analysis?utm_source=rss", "source": "Yahoo Finance",
         "published_date": "2026-10-03T08:00:00Z", "is_authoritative": True},
        {"title": "AAOI announces a new factory", "url": "https://www.reuters.com/aaoi-factory", "source": "search",
         "published_date": "2026-10-03", "is_authoritative": True},
        {"title": "AAOI reports quarterly results", "url": "https://www.reuters.com/aaoi-earnings", "source": "Reuters",
         "published_date": "2026-10-03T10:00:00+02:00", "is_authoritative": True},
    ]
    monkeypatch.setattr(authoritative_feeds, "search_authoritative_feeds", lambda *args, **kwargs: rows)
    payload = authoritative_feeds.get_authoritative_media_news("AAOI latest news")
    articles = {row["title"]: row for row in payload["articles"]}
    assert len(articles) == 3
    assert articles[question]["event_quality"]["content_kind"] == "opinion"
    assert articles[question]["event_quality"]["usable_as_catalyst"] is False
    assert articles[question]["url"] == rows[0]["url"]  # 点击链接保持原样。
    assert "utm_source" not in articles[question]["event_quality"]["canonical_url"]
    search_row = articles["AAOI announces a new factory"]
    assert search_row["retrieval_kind"] == "search"
    assert search_row["event_quality"]["evidence_role"] == "discovery"
    assert search_row["event_quality"]["published_precision"] == "date"
    report = articles["AAOI reports quarterly results"]
    assert report["event_quality"]["evidence_role"] == "reported_news"
    assert report["event_quality"]["published_at"] == "2026-10-03T08:00:00Z"
    assert report["event_quality"]["occurred_at"] is None


def test_authoritative_multi_ticker_query_keeps_each_actual_subject_and_shared_report(monkeypatch):
    from backend.tools import authoritative_feeds

    rows = [
        {"title": title, "url": f"https://www.reuters.com/story-{index}", "source": "Reuters", "published_date": "2026-10-03"}
        for index, title in enumerate(["Apple reports earnings", "Nvidia launches a chip", "Apple and Nvidia announce a partnership", "Nike earnings decline"])
    ]
    monkeypatch.setattr(authoritative_feeds, "search_authoritative_feeds", lambda *args, **kwargs: rows)
    payload = authoritative_feeds.get_authoritative_media_news("AAPL NVDA latest news")
    articles = {row["title"]: row for row in payload["articles"]}
    assert len(articles) == 3 and payload["excluded_subject_count"] == 1
    assert articles["Apple reports earnings"]["subject_tickers"] == ["AAPL"]
    assert articles["Nvidia launches a chip"]["subject_tickers"] == ["NVDA"]
    shared = articles["Apple and Nvidia announce a partnership"]
    assert set(shared["subject_tickers"]) == {"AAPL", "NVDA"}
    assert shared["ticker"] == ""
    assert shared["subject_matches"] == {"AAPL": "headline", "NVDA": "headline"}
