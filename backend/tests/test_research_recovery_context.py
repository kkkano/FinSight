"""保留真实资料读回、时间口径、确定性计算和脱敏边界。"""
import json
import httpx
import pytest

from backend.agent_runtime.analysis import analyze_dataset, render_chart
from backend.agent_runtime.context import tokens
from backend.agent_runtime.data import RunData
from backend.agent_runtime.diagnostics import clean_text
from backend.agent_runtime.model import ModelTransport
from backend.agent_runtime.registry import history_with_returns
from backend.tests.test_agent_runtime import cfg, execute, runtime


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FINSIGHT_ACTION_STORE", str(tmp_path / "actions.sqlite"))
    monkeypatch.setenv("FINSIGHT_RUNTIME_QUOTA_DB", str(tmp_path / "quota.sqlite"))
    monkeypatch.setenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")


@pytest.mark.parametrize("observed,closed,count", [("2026-11-04T20:00:00Z", False, 0), ("2026-11-08T12:00:00Z", True, 1)])
def test_weekly_completion_uses_exchange_close_and_keeps_streak_status_separate(observed, closed, count):
    data = RunData("u", "s", "r", "SOXX周线")
    dates = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02"]
    ref = data.record("get_stock_historical_data", {"ticker": "SOXX", "interval": "1wk"}, {
        "source": "fixture", "observed_at": observed, "asset": {"calendar_name": "NYSE"},
        "rows": [{"date": day, "close": 210-index*10} for index, day in enumerate(dates)]})
    result = analyze_dataset(data, ref, "historical_drawdown_episodes", {"frequency": "weekly", "min_periods": 5})
    output = data.records[result["data_refs"][0]]["output"]
    assert output["method"]["latest_period_closed"] is closed
    assert output["sample_count"] == count
    if closed:
        assert output["episodes"][0]["ongoing"] is True
        assert output["method"]["latest_period_close"].startswith("2026-11-06")


@pytest.mark.asyncio
async def test_final_transport_explicitly_disables_tools_without_schemas():
    async def handler(request):
        payload = json.loads(request.content)
        assert payload["tool_choice"] == "none" and "tools" not in payload
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"完整答案"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = [chunk async for chunk in ModelTransport(cfg(), client=client).stream([], [], tool_choice="none")]
    assert result[0]["choices"][0]["finish_reason"] == "stop"


def test_historical_returns_are_computed_and_do_not_bridge_missing_closes():
    original = {"data": [{"time": "2026-10-29", "close": 92.07}, {"time": "2026-10-30", "close": 65.76},
                         {"time": "2026-11-02", "close": None}, {"time": "2026-11-03", "close": 60.55}]}
    result = history_with_returns(original)
    assert result["data"][1]["period_return_pct"] == pytest.approx((65.76/92.07-1)*100)
    assert result["data"][2]["period_return_pct"] is None and result["data"][3]["period_return_pct"] is None
    assert "period_return_pct" not in original["data"][1]


def test_redaction_preserves_markdown_links_and_sentence_endings():
    text = "[原文](https://example.com/story?ref=yahoo&.tsrc=rss)。这是一句完整说明。"
    assert clean_text(text, len(text)) == text
    balanced = "[原文](https://example.com/Company_(group))。"
    assert clean_text(balanced, len(balanced)) == balanced
    sensitive = clean_text("https://user:pa)ss@example.com/file?api_key=very)secret)说明", 1000)
    assert "pa)ss" not in sensitive and "very" not in sensitive and "secret" not in sensitive


