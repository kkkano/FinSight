"""最终交付与过程草稿分离，校正有界且不绕过工具或事实校验。"""
from types import SimpleNamespace

import pytest

from backend.agent_runtime import service
from backend.agent_runtime.data import RunData
from backend.agent_runtime.model import ModelProtocolError
from backend.agent_runtime.tools import ToolSpec, schema
from backend.agent_runtime.analysis import analyze_dataset, render_chart
from backend.agent_runtime.grounding import validate_paragraph
from backend.agent_runtime.presentation import clean_public_text
from backend.services.run_context import RunContext
from backend.tests.test_agent_runtime import FakeModel, call, cfg, finish


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FINSIGHT_ACTION_STORE", str(tmp_path / "actions.sqlite"))
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("FINSIGHT_RUNTIME_QUOTA_DB", str(tmp_path / "quota.sqlite"))
    monkeypatch.setenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")


def quote_tool():
    return ToolSpec("get_stock_price", "取得真实报价",
        schema({"ticker": {"type": "string"}}, ["ticker"]),
        lambda _: {"price": 42, "currency": "USD", "source": "fixture", "as_of": "2026-11-06"}, True)


async def pipeline(monkeypatch, turns, tools=None, **options):
    model = turns if isinstance(turns, FakeModel) else FakeModel(turns)
    monkeypatch.setattr(service, "resolve_model", cfg)
    monkeypatch.setattr(service, "ModelTransport", lambda _: model)
    real_runtime = service.AgentRuntime
    monkeypatch.setattr(service, "AgentRuntime", lambda **kwargs: real_runtime(**kwargs,
        tools=tools or {"get_stock_price": quote_tool()}))
    context = RunContext.create(owner="verification-user", entry="chat", budget_seconds=20)
    context.quota_checker = lambda _: None
    async def archive():
        pass
    context.archive_usage = archive
    deps = SimpleNamespace(schedule_report_index=lambda **_: True,
        update_session_context=lambda **_: None, persist_run_event=None)
    events = [event async for event in service.run_agent_pipeline(deps=deps, query="查AAPL价格",
        thread_id="verification-session", run_id=context.run_id, run_context=context, **options)]
    return events, model


@pytest.mark.asyncio
async def test_wrong_progress_does_not_poison_correct_final_answer(monkeypatch):
    events, model = await pipeline(monkeypatch, [finish("先确认，AAPL股价999美元。") +
        call("get_stock_price", {"ticker": "AAPL"}), finish("AAPL股价42美元。")])
    done = events[-1]
    assert done["type"] == "done" and done["answer_status"] == "answered"
    assert done["quality"]["state"] == "pass" and done["response"] == "AAPL股价42美元。"
    assert len(model.inputs) == 2
    blocks = [block for block in done["blocks"] if block["kind"] == "text"]
    assert blocks[0]["content"] == "" and blocks[0]["content_phase"] == "progress"
    assert blocks[0]["validation_issues"] == ["explanation_contains_unbound_number"]
    assert blocks[-1]["content_phase"] == "answer" and blocks[-1]["content"] == done["response"]
    assert "已撤回" not in str(done)


@pytest.mark.asyncio
async def test_final_answer_gets_one_tool_free_repair_with_same_identity(monkeypatch):
    events, model = await pipeline(monkeypatch, [call("get_stock_price", {"ticker": "AAPL"}),
        finish("AAPL股价999美元。"), finish("AAPL股价42美元。")])
    done = events[-1]
    assert done["answer_status"] == "answered" and done["quality"]["state"] == "pass"
    assert done["metrics"]["answer_repair_attempted"] is True
    assert len(model.inputs) == 3 and "需核对的段落" in model.inputs[-1][-1]["content"]
    assert done["response"] == "AAPL股价42美元。"
    assert "999" not in str(done["blocks"])
    assert any(event.get("payload", {}).get("activity_id") == "answer_check" for event in events)
    numbered = [event for event in events if "seq" in event]
    assert len({event["seq"] for event in numbered}) == len(numbered)
    assert {event["run_id"] for event in numbered} == {done["run_id"]}


