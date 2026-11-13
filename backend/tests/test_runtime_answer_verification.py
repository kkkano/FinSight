"""以真实计算与来源账本验证金额、区间、交叉和图表缺失，旧正文匹配核验已退役。"""
from copy import deepcopy
import json
import pytest

from backend.agent_runtime.analysis import analyze_dataset, comparison_crossovers, render_chart
from backend.agent_runtime.data import RunData
from backend.agent_runtime.envelope import ToolError, ToolResult
from backend.tests.test_agent_runtime import call, finish
from backend.tests.test_runtime_completeness import isolated, review_pass, run, tool


@pytest.fixture
def data(tmp_path):
    value = RunData("u", "s", "r", "计算核对")
    value.storage_dir = tmp_path
    return value



def recorded(data, name, ticker, output):
    return data.record(name, {"ticker": ticker}, output, envelope=ToolResult(status="ok", kind="table", data=output,
        sources=[{"title": ticker+"原始数据", "url": f"https://example.com/{ticker}/{name}"}]))


def test_latest_two_period_computation_binds_real_difference_and_change(data):
    ref = recorded(data, "get_sec_company_facts_quarterly", "NVDA", {
        "source": "sec_companyfacts", "currency": "USD", "period_ends": ["2026-07-26", "2026-04-26", "2025-07-27"],
        "revenue": [96221000000, 81615000000, 46743000000]})
    before = deepcopy(data.records[ref])
    result = analyze_dataset(data, ref, "series_statistics", {"date": "period_end", "value": "revenue", "latest_n": 2})
    row = result["rows"][0]
    assert row["difference"] == 14606000000
    assert row["return_ratio"] == pytest.approx(96221000000 / 81615000000 - 1)
    assert row["observations"] == 2
    assert row["first"] == 81615000000 and row["last"] == 96221000000
    assert data.source_refs(result["data_refs"][0]) == data.source_refs(ref)
    assert data.source_refs(ref)
    assert data.records[ref] == before


def comparisons(data):
    refs = [recorded(data, "get_stock_historical_data", ticker, {
        "rows": [{"date": f"2026-01-0{i+1}", "close": value} for i, value in enumerate(prices)]})
        for ticker, prices in [("NVDA", [100, 110, 105]), ("AMD", [100, 105, 120])]]
    return analyze_dataset(data, refs[0], "indexed_comparison", {"other_dataset_refs": [refs[1]]})


def test_comparison_statistics_keep_path_direction_and_percentage_units(data):
    result = comparisons(data)
    stats = result["comparison_stats"]
    assert stats["observations"] == 3
    assert stats["series"]["NVDA"]["declining_periods"] == 1
    assert stats["series"]["AMD"]["declining_periods"] == 0
    assert stats["series"]["NVDA"]["end_return_pct"] == pytest.approx(5)
    assert stats["series"]["AMD"]["end_return_pct"] == pytest.approx(20)
    assert stats["strictly_increasing"] == {"NVDA": False, "AMD": True}
    assert stats["lead_days"] == {"NVDA": 1, "AMD": 1, "tie": 1}
    assert result["method"]["unit"] == "%"


def test_crossover_count_and_last_date_match_actual_native_series(data):
    result = comparisons(data)
    crossovers = result["comparison_stats"]["crossovers"]
    assert len(crossovers) == 1
    assert crossovers[0]["count"] == 1
    assert crossovers[0]["dates"][-1].startswith("2026-01-03")


def test_comparison_crossovers_can_be_recomputed_without_modifying_original_record(data):
    result = comparisons(data)
    before = deepcopy(data.records)
    assert comparison_crossovers(result["rows"], result["series"]) == result["comparison_stats"]["crossovers"]
    assert data.records == before


def test_warmup_coverage_uses_actual_missing_prefix_and_first_valid_date(data):
    rows = [{"date": f"2026-01-{i+1:02}", "close": 100+i,
             "ma20": None if i < 19 else 100+i-9.5} for i in range(23)]
    ref = recorded(data, "get_stock_historical_data", "AAPL", {"rows": rows})
    chart = render_chart(data, ref, "AAPL 20日均线", "line", "date", [{"field": "close"}, {"field": "ma20"}])
    assert chart["coverage"]["ma20"] == {"points": 23, "valid": 4, "missing": 19,
        "leading_missing": 19, "first_valid": "2026-01-20", "last_valid": "2026-01-23"}
    assert chart["coverage"]["close"]["missing"] == 0
    assert chart["data"]["rows"] == rows
    assert chart["source_refs"] == data.source_refs(ref)


