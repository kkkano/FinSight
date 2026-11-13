"""显式取证的缓存、失败记录、读回和上下文边界。"""
from types import SimpleNamespace
from copy import deepcopy
import pytest

from backend.agent_runtime import service
from backend.agent_runtime.compactor import Compactor
from backend.agent_runtime.context import tokens
from backend.agent_runtime.data import RunData
from backend.agent_runtime.envelope import ToolResult
from backend.agent_runtime.loop import AgentRuntime
from backend.agent_runtime.registry import ToolSpec, schema
from backend.services.run_context import RunContext
from backend.tests.test_agent_runtime import FakeModel, cfg, finish, call, execute, runtime


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FINSIGHT_ACTION_STORE", str(tmp_path / "actions.sqlite"))
    monkeypatch.setenv("FINSIGHT_RUNTIME_QUOTA_DB", str(tmp_path / "quota.sqlite"))
    monkeypatch.setenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")


def tool(name, callback):
    key = "query" if name == "search" else "ticker"
    return ToolSpec(name, name, schema({key: {"type": "string"}}, [key]), callback, True)


def review_pass(requirement):
    return call("submit_review", {"verdict": "pass", "findings": [],
        "coverage": [{"requirement": requirement, "met": True}]}, call_id="review_submit")


def financials(_args):
    return {"source": "sec_companyfacts", "source_url": "https://www.sec.gov/Archives/filing", "period_ends": ["2026-06-30"],
            "revenue": [100], "net_income": [10], "operating_cash_flow": [12], "free_cash_flow": [8]}


async def run(monkeypatch, query, tools, *, history=None, resume=None, turns=None):
    model = FakeModel(turns or [finish("现有资料不足。"), finish("已根据披露数据核对，仍需结合未来增长判断。")])
    monkeypatch.setattr(service, "resolve_model", cfg)
    monkeypatch.setattr(service, "ModelTransport", lambda _: model)
    monkeypatch.setattr(service, "AgentRuntime", lambda **kwargs: AgentRuntime(**kwargs, tools=tools))
    context = RunContext.create(owner="completeness-user", entry="chat", budget_seconds=90)
    context.quota_checker = lambda _: None
    async def archive():
        pass
    context.archive_usage = archive
    deps = SimpleNamespace(schedule_report_index=lambda **_: True, update_session_context=lambda **_: None, persist_run_event=None)
    events = [e async for e in service.run_agent_pipeline(deps=deps, query=query, thread_id="completion-session",
        run_id=context.run_id, run_context=context, ui_context={"session_history": history or [], "resume_from_run_id": resume})]
    return events, model


@pytest.mark.asyncio
async def test_empty_financial_result_is_not_cached_as_success(tmp_path):
    invoked = []
    spec = tool("get_company_news", lambda args: (invoked.append(args), ToolResult(status="empty", kind="news", data=[]))[1])
    rt, _ = runtime(tmp_path, [], {spec.name: spec})
    try:
        for cid in ("a", "b"):
            result = await execute(rt, spec.name, {"ticker": "INTC"}, cid)
            assert result.status == "empty" and not rt.registry.metadata(result)["source_refs"]
        assert len(invoked) == 2
    finally:
        await rt.close()


def test_restore_rejects_declared_empty_and_failed_records():
    old = RunData("u", "s", "old", "INTC")
    old.record("get_company_news", {"ticker": "INTC"}, [], envelope=ToolResult(status="empty", kind="news", data=[]))
    old.record("get_company_info", {"ticker": "INTC"}, {"status": "unavailable", "error": "timeout"})
    old.save()
    followup = RunData("u", "s", "new", "继续")
    assert not followup.restore("old")
    assert not followup.records and not followup.sources


@pytest.mark.asyncio
async def test_companyfacts_preview_exposes_real_financial_fields_before_long_metadata(tmp_path):
    payload = financials({})
    payload["fact_metadata"] = {"revenue": [{"unit": "USD", "description": "申报元数据" * 1000}]}
    rt, _ = runtime(tmp_path, [])
    ref = rt.data.record("get_sec_company_facts_quarterly", {"ticker": "INTC"}, payload)
    try:
        result = await execute(rt, "read_data", {"handle": ref, "columns": ["period_end", "net_income", "free_cash_flow"], "limit": 1})
        assert result.data["rows"] == [{"period_end": "2026-06-30", "net_income": 10, "free_cash_flow": 8}]
        preview = rt.registry.model_text(result, 1000)
        assert "10" in preview and "8" in preview and ref in preview and tokens(preview) <= 1000
        assert rt.data.records[ref]["output"] == payload
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_two_large_recent_readbacks_keep_protocol_and_fit_window():
    messages = [{"role": "system", "content": "规则" * 500}]
    for i in range(2):
        messages.extend([{"role": "assistant", "tool_calls": [{"id": str(i), "function": {"name": "read_data", "arguments": "{}"}}]},
                         {"role": "tool", "tool_call_id": str(i), "content": "原文" * 3000}])
    before = deepcopy(messages)
    context = SimpleNamespace(guard=lambda: None, timeout=lambda seconds: seconds)
    compactor = Compactor(RunData("u", "s", "r", "读回"), FakeModel([]), context)
    result = await compactor.fit(messages, [], 32000, 2000)
    assert tokens(result) + tokens([]) < 30000 and result == before and messages == before
    calls = {call["id"] for message in result for call in message.get("tool_calls", [])}
    assert calls == {message["tool_call_id"] for message in result if message.get("role") == "tool"}


@pytest.mark.asyncio
async def test_explicit_search_followup_performs_new_search(monkeypatch):
    old = RunData("completeness-user", "completion-session", "old", "INTC新闻")
    old.record("get_company_news", {"ticker": "INTC"}, [], envelope=ToolResult(status="empty", kind="news", data=[]))
    old.save()
    invoked = []
    def search(args):
        invoked.append(args)
        return {"title": "Intel results", "url": "https://www.intc.com/news-events/press-releases/detail/1", "content": "Intel reported earnings."}
    events, model = await run(monkeypatch, "你去搜啊", {"search": tool("search", search)},
        history=[{"role": "user", "content": "INTC最新新闻"}], resume="old",
        turns=[call("search", {"query": "INTC latest news"}), finish("已查询最新报道。"),
               review_pass("重新搜索INTC新闻")])
    assert invoked == [{"query": "INTC latest news"}]
    assert events[-1]["answer_status"] == "answered" and events[-1]["metrics"]["tool_calls"] == 1
    review = next(event["payload"] for event in events if event["type"] == "review.finished")
    assert review["status"] == "completed" and review["verdict"] == "pass"
    assert review["coverage"] == [{"requirement": "重新搜索INTC新闻", "met": True}]
    assert len(model.inputs) == 3 and model.turns == []
