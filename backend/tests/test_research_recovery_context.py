"""真实验收暴露的预览、末轮补查和来源投影回归。"""
import json
import httpx

import pytest

from backend.agent_runtime.context import compact_result, prune_messages, tokens
from backend.agent_runtime.completeness import ResearchCompleteness
from backend.agent_runtime.analysis import analyze_dataset
from backend.agent_runtime.data import RunData
from backend.agent_runtime.loop import AgentRuntime
from backend.agent_runtime.model import ModelTransport
from backend.agent_runtime.tools import history_with_returns
from backend.agent_runtime.service import answer_feedback, verified_text
from backend.services.run_context import RunContext
from backend.tests.test_agent_runtime import FakeModel, call, finish, cfg
from backend.tests.test_runtime_completeness import financials, run, tool


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FINSIGHT_ACTION_STORE", str(tmp_path / "actions.sqlite"))
    monkeypatch.setenv("FINSIGHT_RUNTIME_QUOTA_DB", str(tmp_path / "quota.sqlite"))
    monkeypatch.setenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")


@pytest.mark.asyncio
async def test_final_research_turn_still_fetches_missing_required_evidence(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_MAX_TURNS", "1")
    called = []
    tools = {
        "get_company_info": tool("get_company_info", lambda _: (called.append("valuation"), "Forward P/E: 20.0")[1]),
        "get_sec_company_facts_quarterly": tool("get_sec_company_facts_quarterly", lambda a: (called.append("financials"), financials(a))[1]),
    }
    events, model = await run(monkeypatch, "INTC当前估值健康吗", tools)
    assert set(called) == {"valuation", "financials"}
    assert events[-1]["answer_status"] == "answered"
    assert len(model.inputs) == 2


@pytest.mark.asyncio
async def test_verification_can_compute_missing_return_from_existing_evidence(monkeypatch):
    payload = {"source": "fixture", "rows": [{"date": "2026-11-05", "close": 10}, {"date": "2026-11-06", "close": 12}]}
    data = RunData("u", "s", "r", "AAPL")
    ref = data.record("get_stock_historical_data", {"ticker": "AAPL"}, payload)
    events, model = await run(monkeypatch, "AAPL区间表现", {
        "get_stock_historical_data": tool("get_stock_historical_data", lambda _: payload),
    }, turns=[call("get_stock_historical_data", {"ticker": "AAPL"}), finish("AAPL区间上涨25%。"),
              call("analyze_dataset", {"dataset_ref": ref, "operation": "series_statistics"}), finish("AAPL区间上涨20%。")])
    assert len(model.inputs) == 4
    assert events[-1]["answer_status"] == "answered"
    assert events[-1]["response"] == "AAPL区间上涨20%。"
    assert events[-1]["metrics"]["tool_calls"] == 2


@pytest.mark.asyncio
async def test_inspect_financials_returns_latest_periods_in_descending_data():
    context = RunContext.create(owner="recovery", entry="chat", budget_seconds=30)
    async def emit(*_args):
        pass
    rt = AgentRuntime(context=context, session_id="s", query="INTC财报", model=FakeModel([]), emit=emit, tools={})
    try:
        ref = rt.data.record("get_sec_company_facts_quarterly", {"ticker": "INTC"}, {
            "source": "sec_companyfacts", "period_ends": ["2026-09-26", "2026-06-27", "2026-03-28"],
            "revenue": [16513000000, 16128000000, 10000000000], "net_income": [3320000000, -11033000000, 1],
        })
        result = rt.available_tools("root", "research_lead")["inspect_dataset"].invoke({"data_ref": ref, "limit": 2})
        assert [row["period_end"] for row in result["rows"]] == ["2026-09-26", "2026-06-27"]
        assert result["row_count"] == 3 and result["has_more"] is True
    finally:
        await rt.close()


def test_complete_episode_list_precedes_sampled_price_rows():
    episodes = [{"start": f"2026-01-{n:02}", "end": f"2026-02-{n:02}", "periods": 5, "return_pct": -.1} for n in range(1, 10)]
    result = {"rows": [{"date": f"2026-01-{i % 28 + 1:02}", "close": i + 1} for i in range(1300)],
              "episodes": episodes, "sample_count": 9, "method": {"kind": "consecutive_decline_streaks"}}
    preview = json.loads(compact_result({"result": result, "data_refs": ["dataset_input"]}, "dataset_input"))["preview"]
    assert preview["episodes"] == episodes
    assert preview["sample_count"] == 9 and preview["row_count"] == 1300
    assert preview["rows_sampled"] and len(preview["rows"]) == 2


def test_explicit_chart_cannot_pass_with_computed_table_only():
    data = RunData("u", "s", "r", "SOXX连续下跌画图")
    ref = data.record("get_stock_historical_data", {"ticker": "SOXX"}, {
        "source": "fixture", "rows": [{"date": f"2026-01-{day:02}", "close": 20-day} for day in range(1, 8)]})
    analyze_dataset(data, ref, "historical_drawdown_episodes", {"frequency": "daily", "min_periods": 5})
    check = ResearchCompleteness("SOXX连续至少5天下跌，画图", [], {})
    gaps = check.missing(data, [])
    assert gaps == [{"ticker": "SOXX", "facet": "chart", "label": "用户要求的图表"}]
    calls = check.recovery_calls(gaps, [], {"render_chart": object()}, data)
    assert calls[0][0] == "render_chart"
    assert calls[0][1]["annotations"][0]["start"] == "2026-01-02T00:00:00+00:00"


def test_missing_streak_chart_recovers_computation_before_rendering():
    data = RunData("u", "s", "r", "SOXX连续下跌画图")
    ref = data.record("get_stock_historical_data", {"ticker": "SOXX", "interval": "1wk"}, {
        "source": "fixture", "rows": [{"date": "2026-01-05", "close": 20}]})
    check = ResearchCompleteness("SOXX近25年连续至少5周下跌，画图", [], {})
    calls = check.recovery_calls(check.missing(data, []), [], {"render_chart": object(), "analyze_dataset": object()}, data)
    assert calls == [("analyze_dataset", {"dataset_ref": ref, "operation": "historical_drawdown_episodes", "parameters": {"frequency": "weekly", "min_periods": 5}})]


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


def test_latest_completed_transaction_can_be_archived_after_long_followup():
    messages = [{"role": "system", "content": "研究规则"}, {"role": "user", "content": "你去搜啊"},
        {"role": "assistant", "content": "旧回答" * 4000, "reasoning_content": "provider text " * 4000,
         "tool_calls": [{"id": "c", "function": {"name": "search", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c", "content": json.dumps({"data_refs": ["dataset_live"], "result": "真实报道" * 4000})},
        {"role": "user", "content": "请根据新取得的结果回答"}]
    compact = prune_messages(messages, [], context_window=16000, output_reserve=2000)
    assert tokens(compact) < 14000 and "dataset_live" in str(compact)
    assert not any(message.get("role") == "tool" for message in compact)


def test_explicit_readback_keeps_content_and_advances_only_returned_characters():
    original = {"data_ref": "dataset_news", "offset": 1000, "total_chars": 20000,
                "content": "报道原文" * 1800, "next_offset": 8200, "has_more": True}
    result = json.loads(compact_result({"result": original, "data_refs": ["dataset_news"]}, "dataset_news"))
    assert len(result["content"]) > 5000
    assert result["next_offset"] == 1000 + len(result["content"])
    assert result["has_more"] is True


def test_context_archive_retains_financial_values_and_citations():
    result = {"data_refs": ["dataset_sec"], "source_refs": ["S123abc"], "result": {
        "source": "sec_companyfacts", "currency": "USD", "period_ends": ["2026-09-26"],
        "revenue": [16513000000], "net_income": [3320000000],
        "fact_metadata": {"revenue": [{"audit": "x" * 20000}]}}}
    messages = [{"role": "system", "content": "研究规则"}, {"role": "user", "content": "INTC财报"},
        {"role": "assistant", "reasoning_content": "long provider context " * 2000,
         "tool_calls": [{"id": "c", "function": {"name": "get_sec_company_facts_quarterly", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c", "content": json.dumps(result)}]
    compact = prune_messages(messages, [], context_window=16000, output_reserve=2000)
    assert tokens(compact) < 14000
    assert "16513000000" in str(compact) and "3320000000" in str(compact)
    assert "S123abc" in str(compact) and "dataset_sec" in str(compact)


def test_explicit_source_footnote_can_bind_multiple_rows_of_a_table():
    data = RunData("u", "s", "r", "INTC新闻")
    one = data.record("search", {"query": "INTC first"}, {"url": "https://example.com/first", "text": "shares fell 30%"})
    two = data.record("search", {"query": "INTC second"}, {"url": "https://example.com/second", "text": "shares fell 45%"})
    table = "|报道|跌幅|\n|---|---|\n|[第一篇](https://example.com/first)|下跌30%|\n|第二篇|下跌45%|"
    note = f"两条新闻的日期与数字来源于取得的报道。[{data.source_refs(one)[0]}][{data.source_refs(two)[0]}]"
    answer, issues = verified_text(table + "\n\n" + note, data)
    assert not issues and table in answer
    _, issues = verified_text(table + "\n\n另一件事。\n\n" + note, data)
    assert "explanation_contains_unbound_number" in issues


@pytest.mark.asyncio
async def test_repeated_successful_reads_converge_to_answer_with_real_facts(monkeypatch):
    events, model = await run(monkeypatch, "查看AAPL当前价格", {
        "get_stock_price": tool("get_stock_price", lambda _: {"source": "fixture", "price": 42}),
    }, turns=[call("get_stock_price", {"ticker": "AAPL"}), call("get_stock_price", {"ticker": "AAPL"}),
              call("get_stock_price", {"ticker": "AAPL"}), finish("AAPL价格42。")])
    assert events[-1]["answer_status"] == "answered"
    assert "42" in str(model.inputs[-1])
    assert not any(message.get("tool_calls") for message in model.inputs[-1])


@pytest.mark.asyncio
async def test_final_transport_explicitly_disables_tools_without_schemas():
    async def handler(request):
        payload = json.loads(request.content)
        assert payload["tool_choice"] == "none" and "tools" not in payload
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"完整答案"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = [chunk async for chunk in ModelTransport(cfg(), client=client).stream([], [], tool_choice="none")]
    assert result[0]["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_output_length_recovery_uses_existing_facts_without_replaying_tools(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_MAX_TURNS", "2")
    truncated = [{"choices": [{"delta": {"content": "尚未写完的解释"}, "finish_reason": "length"}]}]
    events, model = await run(monkeypatch, "AAPL当前价格", {
        "get_stock_price": tool("get_stock_price", lambda _: {"source": "fixture", "price": 42}),
    }, turns=[call("get_stock_price", {"ticker": "AAPL"}), truncated, finish("AAPL价格42。")])
    assert events[-1]["answer_status"] == "answered" and events[-1]["metrics"]["tool_calls"] == 1
    assert "尚未写完" not in events[-1]["response"]
    assert len(model.inputs) == 3


@pytest.mark.asyncio
async def test_complete_financial_facts_survive_bad_model_rewording(monkeypatch):
    events, _ = await run(monkeypatch, "INTC最新季度营收、净利润、经营现金流和自由现金流是多少", {
        "get_sec_company_facts_quarterly": tool("get_sec_company_facts_quarterly", financials),
    }, turns=[call("get_sec_company_facts_quarterly", {"ticker": "INTC"}),
              finish("INTC营收999999美元。"), finish("INTC营收999999美元。")])
    done = events[-1]
    assert done["answer_status"] == "answered" and done["metrics"]["fact_fallback_used"]
    assert "| 营收 | 100 |" in done["response"] and "| 净利润 | 10 |" in done["response"]
    assert "999999" not in done["response"] and "2026-06-30" in done["response"]


@pytest.mark.asyncio
async def test_factual_fallback_does_not_replace_valuation_judgment(monkeypatch):
    events, _ = await run(monkeypatch, "INTC估值健康吗", {
        "get_company_info": tool("get_company_info", lambda _: "Forward P/E: 20.0"),
        "get_sec_company_facts_quarterly": tool("get_sec_company_facts_quarterly", financials),
    }, turns=[call("get_company_info", {"ticker": "INTC"}), call("get_sec_company_facts_quarterly", {"ticker": "INTC"}),
              finish("INTC估值99999倍。"), finish("INTC估值99999倍。")])
    assert events[-1]["answer_status"] == "partial"
    assert not events[-1]["metrics"]["fact_fallback_used"]


@pytest.mark.asyncio
async def test_incomplete_week_explanation_is_not_an_unfinished_tool_task(monkeypatch):
    events, _ = await run(monkeypatch, "AAPL当前价格", {
        "get_company_news": tool("get_company_news", lambda _: {"status": "unavailable", "error": "tool_timeout"}),
        "get_stock_price": tool("get_stock_price", lambda _: {"source": "fixture", "price": 42}),
    }, turns=[call("get_company_news", {"ticker": "AAPL"}), call("get_stock_price", {"ticker": "AAPL"}),
              finish("AAPL价格42。\n\n未完成周的处理：未完成周期不计入已经结束的历史样本。")])
    assert events[-1]["answer_status"] == "answered" and events[-1]["quality"]["state"] == "pass"


@pytest.mark.asyncio
async def test_valuation_recovery_calculates_ratios_once_and_retains_market_lineage():
    context = RunContext.create(owner="ratio-user", entry="chat", budget_seconds=90)
    context.quota_checker = lambda _: None
    async def emit(*_args):
        pass
    rt = AgentRuntime(context=context, session_id="s", query="INTC估值健康吗", model=FakeModel([]), emit=emit, tools={})
    try:
        market = rt.data.record("get_company_info", {"ticker": "INTC"}, {"forwardPE": 20, "source_url": "https://example.com/intc"})
        fields = {"revenue": [100], "gross_profit": [40], "net_income": [10], "operating_cash_flow": [12], "free_cash_flow": [8]}
        filing = rt.data.record("get_sec_company_facts_quarterly", {"ticker": "INTC"}, {
            "source": "sec_companyfacts", "source_url": "https://www.sec.gov/Archives/intc", "currency": "USD", "frequency": "quarterly", "ticker": "INTC",
            "period_ends": ["2026-09-26"], **fields,
            "fact_metadata": {key: [{"unit": "USD", "subject": "INTC", "metric": key, "value": values[0],
                "source": "sec_companyfacts", "frequency": "quarterly", "period_start": "2026-06-28", "period_end": "2026-09-26"}]
                for key, values in fields.items()}})
        assert await rt.recover_research([], "先核对估值和财报。", "draft")
        computed = next(record for record in rt.data.records.values() if record.get("inputs", {}).get("operation") == "financial_ratios")
        assert set(computed["inputs"]["dataset_refs"]) == {filing, market}
        assert not await rt.recover_research([], "数据已齐。", "draft2")
        assert rt.tool_count == 1
    finally:
        await rt.close()


def test_historical_returns_are_computed_and_do_not_bridge_missing_closes():
    original = {"data": [{"time": "2026-10-29", "close": 92.07}, {"time": "2026-10-30", "close": 65.76},
                         {"time": "2026-11-02", "close": None}, {"time": "2026-11-03", "close": 60.55}]}
    result = history_with_returns(original)
    assert result["data"][1]["period_return_pct"] == pytest.approx((65.76/92.07-1)*100)
    assert result["data"][2]["period_return_pct"] is None and result["data"][3]["period_return_pct"] is None
    assert "period_return_pct" not in original["data"][1]


def test_search_text_links_and_provider_metadata_are_clickable_sources():
    data = RunData("u", "s", "r", "INTC新闻")
    ref = data.record("search", {"query": "INTC latest"}, "Intel earnings\nhttps://www.intc.com/news-events/press-releases/detail/1\nReported results.")
    assert any(data.sources[sid].get("url") == "https://www.intc.com/news-events/press-releases/detail/1" for sid in data.source_refs(ref))
    ref = data.record("get_stock_historical_data", {"ticker": "INTC", "period": "1y", "interval": "1wk"}, {
        "source": "Yahoo", "source_url": "https://finance.yahoo.com/quote/INTC/history/", "as_of": "2026-11-06",
        "currency": "USD", "rows": [{"time": "2026-11-02", "close": 56.28}],
    })
    sources = [data.sources[sid] for sid in data.source_refs(ref)]
    assert sources and all(source.get("url") for source in sources)
    assert all(source["metadata"]["parameters"]["interval"] == "1wk" for source in sources)


def test_feedback_keeps_latest_financial_numbers_instead_of_metadata():
    data = RunData("u", "s", "r", "INTC财报")
    payload = {"source": "sec_companyfacts", "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000050863.json",
        "ticker": "INTC", "currency": "USD", "period_ends": ["2026-09-26", "2026-06-27"],
        "revenue": [16513000000, 16128000000], "net_income": [3320000000, -11033000000],
        "fact_metadata": {"revenue": [{"description": "申报元数据" * 1000}, {}]}}
    data.record("get_sec_company_facts_quarterly", {"ticker": "INTC"}, payload)
    feedback = answer_feedback("INTC最新季度营收999999亿美元。", data)
    assert feedback and "16513000000" in feedback and "3320000000" in feedback
    assert "申报元数据" not in feedback


def test_news_repair_feedback_keeps_the_actual_cause_in_long_summary():
    data = RunData("u", "s", "r", "INTC新闻")
    snippet = "Intel market background. " * 17 + "Shares fell nearly 30% after disappointing fourth-quarter guidance."
    data.record("get_company_news", {"ticker": "INTC"}, [{
        "title": "Intel outlook", "url": "https://example.com/intel", "snippet": snippet,
        "published_at": "2026-11-06", "metadata": {"audit": "x" * 20000}}])
    feedback = answer_feedback("INTC股价上涨999%。", data)
    assert feedback and "disappointing fourth-quarter guidance" in feedback
    assert "https://example.com/intel" in feedback