def test_incomplete_chart_retains_actual_gap_and_does_not_interpolate(data):
    rows = [{"date": "2026-01-01", "close": 100}, {"date": "2026-01-02", "close": None}, {"date": "2026-01-03", "close": 110}]
    ref = recorded(data, "get_stock_historical_data", "AAPL", {"rows": rows})
    chart = render_chart(data, ref, "已有收盘价", "line", "date", [{"field": "close"}])
    assert chart["coverage"]["close"]["missing"] == 1
    assert chart["coverage"]["close"]["valid"] == 2
    assert chart["data"]["rows"][1]["close"] is None and data.rows(ref) == rows


def test_computation_inherits_all_declared_inputs_without_borrowing_unrelated_sources(data):
    primary = recorded(data, "get_sec_company_facts_quarterly", "NVDA", {"revenue": 1000, "gross_profit": 700})
    quote = recorded(data, "get_stock_price", "NVDA", {"price": 186.64})
    other = recorded(data, "get_stock_price", "AMD", {"price": 99})
    raw = {"rows": [{"gross_margin_pct": 70, "market_price": 186.64}], "method": {"code": "unrelated = 999999"}}
    derived = data.record("run_analysis_code", {"dataset_refs": [primary, quote]}, raw)
    assert data.source_refs(derived) == [*data.source_refs(primary), *data.source_refs(quote)]
    assert not set(data.source_refs(other)).intersection(data.source_refs(derived))
    assert data.records[derived]["output"] == raw
    assert data.source_refs(primary) == ["1"] and len(data.sources) == 3


@pytest.mark.asyncio
async def test_wrong_progress_does_not_poison_correct_final_answer(monkeypatch):
    tools = {"get_stock_price": tool("get_stock_price", lambda _: {"price": 42, "currency": "USD"})}
    turns = [finish("先确认，AAPL股价999美元。") + call("get_stock_price", {"ticker": "AAPL"}),
             finish("AAPL股价42美元。"), review_pass("核实AAPL当前价格")]
    events, model = await run(monkeypatch, "查AAPL价格", tools, turns=turns)
    done = events[-1]
    assert done["response"] == "AAPL股价42美元。" and done["answer_status"] == "answered"
    assert len(model.inputs) == 3 and model.turns == [] and done["metrics"]["tool_calls"] == 1
    assert any(event.get("content") == "先确认，AAPL股价999美元。" for event in events)
    review = next(event["payload"] for event in events if event["type"] == "review.finished")
    assert review["status"] == "completed" and review["verdict"] == "pass"
    review_inputs = [json.loads(message["content"]) for message in model.inputs[-1] if message["role"] == "user"]
    assert [item["answer"] for item in review_inputs if "answer" in item] == [done["response"]]


@pytest.mark.asyncio
async def test_failed_optional_tool_preserves_original_answer_and_reports_structured_failure(monkeypatch):
    failure = ToolResult(status="error", kind="news", error=ToolError(code="tool_timeout", user_message="新闻源超时", retryable=True))
    tools = {"get_company_news": tool("get_company_news", lambda _: failure),
             "get_stock_price": tool("get_stock_price", lambda _: {"price": 42, "currency": "USD"})}
    answer = "AAPL股价42美元。新闻来源本次超时，消息面仍待核实。"
    events, model = await run(monkeypatch, "查AAPL", tools, turns=[call("get_company_news", {"ticker": "AAPL"}),
        call("get_stock_price", {"ticker": "AAPL"}), finish(answer), review_pass("说明价格并披露新闻来源超时")])
    done = events[-1]
    assert done["response"] == answer and done["quality"]["state"] == "warn"
    assert done["answer_status"] == "partial"
    assert {reason["code"] for reason in done["quality"]["reasons"]} == {"partial_tool_failure"}
    assert done["metrics"]["tool_calls"] == 2
    review = next(event["payload"] for event in events if event["type"] == "review.finished")
    assert review["status"] == "completed" and review["verdict"] == "pass"
    assert len(model.inputs) == 4 and model.turns == []


@pytest.mark.asyncio
async def test_unknown_citation_marks_nonpublishable_without_changing_model_text(monkeypatch):
    answer = "数据尚需核对。[999]"
    events, _ = await run(monkeypatch, "查AAPL", {}, turns=[finish(answer)])
    done = events[-1]
    assert done["response"] == answer and done["publishable"] is False
    assert done["answer_status"] == "partial" and done["quality"]["state"] == "block"
    assert done["quality"]["reasons"] == [{"code": "unknown_citations", "severity": "warn", "source_ids": ["999"]}]
