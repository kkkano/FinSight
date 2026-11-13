"""事件质量回归：重复采集、旧闻、搜索时间与传闻不能变成当前事实。"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.agents.news_agent import NewsAgent
from backend.agents.sentiment_brief import build_light_snapshot, render_stock_brief
from backend.research import news_event_quality as quality
from backend.services.market_data_gateway import validate_news_items
from backend.tools import news

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(quality, "utc_now", lambda: NOW)
    monkeypatch.setattr("backend.agents.news_agent.utc_now", lambda: NOW)


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


def test_query_ticker_in_url_or_summary_does_not_upgrade_another_issuers_headline():
    from backend.graph.synthesis.research_synthesis import _news_bound_to_subject
    assert not _news_bound_to_subject({"title": "GE Vernova wins an energy contract",
        "snippet": "Search results for GE", "url": "https://example.invalid/search?q=GE"}, "GE", {})
    assert not _news_bound_to_subject({"title": "Unrelated earnings announcement",
        "snippet": "AAPL query matches", "url": "https://example.invalid/?ticker=AAPL"}, "AAPL", {})


def test_verified_issuer_names_stay_phrases_and_sec_name_can_bind_its_own_news():
    from backend.graph.synthesis.research_synthesis import _news_bound_to_subject, _subject_names
    steps = [{"id": "company", "name": "get_company_info", "inputs": {"ticker": "IBM"}},
             {"id": "filing", "name": "get_sec_company_facts_quarterly", "inputs": {"ticker": "ORCL"}}]
    names = _subject_names(steps, {"company": {"name": "International Business Machines Corp."},
        "filing": '{"ticker":"ORCL","company_name":"ORACLE CORP"}'})
    assert "Business" not in names["IBM"] and "International" not in names["IBM"]
    assert not _news_bound_to_subject({"title": "International business confidence improves"}, "IBM", names)
    assert _news_bound_to_subject({"title": "Oracle announces a new customer contract"}, "ORCL", names)


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


def test_tool_gateway_execution_and_synthesis_keep_news_quality(monkeypatch):
    from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
    from backend.graph.synthesis.research_synthesis import normalize_evidence
    from backend.graph.synthesis.task_outcomes import TaskDescriptor

    rows, as_of = validate_news_items([
        article(published_at="2026-07-01"),
        article(published_at="2026-10-03", retrieval_kind="search_snippet"),
    ])
    gateway = SimpleNamespace(get_news=lambda *args, **kwargs: {"data": rows, "provider": "fixture", "as_of": as_of.isoformat()})
    monkeypatch.setattr("backend.services.market_data_gateway.get_market_data_gateway", lambda: gateway)
    output = news.get_company_news("AAPL")
    task = {"id": "task", "tickers": ["AAPL"], "required_evidence": ["news_context"]}
    step = {"id": "news", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "AAPL"},
            "subject_tickers": ["AAPL"], "task_ids": ["task"], "evidence_kinds": ["news_context"]}
    state = {"subject": {"tickers": ["AAPL"]}, "tasks": [task], "artifacts": {"step_results": {"news": {"output": output}}}}
    normalize_execution_evidence(state=state, plan_ir={"tasks": [task], "steps": [step]}, artifacts=state["artifacts"])
    descriptor = TaskDescriptor(task_id="task", title="AAPL 新闻", priority=0, order_index=0, operation="news_impact",
                                subject_label="AAPL", tickers=["AAPL"], request_frame_id="frame", render_kind="single",
                                render_group_id="frame", intent_status="ready", required_step_ids=["news"],
                                required_evidence=["news_context"], error_codes=[])
    result = normalize_evidence(task_descriptors=[descriptor], plan_steps=[step], agent_outputs={},
                                raw_evidence_by_task=state["artifacts"]["evidence_by_task"])
    evidence = list(result.evidence_index.values())
    assert len(evidence) == 2  # 同URL跨日内容不能在执行层被吞掉。
    assert all(item.usage == "raw" for item in evidence)
    assert {item.metadata["event_quality"]["freshness"] for item in evidence} == {"fresh", "stale"}
    assert all(item.metadata["event_quality"]["published_precision"] == "date" for item in evidence)


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


def test_unknown_or_old_reports_cannot_become_catalysts_in_either_snapshot():
    rows = [article(published_at=None), article(title="Apple reports record earnings", published_at="2026-07-01")]
    annotated = quality.prepare_news_items(rows, ticker="AAPL")
    agent = NewsAgent(None, None, SimpleNamespace())
    agent._current_ticker = "AAPL"
    assert agent._build_catalyst_events(annotated)["count"] == 0
    snapshot = build_light_snapshot("AAPL", rows)
    assert snapshot["catalyst_events"]["count"] == 0
    assert snapshot["heat"]["news_count"] == 0
    md = render_stock_brief(snapshot, rows, None)
    assert "旧闻背景" in md and "发布时间未知" in md


def test_news_agent_evidence_preserves_discovery_role_and_provenance():
    agent = NewsAgent(None, None, SimpleNamespace())
    agent._current_ticker = "AAPL"
    agent._current_query = "AAPL最近新闻"
    output = agent._format_output("测试摘要", [article(published_at=None)])
    evidence = output.evidence[0]
    assert evidence.title == "Apple announces new product launch"
    assert evidence.meta["event_quality"]["freshness"] == "unknown"
    assert evidence.meta["verification"] == "discovery_only"
    assert evidence.meta["usage"] == "raw"
    assert evidence.meta["subject"] == "AAPL"
    assert not any(claim["metadata"]["claim_type"] == "catalyst_candidate" for claim in output.claims)


def test_unrelated_news_is_diagnostic_only_for_company_but_kept_for_market():
    agent = NewsAgent(None, None, SimpleNamespace())
    agent._current_ticker = "0700.HK"
    agent._current_query = "腾讯最近新闻"
    rows = [article(title="Nike quarterly earnings decline", url="https://www.reuters.com/nike"),
            article(title="G7 leaders discuss trade", url="https://www.reuters.com/g7")]
    retained = agent._prepare_news_items(rows, "0700.HK")
    assert retained == []
    output = agent._format_output("未找到相关新闻。", retained)
    assert output.evidence == [] and output.claims == []
    assert "Nike" not in output.summary and "G7" not in output.summary
    diagnostic = next(event for event in output.trace if event["event_type"] == "news_quality_filter")
    assert diagnostic["metadata"]["excluded_count"] == 2
    assert all(item["reason"] == "subject_unrelated" for item in diagnostic["metadata"]["excluded"])
    assert len(agent._prepare_news_items(rows, "")) == 2
    assert len(agent._prepare_news_items(rows, "^GSPC")) == 2


def test_summary_only_news_remains_an_explicit_discovery():
    agent = NewsAgent(None, None, SimpleNamespace())
    rows = agent._prepare_news_items([article(title="Market review includes gaming sector", snippet="Tencent issued a trading update")], "0700.HK")
    assert len(rows) == 1
    assert rows[0]["event_quality"]["subject_match"] == "summary_only"
    assert rows[0]["event_quality"]["evidence_role"] == "discovery"


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


def test_authoritative_tool_to_normalized_evidence_preserves_opinion_boundary(monkeypatch):
    from backend.tools import authoritative_feeds
    from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
    from backend.graph.synthesis.research_synthesis import normalize_evidence
    from backend.graph.synthesis.task_outcomes import TaskDescriptor

    rows = [{"title": "Is AAOI becoming an AI networking leader?", "url": "https://finance.yahoo.com/news/aaoi-opinion",
             "source": "Yahoo Finance", "published_date": "2026-10-03", "is_authoritative": True}]
    monkeypatch.setattr(authoritative_feeds, "search_authoritative_feeds", lambda *args, **kwargs: rows)
    payload = authoritative_feeds.get_authoritative_media_news("AAOI recent news")
    task = {"id": "news", "tickers": ["AAOI"], "required_evidence": ["news_context"]}
    step = {"id": "s2", "kind": "tool", "name": "get_authoritative_media_news", "inputs": {"query": "AAOI recent news"},
            "subject_tickers": ["AAOI"], "task_ids": ["news"], "evidence_kinds": ["news_context"]}
    state = {"subject": {"tickers": ["AAOI"]}, "tasks": [task], "artifacts": {"step_results": {"s2": {"output": payload}}}}
    normalize_execution_evidence(state=state, plan_ir={"tasks": [task], "steps": [step]}, artifacts=state["artifacts"])
    descriptor = TaskDescriptor(task_id="news", title="AAOI 新闻", priority=0, order_index=0, operation="news_impact",
                                subject_label="AAOI", tickers=["AAOI"], request_frame_id="frame", render_kind="single",
                                render_group_id="frame", intent_status="ready", required_step_ids=["s2"],
                                required_evidence=["news_context"], error_codes=[])
    result = normalize_evidence(task_descriptors=[descriptor], plan_steps=[step], agent_outputs={},
                                raw_evidence_by_task=state["artifacts"]["evidence_by_task"])
    evidence = list(result.evidence_index.values())
    assert len(evidence) == 1
    assert evidence[0].title == rows[0]["title"]
    assert evidence[0].usage == "raw"
    assert evidence[0].metadata["verification"] == "discovery_only"
    assert evidence[0].metadata["event_quality"]["content_kind"] == "opinion"


@pytest.mark.asyncio
async def test_news_agent_authoritative_supplement_cannot_erase_search_provenance(monkeypatch):
    monkeypatch.setenv("NEWS_STRICT_FINANCE_SOURCES", "true")
    candidates = quality.prepare_news_items([
        article(published_at="2026-10-03", retrieval_kind="search"),
        article(published_at="2026-10-03", retrieval_kind="search", url="https://www.cnbc.com/apple-launch", source="CNBC"),
    ], ticker="AAPL")
    cache = SimpleNamespace(get=lambda key: None, set=lambda *args: None)
    fake_tools = SimpleNamespace(get_company_news=lambda ticker: [],
                                 get_authoritative_media_news=lambda **kwargs: {"articles": candidates})
    agent = NewsAgent(None, cache, fake_tools)
    result = await agent._initial_search("AAPL earnings report", "AAPL")
    assert len(result) == 1
    row = result[0]
    assert row["retrieval_kind"] == "search"
    assert row["published_at_precision"] == "date"
    assert row["event_quality"]["evidence_role"] == "discovery"
    assert row["event_quality"]["usable_as_catalyst"] is False
    assert row["event_quality"]["observed_at"] == candidates[0]["event_quality"]["observed_at"]
    assert len(row["supporting_reports"]) == 2
