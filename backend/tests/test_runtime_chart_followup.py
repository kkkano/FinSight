"""已有行情的自然语言绘图追问必须生成图卡，补充计算失败不能吞掉绘图需求。"""
import pytest
from types import SimpleNamespace

from backend.agent_runtime.completeness import ResearchCompleteness
from backend.agent_runtime.data import RunData
from backend.tests.test_agent_runtime import runtime, finish


def test_context_estimate_counts_tokens_offline_instead_of_utf8_bytes(monkeypatch):
    from backend.agent_runtime.context import _tokenizer, tokens
    import socket

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("分词估算不应联网")

    monkeypatch.setattr(socket, "create_connection", forbid_network)
    _tokenizer.cache_clear()
    text = "英特尔的营业利润与现金流需要使用实际披露数据核验。" * 100
    assert len(text) // 3 < tokens(text) < len(text.encode("utf-8")) * .75


@pytest.mark.parametrize("query", ["画个图给我解释一下", "画一张图", "画张图看看", "画图解释"])
def test_natural_chart_request_can_recover_from_existing_history(query, tmp_path, monkeypatch):
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path))
    data = RunData("u", "s", "r", query)
    ref = data.record("get_stock_historical_data", {"ticker": "INTC", "period": "1y", "interval": "1d"},
        {"source": "fixture", "currency": "USD", "rows": [{"time": "2026-10-01", "close": 80}, {"time": "2026-10-02", "close": 60}]})
    data.record("run_analysis_code", {}, {"error": "analysis_code_or_result_invalid", "code_error": {"message": "nan"}}, status="control")
    check = ResearchCompleteness(query, [{"role": "user", "content": "为什么英特尔突然这样暴跌"}], {})
    gaps = check.missing(data, [])
    calls = check.recovery_calls(gaps, [], {"render_chart": object()}, data)
    assert calls == [("render_chart", {"dataset_ref": ref, "title": "INTC价格走势", "chart_type": "line",
        "x": "time", "series": [{"field": "close", "name": "收盘价"}]})]


@pytest.mark.parametrize("query", ["不要画图", "画MA20均线图", "比较INTC与NVDA并画图"])
def test_plain_price_chart_cannot_substitute_for_unrequested_or_specialized_chart(query, tmp_path, monkeypatch):
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path))
    data = RunData("u", "s", "r", query)
    data.record("get_stock_historical_data", {"ticker": "INTC"}, {"rows": [{"time": "2026-10-01", "close": 80}]})
    check = ResearchCompleteness(query, [], {})
    assert not check.recovery_calls(check.missing(data, []), [], {"render_chart": object()}, data)


@pytest.mark.asyncio
async def test_live_chart_instruction_produces_artifact_before_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    rt, events = runtime(tmp_path, [finish("我准备画图。"), finish("已画出价格走势，可看到区间回落。")])
    rt.context.deadline += 60
    rt.query = "解释英特尔的价格走势"
    rt.data.record("get_stock_historical_data", {"ticker": "INTC", "interval": "1d"},
        {"source": "fixture", "currency": "USD", "rows": [{"time": "2026-10-01", "close": 80}, {"time": "2026-10-02", "close": 60}]})
    rt.instruct("画个图给我解释一下", "chart-request")
    try:
        answer = await rt.run_agent("root", "research_lead", rt.query)
        assert "已画出" in answer
        assert len(rt.data.artifacts) == 1
        assert any(kind == "artifact.ready" for kind, _, _ in events)
        assert not rt.completeness.missing(rt.data, rt.executor.attempts)
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_last_model_turn_delivers_existing_price_chart_before_closing(tmp_path, monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_MAX_TURNS", "1")
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    rt, events = runtime(tmp_path, [finish("图中展示了英特尔收盘价的回落。")])
    rt.query = "画个图解释英特尔走势"
    rt.completeness = ResearchCompleteness(rt.query, [], {})
    rt.data.record("get_stock_historical_data", {"ticker": "INTC"},
        {"source": "fixture", "rows": [{"time": "2026-10-01", "close": 80}, {"time": "2026-10-02", "close": 60}]})
    try:
        await rt.run_agent("root", "research_lead", rt.query)
        kinds = [kind for kind, _, _ in events]
        assert kinds.index("artifact.ready") < kinds.index("content.delta")
        assert len(rt.data.artifacts) == 1
    finally:
        await rt.close()


@pytest.mark.parametrize("source_style", ["citation", "source_refs"])
def test_causal_answer_with_chart_uses_verified_price_delivery(tmp_path, monkeypatch, source_style):
    from backend.agent_runtime.analysis import render_chart
    from backend.agent_runtime.fact_answer import can_compose_causal, causal_fact_delivery

    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path))
    query = "为什么英特尔暴跌，画个图给我解释一下"
    data = RunData("u", "s", "r", query)
    history_ref = data.record("get_stock_historical_data", {"ticker": "INTC", "interval": "1d"},
        {"source": "fixture", "currency": "USD", "rows": [
            {"time": "2026-11-05", "close": 40, "period_return_pct": -10},
            {"time": "2026-11-06", "close": 42, "period_return_pct": 5}]})
    news_ref = data.record("search", {"query": "INTC stock price drop"}, [
        {"title": "Intel outlook", "url": "https://example.com/intc-outlook", "published_date": "2026-11-06",
         "summary": "公司指引低于预期，引发抛售。"}])
    rt = SimpleNamespace(query=query, data=data, report_title=None, cause_summary_requested=True,
        completeness=ResearchCompleteness(query, [], {}),
        executor=SimpleNamespace(attempts=[{"data_ref": news_ref, "status": "success"}]))
    assert not can_compose_causal(rt)
    render_chart(data, history_ref, "INTC价格走势", "line", "time", [{"field": "close"}])
    assert can_compose_causal(rt)
    sid = data.source_refs(news_ref)[0]
    reference = f"[{sid}]" if source_style == "citation" else f"（source_refs: {sid}）"
    response = causal_fact_delivery(rt, "公司指引低于预期，引发抛售。 " + reference)
    assert "原因判断" in response and "40.00" in response and "42.00" in response
    assert data.source_refs(history_ref)[0] in response
    assert "source_refs" not in response