@pytest.mark.asyncio
async def test_inspect_financials_returns_latest_periods_in_descending_data(tmp_path):
    rt, _ = runtime(tmp_path, [])
    raw = {"source": "sec_companyfacts", "period_ends": ["2026-09-26", "2026-06-27", "2026-03-28"],
           "revenue": [16513000000, 16128000000, 10000000000], "net_income": [3320000000, -11033000000, 1]}
    ref = rt.data.record("get_sec_company_facts_quarterly", {"ticker": "INTC"}, raw)
    try:
        result = await execute(rt, "read_data", {"handle": ref, "limit": 2})
        assert result.status == "ok"
        assert [row["period_end"] for row in result.data["rows"]] == ["2026-09-26", "2026-06-27"]
        assert [row["net_income"] for row in result.data["rows"]] == [3320000000, -11033000000]
        assert result.data["row_count"] == 3 and result.data["has_more"] is True
        assert rt.data.records[ref]["output"] == raw
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_explicit_readback_keeps_content_and_advances_only_returned_characters(tmp_path):
    rt, _ = runtime(tmp_path, [])
    original = "报道原文" * 5000
    ref = rt.data.record("fetch_url_content", {}, original)
    try:
        result = await execute(rt, "read_data", {"handle": ref, "offset": 1000, "limit": 7200})
        assert result.data["content"] == original[1000:8200]
        assert result.data["next_offset"] == 8200 and result.data["has_more"] is True
        projected = rt.registry.model_text(result, 1000)
        page = json.loads(projected.split("\n\n")[-1])
        assert page["content"] == original[1000:page["next_offset"]]
        assert page["next_offset"] == 1000 + len(page["content"])
        assert page["has_more"] is True and tokens(projected) <= 1000
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_complete_episode_list_is_readable_without_sampling_the_stored_result(tmp_path):
    rt, _ = runtime(tmp_path, [])
    episodes = [{"start": f"2026-01-{i:02}", "end": f"2026-02-{i:02}", "periods": 5, "return_pct": -.1} for i in range(1, 10)]
    raw = {"rows": [{"date": f"2026-01-{i % 28 + 1:02}", "close": i+1} for i in range(1300)],
           "episodes": episodes, "sample_count": 9, "method": {"kind": "consecutive_decline_streaks"}}
    ref = rt.data.record("run_analysis_code", {}, raw)
    try:
        result = await execute(rt, "read_data", {"handle": ref, "table": "episodes", "limit": 20})
        assert result.status == "ok" and result.data["row_count"] == 9
        assert result.data["rows"] == episodes
        assert rt.data.records[ref]["output"] == raw
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_history_aliases_do_not_hide_latest_rows_or_sampling_boundaries(tmp_path):
    rt, _ = runtime(tmp_path, [])
    rows = [{"time": f"2026-11-{i+1:02}", "close": 100+i} for i in range(20)]
    raw = {"data": rows, "kline_data": rows, "price_basis": "split_adjusted_close", "metadata_noise": "x" * 10000}
    ref = rt.data.record("get_stock_historical_data", {"ticker": "INTC"}, raw)
    try:
        result = await execute(rt, "read_data", {"handle": ref, "offset": 18, "limit": 2})
        assert result.data["rows"][-1]["close"] == 119
        assert result.data["rows"][-1]["time"] == "2026-11-20"
        assert result.data["row_count"] == 20 and result.data["next_offset"] == 20
        assert result.data["has_more"] is False and rt.data.records[ref]["output"] == raw
    finally:
        await rt.close()


def test_streak_calculation_and_chart_keep_exchange_close_and_ongoing_status():
    data = RunData("u", "s", "r", "SOXX连续下跌")
    dates = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02"]
    ref = data.record("get_stock_historical_data", {"ticker": "SOXX", "interval": "1wk"}, {
        "observed_at": "2026-11-08T12:00:00Z", "asset": {"calendar_name": "NYSE"},
        "rows": [{"date": day, "close": 210-i*10} for i, day in enumerate(dates)]})
    result = analyze_dataset(data, ref, "historical_drawdown_episodes", {"frequency": "weekly", "min_periods": 5})
    assert result["sample_count"] == 1 and result["episodes"][0]["ongoing"] is True
    assert result["method"]["latest_period_closed"] is True
    assert result["method"]["latest_period_close"] == "2026-11-06T21:00:00+00:00"
    chart = render_chart(data, result["data_refs"][0], "SOXX周线", "line", "date", [{"field": "close"}])
    assert chart["method"] == result["method"]
    assert chart["data"]["rows"] == data.rows(result["data_refs"][0])
