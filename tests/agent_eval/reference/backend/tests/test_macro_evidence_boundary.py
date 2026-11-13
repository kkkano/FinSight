"""宏观工具失败、搜索线索与实际指标读数的生产者边界。"""

from types import SimpleNamespace

import pytest

from backend.agents.macro_agent import MacroAgent

SEARCH_FAILURE = "Search error: 所有搜索源均失败，无法获取搜索结果。"


def tools(**overrides):
    defaults = {
        "get_fred_data": lambda: {"status": "data_unavailable", "unavailable_reason": "fixture"},
        "get_official_macro_releases": lambda **kwargs: {"releases": []},
        "get_market_sentiment": lambda: "Fear & Greed Index: Unable to fetch. Please check manually.",
        "get_economic_events": lambda: SEARCH_FAILURE,
        "search": lambda query: SEARCH_FAILURE,
    }
    return SimpleNamespace(**{**defaults, **overrides})


@pytest.mark.asyncio
async def test_failure_text_is_source_health_not_macro_evidence():
    agent = MacroAgent(None, None, tools())
    payload = await agent._initial_search("宏观环境", "AAPL")
    assert payload["source_health"]["economic_events"] == "failed:tool_error"
    assert payload["source_health"]["search_cross_check"] == "failed:tool_error"
    assert payload["source_health"]["market_sentiment"] == "failed:tool_error"
    assert payload["economic_events"] == payload["cross_check_raw"] == payload["market_sentiment"] == ""
    assert payload["used_sources"] == []
    output = agent._format_output(await agent._first_summary(payload), payload)
    assert output.evidence == []
    assert output.data_sources == []
    assert "Search error" not in output.summary
    assert output.evidence_quality["source_health"]["economic_events"].startswith("failed")


@pytest.mark.asyncio
async def test_search_numbers_and_calendar_are_only_unverified_material():
    agent = MacroAgent(None, None, tools(
        search=lambda query: "Federal funds rate 4.5%, CPI inflation 3.2% year-over-year, unemployment rate 4.0%",
        get_economic_events=lambda: "A search summary suggests CPI release on October 10.",
    ))
    payload = await agent._initial_search("宏观环境", "AAPL")
    assert payload["fed_rate"] is None and payload["cpi"] is None and payload["unemployment"] is None
    assert payload["merge"]["coverage_count"] == 0
    assert all(item["value"] is None for item in payload["indicators"])
    assert payload["conflicts"] == []
    assert payload["source_health"]["search_cross_check"] == "discovery_only"
    output = agent._format_output(await agent._first_summary(payload), payload)
    assert len(output.evidence) == 2
    assert all(item.meta["usage"] == "raw" and item.meta["verification"] == "discovery_only" for item in output.evidence)
    assert output.chart_specs == []
    assert "4.5%" not in output.summary


@pytest.mark.asyncio
async def test_fred_metrics_remain_facts_despite_search_errors_or_disagreement():
    agent = MacroAgent(None, None, tools(
        get_fred_data=lambda: {"fed_rate": 4.5, "cpi": 3.2, "indicator_metadata": {
            "cpi": {"unit": "percent", "definition": "inflation_yoy", "period_end": "2026-08-01"}}},
        search=lambda query: "Federal funds rate 8.5% and CPI inflation 9.2% year-over-year",
    ))
    payload = await agent._initial_search("宏观环境", "AAPL")
    assert payload["fed_rate"] == 4.5 and payload["cpi"] == 3.2
    assert payload["conflicts"] == []  # 未核验摘要不是已确认的同口径冲突。
    output = agent._format_output(await agent._first_summary(payload), payload)
    fred = [item for item in output.evidence if item.source == "FRED"]
    assert len(fred) == 2
    assert all(item.meta["usage"] == "fact" for item in fred)
    assert next(item for item in fred if item.meta["indicator_key"] == "cpi").timestamp == "2026-08-01"
    assert len(output.chart_specs) == 1
    assert not any(item.source == "Economic Calendar" for item in output.evidence)
    assert next(item for item in output.evidence if item.source == "Web Search").meta["usage"] == "raw"


@pytest.mark.asyncio
async def test_official_release_preserves_its_source_url_and_time():
    release = {"title": "CPI news release", "snippet": "The CPI rose 3.2 percent over the year.",
               "source": "BLS", "url": "https://www.bls.gov/news.release/cpi.nr0.htm",
               "published_date": "2026-09-10T12:30:00Z"}
    agent = MacroAgent(None, None, tools(get_official_macro_releases=lambda **kwargs: {"releases": [release]}))
    payload = await agent._initial_search("宏观环境", "AAPL")
    output = agent._format_output(await agent._first_summary(payload), payload)
    item = next(item for item in output.evidence if item.source == "BLS")
    assert item.url == release["url"] and item.timestamp == release["published_date"]
    assert item.meta["usage"] == "fact"
    assert item.meta["verification"] == "provider_reported"
    assert not any("Search error" in item.text for item in output.evidence)


def test_legacy_raw_payload_cannot_reintroduce_failure_evidence():
    agent = MacroAgent(None, None, None)
    output = agent._format_output("已有报告上下文", {
        "status": "fallback", "used_sources": ["economic_events", "search_cross_check"],
        "source_health": {"economic_events": "ok", "search_cross_check": "ok"},
        "economic_events": SEARCH_FAILURE, "cross_check_raw": SEARCH_FAILURE,
    })
    assert output.evidence == [] and output.data_sources == []
    assert output.evidence_quality["source_health"]["economic_events"] == "failed:tool_error"


def test_legacy_search_indicators_are_raw_and_cannot_generate_a_chart():
    agent = MacroAgent(None, None, None)
    output = agent._format_output("检索线索", {
        "status": "fallback", "used_sources": ["search_cross_check"],
        "indicators": [
            {"key": "fed_rate", "name": "Fed rate", "value": 4.5, "source": "search_cross_check"},
            {"key": "unemployment", "name": "Unemployment", "value": 4.0, "source": "search_cross_check"},
        ],
    })
    assert len(output.evidence) == 2
    assert all(item.meta["usage"] == "raw" for item in output.evidence)
    assert output.chart_specs == []


@pytest.mark.parametrize("value", [{"error": "fixture unavailable"}, "403 Forbidden", "Search error: no source", "No search results"])
def test_existing_failure_envelopes_are_never_successful_text(value):
    text, health = MacroAgent._source_text(value)
    assert text == ""
    assert health in {"failed:tool_error", "empty"}
