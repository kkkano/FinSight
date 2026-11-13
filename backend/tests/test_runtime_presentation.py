"""统一信封展示、模型原文投影、思考限长与准确历史区间。"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import pytest

from backend.agent_runtime.presentation import message_blocks
from backend.agent_runtime.diagnostics import display_tool
from backend.agent_runtime.registry import financial_tools
from backend.agent_runtime.adapters import ADAPTERS, TOOL_KINDS, adapt_result
from backend.agent_runtime.envelope import to_ui
from backend.agent_runtime.data import RunData
from backend.agent_runtime.analysis import analyze_dataset
from backend.services.market_history_view import clip_history_period
from backend.tests.test_agent_runtime import runtime, finish


@pytest.mark.parametrize("name", sorted(TOOL_KINDS))
def test_every_registered_tool_has_typed_target_and_result(name):
    args = {"ticker": "AAPL", "query": "AAPL earnings", "title": "股价走势", "role": "technical_agent", "task": "核对均线与风险",
            "chart_type": "line", "series": [{"field": "close"}], "period": "1y", "interval": "1d"}
    output = {"status": "ok", "rows": [{"time": "2026-01-02", "close": 100}, {"time": "2026-11-06", "close": 110}],
              "_artifact": {"data": {"rows": [{"date": "2026-11-06", "close": 110}]}}, "summary": "已完成本次计算"}
    assert display_tool(name, args)["target"]
    rendered = display_tool(name, args, output)
    assert rendered["kind"] == TOOL_KINDS[name] and rendered["status"] == "ok"
    assert all(isinstance(rendered[key], str) and rendered[key] for key in ("target", "result", "title"))


def test_all_actual_financial_and_native_tools_require_registered_display(tmp_path):
    tools = financial_tools()
    rt, _ = runtime(tmp_path, [finish()], tools)
    assert set(tools) <= ADAPTERS.keys()
    assert set(rt.registry.available("root", "research_lead")) <= ADAPTERS.keys()
    with pytest.raises(ValueError, match="tool_adapter_not_registered"):
        display_tool("unimplemented_tool", {})


def test_history_and_quote_rows_display_actual_values():
    rows = [{"time": "2025-11-07", "close": 228.4}, {"time": "2026-11-06", "close": 231.1}]
    history = display_tool("get_stock_historical_data", {"ticker": "AAPL", "interval": "1d"}, {"kline_data": rows})
    assert history["target"] == "AAPL" and history["rows"] == rows and history["row_count"] == 2
    raw = {"price": 56.28, "change": 4.03, "change_percent": 7.71, "as_of": "2026-11-06", "currency": "USD"}
    envelope = adapt_result("get_stock_price", raw)
    row = to_ui(envelope, "get_stock_price", {"ticker": "INTC"})
    assert "56.28 USD" in row["result"] and row["as_of"] == "2026-11-06"
    assert {"label": "涨跌幅", "value": 7.71} in row["key_facts"] and envelope.data == raw


def test_text_projection_preserves_model_words_citations_urls_and_code():
    text = "AAPL支撑位330美元。[1] dataset_abcdef h_1234\n原始链接 https://example.test/dataset_abcdef\n```python\nload('dataset_abcdef')\n```\n<｜DSML｜ calls>"
    block = {"id": "original", "kind": "text", "content": text}
    assert message_blocks([block]) == [block]
    assert block["content"] == text


@pytest.mark.asyncio
async def test_provider_reasoning_default_and_shared_run_cap(tmp_path):
    first = [{"choices": [{"delta": {"reasoning_content": "甲" * 15000}, "finish_reason": None}]}] + finish("主回复")
    second = [{"choices": [{"delta": {"reasoning_content": "乙" * 15000}, "finish_reason": None}]}] + finish("专业回复")
    rt, events = runtime(tmp_path, [first, second])
    await rt.run_agent("root", "research_lead", "问题")
    await rt.run_agent("child", "technical_agent", "核对走势")
    deltas = [payload for kind, payload, _ in events if kind == "reasoning.delta"]
    assert sum(len(item["delta"]) for item in deltas) == 20000
    assert "甲" not in rt.root_content and "乙" not in json.dumps(rt.data.snapshot())
    await rt.close()


def test_message_reasoning_cap_is_defended_at_persistence_boundary():
    blocks = [{"id": str(i), "kind": "reasoning", "reasoning_kind": "provider_raw", "content": "x" * 15000} for i in range(2)]
    original = deepcopy(blocks)
    safe = message_blocks(blocks)
    assert sum(len(block["content"]) for block in safe) == 20000
    assert safe[-1]["truncated"] and blocks == original
    assert message_blocks([{"id": "hidden", "kind": "private_internal", "content": "hidden"}]) == []




def test_one_year_is_calendar_range_not_367_trading_bars():
    payload = {"asset": {"timezone": "America/New_York"}, "kline_data": [
        {"time": "2025-05-01", "close": 1}, {"time": "2025-11-07", "close": 2}, {"time": "2026-11-06", "close": 3}]}
    original = deepcopy(payload)
    result = clip_history_period(payload, "1y", now=datetime(2026, 11, 7, 18, tzinfo=timezone.utc))
    assert len(result["kline_data"]) == 2 and result["requested_start"] == "2025-11-07"
    assert payload == original


def test_multi_ticker_return_comparison_uses_common_baseline():
    data = RunData("test", "test", "test", "比较")
    refs = [data.record("get_stock_historical_data", {"ticker": ticker}, {"source_url": f"https://example.test/history/{ticker}", "currency": "USD", "price_basis": "split_adjusted_close", "dividends_included": False,
        "rows": [{"time": "2025-12-31", "close": start}, {"time": "2026-11-06", "close": end}]}) for ticker, start, end in [("NVDA", 100, 125), ("AMD", 200, 180)]]
    result = analyze_dataset(data, refs[0], "indexed_comparison", {"other_dataset_refs": [refs[1]]})
    assert result["rows"][-1]["series_1"] == 25
    assert result["rows"][-1]["series_2"] == pytest.approx(-10)
    assert result["method"]["baseline_date"] == "2025-12-31"
    assert len(data.source_refs(result["data_refs"][0])) >= 2


def test_unknown_calculation_parameters_are_rejected_not_silently_reinterpreted():
    data = RunData("test", "test", "test", "图表")
    ref = data.record("get_stock_historical_data", {"ticker": "AAPL"}, {"rows": [
        {"time": "2026-01-02", "close": 100}, {"time": "2026-11-06", "close": 125}]})
    result = analyze_dataset(data, ref, "historical_drawdown_episodes", {"field": "close", "min_drawdown_pct": 5})
    assert result["status"] == "unavailable" and result["error"] == "analysis_parameters_invalid"
    assert "min_drawdown_pct" in result["summary"]
    stats = analyze_dataset(data, ref, "series_statistics")
    assert stats["rows"][0]["return_ratio"] == .25
    assert "25.00%" in stats["summary"]






def test_source_projection_keeps_reference_not_entire_market_table():
    data = RunData("test", "test", "test", "走势")
    rows = [{"date": str(i), "close": i + 1} for i in range(2000)]
    ref = data.record("get_stock_historical_data", {"ticker": "AAPL"}, {"source": "yfinance", "source_url": "https://example.com/aapl", "kline_data": rows, "data": rows})
    assert data.records[ref]["output"]["kline_data"] == rows
    assert all("kline_data" not in source and "data" not in source for source in data.sources.values())
    assert len(json.dumps(data.sources)) < 6000










def test_date_only_window_contains_end_and_previous_close_baseline():
    from backend.agent_runtime.analysis import render_chart
    data = RunData("test", "test", "test", "连续下跌")
    rows = [{"date": f"2026-01-{day:02d}T00:00:00+00:00", "close": 100-day} for day in range(1, 7)]
    ref = data.record("analyze_dataset", {}, {"rows": rows, "method": {"kind": "consecutive_decline_streaks"}})
    artifact = render_chart(data, ref, "区间", "line_with_event_windows", "date", [{"field": "close"}],
        annotations=[{"start": "2026-01-02", "end": "2026-01-06", "label": "5期"}])
    assert artifact["spec"]["annotations"][0]["end"] == rows[-1]["date"]
    panel = artifact["data"]["panels"][0]
    assert panel["rows"] == rows and panel["baseline_included"] and panel["periods"] == 5
