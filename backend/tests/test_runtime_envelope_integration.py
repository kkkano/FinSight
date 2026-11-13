"""统一注册表消费信封，失败判断、去重和控制来源均按协议验证。"""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import pytest

from backend.agent_runtime.config import ModelConfig
from backend.agent_runtime.context import tokens
from backend.agent_runtime.data import RunData
from backend.agent_runtime.registry import ToolRegistry, ToolSpec, schema
from backend.agent_runtime.adapters import adapt_result
from backend.agent_runtime.envelope import to_model, to_ui


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    events = []

    @asynccontextmanager
    async def slot(*args, **kwargs):
        yield

    async def emit(kind, payload, **kwargs):
        events.append((kind, payload))

    rt = SimpleNamespace(context=SimpleNamespace(owner="fixture-owner", guard=lambda: None,
                          timeout=lambda value: value), limiter=SimpleNamespace(slot=slot),
                         data=RunData(owner="fixture-owner", session_id="fixture-session", run_id="fixture-run", query="协议测试"),
                         model=SimpleNamespace(config=ModelConfig("fixture", "https://example.invalid", "fixture")),
                         ui_context={}, base_tools={}, observed_tickers=[], _closed=False, emit=emit, tool_count=0)
    rt.executor = ToolRegistry(rt)
    return rt, events


@pytest.mark.asyncio
async def test_shared_financial_call_keeps_typed_data_and_source_refs(runtime):
    rt, events = runtime
    calls = []

    def quote(args):
        calls.append(args)
        return {"status": "ok", "price": 42.25, "currency": "USD", "source": "fixture"}

    spec = ToolSpec("get_stock_price", "行情", schema({"ticker": {"type": "string"}}, ["ticker"]), quote, True)
    rt.base_tools[spec.name] = spec
    results = await asyncio.gather(*(rt.executor.execute({"id": f"call-{index}", "function": {
        "name": spec.name, "arguments": {"ticker": "AAPL"}}}, "root", "research_lead") for index in range(2)))
    assert calls == [{"ticker": "AAPL"}]
    assert len([kind for kind, _ in events if kind == "tool.started"]) == 2
    assert all(result.status == "ok" and result.kind == "quote" for result in results)
    assert rt.executor.metadata(results[0]) == rt.executor.metadata(results[1])
    projection = rt.executor.model_text(results[0], 600)
    assert "42.25" in projection and "[1]" in projection and tokens(projection) <= 600
    assert json.loads(projection.splitlines()[0])["source_refs"] == ["1"]
    assert rt.observed_tickers == ["AAPL"]


@pytest.mark.asyncio
async def test_empty_data_is_not_a_provider_failure(runtime):
    rt, events = runtime
    spec = ToolSpec("get_stock_price", "行情", schema({"ticker": {"type": "string"}}, ["ticker"]),
                    lambda _: {"status": "empty", "data": []}, True)
    rt.base_tools[spec.name] = spec
    result = await rt.executor.execute({"id": "empty", "function": {"name": spec.name, "arguments": {"ticker": "AAPL"}}},
                                       "root", "research_lead")
    assert result.status == "empty" and result.error is None
    assert events[-1][0] == "tool.result" and rt.data.sources == {}
    assert rt.data.records[rt.executor.metadata(result)["handles"][0]]["status"] == "empty"


@pytest.mark.asyncio
async def test_financial_catalog_control_result_cannot_create_financial_sources(runtime):
    rt, _ = runtime
    spec = ToolSpec("get_current_datetime", "时间", schema({}, []), lambda _: "2026-11-11T12:00:00Z", True)
    rt.base_tools[spec.name] = spec
    result = await rt.executor.execute({"id": "clock", "function": {"name": spec.name, "arguments": {}}},
                                       "root", "research_lead")
    assert result.kind == "control" and rt.data.sources == {}
    assert rt.executor.metadata(result) == {"handles": [], "source_refs": []}
    assert rt.data.records == {}


def test_nested_quote_keeps_outer_currency_visible():
    result = adapt_result("get_stock_price", {"status": "ok", "currency": "HKD", "data": {"price": 42.25}})
    display = to_ui(result, "get_stock_price", {"ticker": "0700.HK"})
    assert "HKD" in display["result"]
    assert {"label": "货币", "value": "HKD"} in display["key_facts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("total", [5, 20])
async def test_dataset_projection_uses_declared_full_row_count(runtime, total):
    rt, _ = runtime
    rows = [{"close": 42.25 + index} for index in range(total)]
    ref = rt.data.record("get_stock_historical_data", {}, {"rows": rows})
    result = await rt.executor.execute({"id": "page", "function": {"name": "read_data",
        "arguments": {"handle": ref, "limit": 1}}}, "root", "research_lead")
    assert f"共 {total} 行，已显示 1 行" in to_model(result, 1000, handle=ref)
    assert to_ui(result, "read_data")["row_count"] == total
    assert to_ui(result, "read_data")["has_more"] is True
    assert rt.data.records[ref]["output"] == {"rows": rows}


def test_financial_serialization_keeps_non_finite_missing_values_as_null(monkeypatch):
    from backend.agent_runtime import registry
    from backend.agent_runtime.envelope import ToolResult
    monkeypatch.setattr(registry, "invoke_adapter", lambda *args: ToolResult(status="ok", kind="quote", data={"price": float("nan")}))
    result = registry.financial_tools()["get_stock_price"].invoke({"ticker": "AAPL"})
    assert result["data"]["price"] is None