@pytest.mark.asyncio
async def test_failed_repair_keeps_verified_paragraphs_and_one_gap(monkeypatch):
    invalid = "AAPL股价42美元。\n\n涨幅999%。\n\n后续还会涨777%。"
    events, model = await pipeline(monkeypatch, [call("get_stock_price", {"ticker": "AAPL"}),
        finish(invalid), finish(invalid)])
    done = events[-1]
    assert len(model.inputs) == 3
    assert done["answer_status"] == "partial" and done["quality"]["state"] == "block"
    assert done["response"] == "AAPL股价42美元。\n\n部分结论还缺少可靠依据，暂时无法确认。"
    assert done["response"].count("暂时无法确认") == 1 and "已撤回" not in str(done)
    assert "999" not in str(done["blocks"]) and "777" not in str(done["blocks"])
    assert len(done["quality"]["reasons"]) == 1


@pytest.mark.asyncio
async def test_repair_cannot_execute_supplier_tool_calls(monkeypatch):
    invoked = []
    tool = quote_tool()
    original = tool.invoke
    tool.invoke = lambda args: (invoked.append(args), original(args))[1]
    events, _ = await pipeline(monkeypatch, [call("get_stock_price", {"ticker": "AAPL"}),
        finish("AAPL股价999美元。"), call("get_stock_price", {"ticker": "NVDA"}) + finish("股价777美元。")],
        {"get_stock_price": tool})
    assert invoked == [{"ticker": "AAPL"}]
    assert events[-1]["answer_status"] == "partial"
    assert events[-1]["metrics"]["tool_calls"] == 1


@pytest.mark.asyncio
async def test_repair_transport_failure_keeps_original_verified_results(monkeypatch):
    class InterruptedRepair(FakeModel):
        async def stream(self, messages, tools, **kwargs):
            if len(self.inputs) == 2:
                self.inputs.append(messages)
                yield {"choices": [{"delta": {"content": "半截校正报价888美元"}, "finish_reason": None}]}
                raise ModelProtocolError("model_incomplete_stream")
            async for chunk in super().stream(messages, tools, **kwargs):
                yield chunk
    model = InterruptedRepair([call("get_stock_price", {"ticker": "AAPL"}),
        finish("AAPL股价42美元。\n\n预计上涨999%。")])
    events, _ = await pipeline(monkeypatch, model)
    done = events[-1]
    assert done["type"] == "done" and done["answer_status"] == "partial"
    assert "股价42美元" in done["response"] and "888" not in str(done["blocks"])
    assert any(event.get("payload", {}).get("activity_id") == "answer_check" and
        event["payload"].get("status") == "failed" for event in events)


@pytest.mark.asyncio
async def test_optional_failed_tool_is_process_history_not_delivery_gap(monkeypatch):
    news = ToolSpec("get_company_news", "获取新闻", schema({"ticker": {"type": "string"}}, ["ticker"]),
        lambda _: {"status": "unavailable", "error": "tool_timeout", "summary": "新闻源超时"}, True)
    events, _ = await pipeline(monkeypatch, [call("get_company_news", {"ticker": "AAPL"}),
        call("get_stock_price", {"ticker": "AAPL"}), finish("AAPL股价42美元。")],
        {"get_company_news": news, "get_stock_price": quote_tool()})
    done = events[-1]
    assert any(event.get("runtime_type") == "tool.failed" for event in events)
    assert done["answer_status"] == "answered" and done["quality"]["state"] == "pass"


@pytest.mark.asyncio
async def test_actual_declared_tool_gap_still_marks_partial(monkeypatch):
    news = ToolSpec("get_company_news", "获取新闻", schema({"ticker": {"type": "string"}}, ["ticker"]),
        lambda _: {"status": "unavailable", "error": "tool_timeout", "summary": "新闻源超时"}, True)
    events, _ = await pipeline(monkeypatch, [call("get_company_news", {"ticker": "AAPL"}),
        call("get_stock_price", {"ticker": "AAPL"}), finish("AAPL股价42美元。\n\n本轮未能获取新闻。")],
        {"get_company_news": news, "get_stock_price": quote_tool()})
    done = events[-1]
    assert done["answer_status"] == "partial" and done["quality"]["state"] == "warn"
    assert done["quality"]["reasons"][0]["code"] == "partial_tool_failure"


@pytest.mark.asyncio
async def test_invalid_draft_citation_does_not_block_correct_answer(monkeypatch):
    events, _ = await pipeline(monkeypatch, [finish("先看这里 https://invented.example/aapl 。") +
        call("get_stock_price", {"ticker": "AAPL"}), finish("AAPL股价42美元。")])
    done = events[-1]
    assert done["answer_status"] == "answered" and "invented.example" not in str(done["blocks"])


def test_unverified_metadata_cannot_hide_inside_unit_bullet():
    data = RunData("u", "s", "r", "AAPL")
    data.record("get_stock_historical_data", {"ticker": "AAPL"}, {"source": "fixture",
        "price_basis": None, "dividends_included": None, "rows": [{"date": "2026-11-06", "close": 42}]})
    text = "- 单位：美元，价格为未复权原始收盘价。"
    assert service.paragraph_issues(text, data) == ["explanation_adjustment_unverified"]


def test_error_paragraph_is_not_salvaged_from_unrelated_numeric_matches():
    data = RunData("u", "s", "r", "走势")
    data.record("get_stock_price", {"ticker": "AAPL"}, {"source": "fixture", "price": 42})
    text = "上涨999%。\n- 在42个区间中全部出现V型修复。"
    safe, issues = service.verified_text(text, data)
    assert safe == "" and issues == ["explanation_contains_unbound_number"]


def test_missing_evidence_does_not_approve_closed_book_market_numbers():
    data = RunData("u", "s", "r", "报价")
    assert service.paragraph_issues("AAPL股价999美元。", data) == ["missing_factual_evidence"]
    assert service.paragraph_issues("假设股价为999美元，下面只解释计算方法。", data) == []


@pytest.mark.parametrize("text", ["行情延迟约1.7天。", "数据截止昨日（约1.7天延迟）。"])
def test_data_age_does_not_verify_provider_delay_in_either_word_order(text):
    data = RunData("u", "s", "r", "报价")
    data.record("get_stock_price", {"ticker": "AAPL"}, {"source": "fixture", "price": 1.7,
        "freshness_seconds": 146880})
    assert service.paragraph_issues(text, data) == ["explanation_delivery_delay_unverified"]


@pytest.mark.asyncio
async def test_repair_is_bounded_even_at_last_research_turn(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_MAX_TURNS", "2")
    events, model = await pipeline(monkeypatch, [call("get_stock_price", {"ticker": "AAPL"}),
        finish("AAPL股价999美元。"), finish("AAPL股价888美元。")])
    assert len(model.inputs) == 3
    assert events[-1]["type"] == "done" and events[-1]["answer_status"] == "partial"


@pytest.mark.asyncio
async def test_empty_repair_does_not_discard_verified_original_result(monkeypatch):
    events, _ = await pipeline(monkeypatch, [call("get_stock_price", {"ticker": "AAPL"}),
        finish("AAPL股价42美元。\n\n预计上涨999%。"), call("get_stock_price", {"ticker": "NVDA"})])
    done = events[-1]
    assert done["type"] == "done" and done["answer_status"] == "partial"
    assert "股价42美元" in done["response"] and "999" not in done["response"]


@pytest.mark.asyncio
async def test_data_basis_caveat_does_not_turn_optional_news_failure_into_gap(monkeypatch):
    news = ToolSpec("get_company_news", "获取新闻", schema({"ticker": {"type": "string"}}, ["ticker"]),
        lambda _: {"status": "unavailable", "error": "tool_timeout", "summary": "新闻源超时"}, True)
    events, _ = await pipeline(monkeypatch, [call("get_company_news", {"ticker": "AAPL"}),
        call("get_stock_price", {"ticker": "AAPL"}), finish("AAPL股价42美元。\n\n复权与股息处理口径无法确认。")],
        {"get_company_news": news, "get_stock_price": quote_tool()})
    assert events[-1]["answer_status"] == "answered"


@pytest.mark.parametrize("claim", ["AAPL下跌 $1.80，跌幅0.52%。", "AAPL下降1.80美元。", "AAPL减少1.80 USD。", "AAPL下跌 **$1.80**。", "AAPL跌 $1.80。"])
def test_negative_change_supports_positive_magnitude_with_decline_direction(claim):
    data=RunData("u","s","r","AAPL")
    data.record("get_stock_price",{"ticker":"AAPL"},{"source":"fixture","price":342.37,"change":-1.8,"change_percent":"-0.52%","currency":"USD"})
    assert validate_paragraph(claim,data)==[]


@pytest.mark.parametrize("claim", ["AAPL上涨1.80美元。", "AAPL下跌+1.80美元。", "AAPL上涨-1.80美元。"])
def test_wrong_direction_is_not_approved_by_absolute_value_match(claim):
    data=RunData("u","s","r","AAPL")
    data.record("get_stock_price",{"ticker":"AAPL"},{"source":"fixture","price":342.37,"change":-1.8,"currency":"USD"})
    assert validate_paragraph(claim,data)


def test_direction_normalization_does_not_change_destination_price_or_period_count():
    data=RunData("u","s","r","AAPL")
    data.record("get_stock_price",{"ticker":"AAPL"},{"source":"fixture","price":1.8,"periods":5,"currency":"USD"})
    assert validate_paragraph("AAPL下跌至1.80美元，连续下跌5周。",data)==[]


@pytest.mark.parametrize("source_id", ["S1","Sdbf67a99636931dade","SABCDEF123456789012345678"])
def test_unknown_reference_length_does_not_hide_invalid_citation(source_id):
    data=RunData("u","s","r","AAPL")
    data.record("get_stock_price",{"ticker":"AAPL"},{"source":"fixture","price":42})
    assert "unverified_citation" in service.paragraph_issues(f"AAPL股价42。[{source_id}]",data)


def test_real_source_url_in_chinese_markdown_parenthesis_is_not_rejected():
    data=RunData("u","s","r","NVDA")
    url="https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json"
    data.record("get_sec_company_facts_quarterly",{"ticker":"NVDA"},{"source":"sec_companyfacts","source_url":url,"revenue":42})
    assert service.paragraph_issues(f"NVDA营收42（[SEC companyfacts]({url})）。",data)==[]
    assert service.paragraph_issues(f"NVDA营收42（[SEC]({url})）。",data)==[]
    assert service.paragraph_issues(f"NVDA营收42（[SEC] ({url})）。",data)==[]
    assert service.paragraph_issues("NVDA营收42（[SEC](https://invented.example/facts)）。",data)==["unverified_citation"]
    sid=data.source_refs(next(iter(data.records)))[0]
    assert service.paragraph_issues(f"来源：{url}（[{sid}]）。",data)==[]
    assert "unverified_citation" in service.paragraph_issues(f"来源：{url}/invented。",data)
    assert "unverified_citation" in service.paragraph_issues(f"来源：{url}.invented。",data)


def test_repair_feedback_projects_related_successful_results_not_other_subjects():
    data=RunData("u","s","r","AAPL")
    aapl=data.record("get_stock_historical_data",{"ticker":"AAPL"},{"source":"fixture","rows":[{"date":"2026-10-01","close":100},{"date":"2026-11-06","close":125}]})
    amd=data.record("get_stock_historical_data",{"ticker":"AMD"},{"source":"fixture","rows":[{"date":"2026-10-01","close":100},{"date":"2026-11-06","close":180}]})
    analyze_dataset(data,aapl,"series_statistics");analyze_dataset(data,amd,"series_statistics")
    sid=data.source_refs(aapl)[0]
    feedback=service.answer_feedback(f"AAPL区间涨幅999%。[{sid}]",data)
    assert "25.00%" in feedback and sid in feedback and "AMD" not in feedback
    assert "run_analysis_code" not in feedback and "source_id" in feedback


def test_successful_python_result_can_bind_original_sources_without_exposing_code_numbers():
    data=RunData("u","s","r","均值")
    original=data.record("get_stock_historical_data",{"ticker":"AAPL"},{"source":"fixture","rows":[{"date":"2026-10-01","close":100},{"date":"2026-11-06","close":125}]})
    data.record("run_analysis_code",{"dataset_refs":[original]},{"mean":112.5,"method":{"kind":"derived","code":"unrelated=999999"}})
    sid=data.source_refs(original)[0]
    assert validate_paragraph(f"AAPL平均收盘价112.5。[{sid}]",data)==[]
    assert validate_paragraph(f"AAPL平均收盘价999999。[{sid}]",data)==["explanation_contains_unbound_number"]


def test_latest_two_period_computation_binds_real_difference_and_change():
    data=RunData("u","s","r","营收变化")
    ref=data.record("get_sec_company_facts_quarterly",{"ticker":"NVDA"},{"source":"sec_companyfacts","currency":"USD",
        "periods":["2026-07-26","2026-04-26","2025-07-27"],"period_ends":["2026-07-26","2026-04-26","2025-07-27"],"revenue":[96221000000,81615000000,46743000000]})
    analyze_dataset(data,ref,"series_statistics",{"date":"period_end","value":"revenue","latest_n":2})
    sid=data.source_refs(ref)[0]
    assert validate_paragraph(f"NVDA营收增加146.06亿美元，环比增长17.90%。[{sid}]",data)==[]
    assert validate_paragraph(f"NVDA营收增加146.06亿美元，环比增长25%。[{sid}]",data)


def comparisons():
    data=RunData("u","s","r","比较")
    refs=[]
    for ticker,prices in [("NVDA",[100,110,105]),("AMD",[100,105,120])]:
        refs.append(data.record("get_stock_historical_data",{"ticker":ticker},{"source":"fixture","rows":[{"date":f"2026-01-0{i+1}","close":value} for i,value in enumerate(prices)]}))
    analyze_dataset(data,refs[0],"indexed_comparison",{"other_dataset_refs":[refs[1]]})
    return data


@pytest.mark.parametrize("claim", ["AMD始终领先NVDA。","NVDA从未反超AMD。","AMD领先关系全年保持，未出现NVDA累计涨幅反超AMD。","NVDA累计涨幅持续向上。"])
def test_absolute_path_claims_check_actual_comparison_statistics(claim):
    assert validate_paragraph(claim,comparisons())==["explanation_comparison_path_mismatch"]


@pytest.mark.parametrize("claim", ["AMD期末涨幅较高。","NVDA未呈现持续上行。","不能断言AMD始终领先NVDA。","AMD累计涨幅持续向上。"])
def test_qualified_or_supported_comparison_claims_are_preserved(claim):
    assert validate_paragraph(claim,comparisons())==[]


def test_algorithm_window_counts_are_definition_but_market_percentages_still_need_evidence():
    data=RunData("u","s","r","均线怎么算")
    text="用rolling(20).mean()计算，每个点取20个收盘价。前面19个点为空，20指20个交易日而非20个日历日。"
    assert validate_paragraph(text,data)==[]
    assert validate_paragraph(text+"股票上涨20%。",data)==["missing_factual_evidence"]
    assert validate_paragraph("股票平均收盘价20美元。用rolling(20).mean()计算。",data)==["missing_factual_evidence"]


def test_repair_heading_is_removed_from_public_answer_only():
    assert clean_public_text("核对后的段落：\n\n计算方法如下。") == "计算方法如下。"
    assert clean_public_text("以下修正后的结论仅基于价格资料：") == "以下结论仅基于价格资料："
    assert clean_public_text("```python\nprint('核对后的段落：')\n```") == "```python\nprint('核对后的段落：')\n```"
    assert clean_public_text("这条数据 session 为 regular_close，Time precision: date。") == "这条数据 常规时段收盘，时间仅精确到日期。"
    assert clean_public_text("引用详情含 source_id 和 data_ref。") == "引用详情含 引用来源 和 资料引用。"
    assert clean_public_text("```json\n{\"session\":\"regular_close\"}\n```") == "```json\n{\"session\":\"regular_close\"}\n```"


def incomplete_average_chart():
    data=RunData("u","s","r","AAPL")
    rows=[{"date":f"2026-01-{i+1:02d}","close":100+i,"ma20":None if i<19 else 100+i-9.5} for i in range(23)]
    original=data.record("get_stock_historical_data",{"ticker":"AAPL"},{"source":"fixture","rows":[{k:v for k,v in row.items() if k!='ma20'} for row in rows]})
    computed=data.record("run_analysis_code",{"dataset_refs":[original]},{"rows":rows})
    render_chart(data,computed,"AAPL一个月与20日均线","line","date",[{"field":"close","name":"收盘价"},{"field":"ma20","name":"20日均线"}])
    return data


def test_warmup_claim_uses_actual_missing_prefix_not_any_matching_number():
    data=incomplete_average_chart()
    assert validate_paragraph("20日均线前3天无法计算。",data)==["explanation_chart_coverage_mismatch"]
    assert validate_paragraph("20日均线前19天为空。",data)==[]
    assert validate_paragraph("20日均线从2026-01-20开始有值。",data)==[]
    assert validate_paragraph("20日均线从2026-01-12开始有值。",data)==["explanation_chart_coverage_mismatch"]


def test_prior_chart_coverage_is_checked_without_republishing_chart():
    data=incomplete_average_chart();artifact=data.artifacts[0]
    data.prior_artifacts=[{k:artifact[k] for k in ['title','dataset_refs','source_refs','spec','coverage']}]
    data.artifacts=[]
    assert validate_paragraph("20日均线前3天无法计算。",data)==["explanation_chart_coverage_mismatch"]
    feedback=service.answer_feedback("AAPL20日均线前3天无法计算。",data)
    assert 'leading_missing' in feedback and '19' in feedback and not data.artifacts
    data.prior_artifacts[0].pop('coverage')
    assert validate_paragraph("20日均线最早3个交易日为空。",data)==["explanation_chart_coverage_mismatch"]


def test_explicit_percent_series_unit_is_grounded_without_scaling_counts():
    data=comparisons()
    assert validate_paragraph("AMD区间最高涨幅20%。",data)==[]
    assert validate_paragraph("AMD区间最高涨幅−20%。",data)
    assert validate_paragraph("AMD区间涨幅300%。",data)


def test_neutral_change_label_does_not_turn_positive_change_into_decline():
    data=RunData("u","s","r","AAPL")
    data.record("get_stock_price",{"ticker":"AAPL"},{"source":"fixture","change":"+1.80%","currency":"USD"})
    assert validate_paragraph("AAPL涨跌幅+1.80%。",data)==[]


def test_percent_unit_applies_to_values_not_observation_counts():
    data=RunData("u","s","r","宏观")
    data.record("get_fred_data",{}, {"source":"fixture","unit":"Percent","observations":3,"rows":[{"date":"2026-01-01","value":5.25}]})
    assert validate_paragraph("利率5.25%。",data)==[]
    assert validate_paragraph("利率300%。",data)==["explanation_contains_unbound_number"]


@pytest.mark.parametrize("claim", ["AAPL的实时报价数据包已取得。", "这是AAPL实时行情。"])
def test_formatted_daily_close_is_not_realtime_even_if_provider_is_fast(claim):
    data=RunData("u","s","r","AAPL")
    data.record("get_stock_price",{"ticker":"AAPL"},"AAPL Current Price: $342.37 | Session: regular_close | Time precision: date | Price basis: unknown | Dividends included: unknown | Currency: USD")
    assert validate_paragraph(claim,data)==["explanation_realtime_unverified"]


@pytest.mark.parametrize("claim", ["AAPL这条收盘价不代表实时行情。", "没有AAPL实时逐笔数据。", "AAPL无法取得实时暗盘净流入。"])
def test_honest_realtime_limitations_are_preserved(claim):
    data=RunData("u","s","r","AAPL")
    data.record("get_stock_price",{"ticker":"AAPL"},"AAPL Current Price: $342.37 | Session: regular_close | Time precision: date")
    assert validate_paragraph(claim,data)==[]


def test_explicit_realtime_provider_flag_supports_realtime_claim():
    data=RunData("u","s","r","AAPL")
    data.record("get_stock_price",{"ticker":"AAPL"},{"source":"fixture","is_realtime":True})
    assert validate_paragraph("AAPL这条是实时行情。",data)==[]


def test_crossover_count_and_last_date_match_actual_native_series():
    data=comparisons()
    assert validate_paragraph("NVDA和AMD两条曲线共交叉1次，最后一次交叉在2026-01-03。",data)==[]
    assert validate_paragraph("NVDA和AMD两条曲线共交叉2次。",data)==["explanation_crossover_mismatch"]
    assert validate_paragraph("最后一次交叉在2026-01-02。",data)==["explanation_crossover_mismatch"]


def test_legacy_comparison_rechecks_crossovers_without_modifying_original_record():
    from copy import deepcopy
    data=comparisons()
    native=next(record for record in data.records.values() if record['tool']=='analyze_dataset')
    native['output']['comparison_stats'].pop('crossovers')
    original=deepcopy(data.records)
    assert validate_paragraph("两条曲线交叉3次。",data)==["explanation_crossover_mismatch"]
    feedback=service.answer_feedback("NVDA和AMD两条曲线交叉3次。",data)
    assert 'crossovers' in feedback and data.records==original


def test_repair_feedback_has_utf8_cap_and_keeps_verified_crossover_facts():
    from backend.agent_runtime.context import tokens
    data=comparisons()
    for i in range(10):
        data.record('fixture',{'ticker':'NVDA'},{'source':'fixture','summary':'很长的历史资料'*600,'value':i})
    text='NVDA和AMD两条曲线交叉3次。\n\n'+'\n\n'.join('说明'+('未经计算的内容'*500)+str(99900+i)+'美元。' for i in range(6))
    feedback=service.answer_feedback(text,data)
    assert tokens(feedback)<=service.MAX_REPAIR_FEEDBACK_BYTES
    assert 'crossovers' in feedback and '2026-01-03' in feedback


def period_statistics():
    data=RunData('u','s','r','NVDA营收')
    ref=data.record('get_sec_company_facts_quarterly',{'ticker':'NVDA'},{'source':'sec_companyfacts','currency':'USD',
        'periods':['2026-07-26','2026-04-26'],'period_ends':['2026-07-26','2026-04-26'],'revenue':[96221000000,81615000000]})
    analyze_dataset(data,ref,'series_statistics',{'value':'revenue','date':'period_end','latest_n':2})
    return data


@pytest.mark.parametrize('claim',['NVDA最新两个已公布财季的营收均为增长。','NVDA两期收入均增长。'])
def test_two_observations_do_not_prove_each_period_grew(claim):
    assert validate_paragraph(claim,period_statistics())==['explanation_period_trend_unverified']


@pytest.mark.parametrize('claim',['NVDA这两期相比，后一期营收更高。','不能断言NVDA两个财季营收均增长。','NVDA两期毛利和营收均增长。'])
def test_period_contract_does_not_change_distinct_metric_or_qualified_statements(claim):
    assert validate_paragraph(claim,period_statistics())==[]


@pytest.mark.asyncio
async def test_incomplete_chart_has_partial_state_with_real_gap(monkeypatch):
    data=RunData("u","s","r","AAPL")
    output={"source":"fixture","rows":[{"date":"2026-01-01","close":100},{"date":"2026-01-02","close":None},{"date":"2026-01-03","close":110}]}
    ref=data.record("get_stock_historical_data",{"ticker":"AAPL"},output)
    tool=ToolSpec("get_stock_historical_data","行情",schema({"ticker":{"type":"string"}},["ticker"]),lambda _:output,True)
    events,_=await pipeline(monkeypatch,[call("get_stock_historical_data",{"ticker":"AAPL"}),
        call("render_chart",{"dataset_ref":ref,"title":"已有收盘价","chart_type":"line","x":"date","series":[{"field":"close","name":"收盘价"}]}),
        finish("图展示已有收盘价，部分数据缺失。")],{"get_stock_historical_data":tool})
    done=events[-1]
    assert done["answer_status"]=="partial" and done["quality"]["state"]=="warn"
    assert any(reason["code"]=="partial_chart_data" for reason in done["quality"]["reasons"])
