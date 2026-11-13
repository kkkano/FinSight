"""新工具注册表的协议、并发、引用及只提议写操作边界。"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.agent_runtime.registry import ToolRegistry
from backend.agent_runtime.context import tokens
from backend.agent_runtime.data import RunData
from backend.agent_runtime.envelope import Source, ToolResult
from backend.agent_runtime.registry import ToolSpec, schema


def call(name, args, identity="call"):
    return {"id": identity, "type": "function", "function": {"name": name, "arguments": args}}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("FINSIGHT_ACTION_STORE", str(tmp_path / "actions.sqlite"))
    events, slots = [], []

    @asynccontextmanager
    async def slot(*args, **kwargs):
        slots.append(args)
        yield

    async def emit(kind, payload, agent_id="root"):
        events.append((kind, payload, agent_id))

    data = RunData("owner", "session", "run", "任何自然语言")
    data.storage_dir = tmp_path / "data"
    return SimpleNamespace(data=data, events=events, emit=emit, slots=slots, session_id="session", _knowledge=None,
        context=SimpleNamespace(owner="owner", run_id="run", guard=lambda: None, timeout=lambda value: value),
        model=SimpleNamespace(config=SimpleNamespace(context_window=32768), stream=AsyncMock(side_effect=AssertionError("工具不得调用模型"))), limiter=SimpleNamespace(slot=slot),
        base_tools={}, history=[], ui_context={}, actions={}, report_title=None, observed_tickers=[],
        children=set(), _closed=False, tool_count=0)


def seed(runtime):
    raw = {"rows": [{"day": "2026-11-10", "close": 1.2345, "volume": None},
                     {"day": "2026-11-11", "close": 2.3456, "volume": 7}]}
    return runtime.data.record("get_stock_historical_data", {"ticker": "NVDA"}, raw,
        envelope=ToolResult(status="ok", kind="series", data=raw,
                            sources=[Source(title="行情原始数据", url="https://example.test/history")]))


@pytest.mark.asyncio
@pytest.mark.parametrize("args", ['{"handle":', {"handle": 3}, {"handle": "h_missing", "offset": -1},
    {"handle": "h_missing", "limit": True}, {"handle": "h_missing", "other": 1}, ["h_missing"],
    '{"handle":"h_a","handle":"h_b"}', '{"handle":"h_a","limit":NaN}'])
async def test_invalid_arguments_return_error_envelopes(runtime, args):
    result = await ToolRegistry(runtime).execute(call("read_data", args), "root", "root")
    assert result.status == "error"
    assert result.error.code in {"invalid_tool_arguments", "tool_arguments_must_be_object"}
    assert [event[0] for event in runtime.events] == ["tool.failed"]


@pytest.mark.asyncio
async def test_financial_calls_share_work_and_return_original_data_with_citations(runtime):
    entered, release = asyncio.Event(), asyncio.Event()
    invocations = []
    raw = {"price": 42.125, "currency": "USD", "text": "error: 是资料正文"}

    async def quote(args):
        invocations.append(args)
        entered.set()
        await release.wait()
        return ToolResult(status="ok", kind="quote", data=raw,
                          sources=[Source(title="报价", url="https://example.test/quote")])

    runtime.base_tools["get_stock_price"] = ToolSpec("get_stock_price", "报价",
        schema({"ticker": {"type": "string"}, "period": {"type": "string"}}, ["ticker"]), quote, financial=True)
    registry = ToolRegistry(runtime)
    arguments = [{"ticker": "nvda", "period": "1d"}, {"period": "1d", "ticker": "nvda"}]
    tasks = [asyncio.create_task(registry.execute(call("get_stock_price", args, str(i)), "root", "root")) for i, args in enumerate(arguments)]
    await entered.wait()
    release.set()
    results = await asyncio.gather(*tasks)
    cached = await registry.execute(call("get_stock_price", arguments[0]), "root", "root")
    assert len(invocations) == len(runtime.slots) == 1
    assert len(runtime.data.records) == 1 and runtime.observed_tickers == ["NVDA"]
    assert all(result.data == raw and result.status == "ok" for result in [*results, cached])
    assert registry.metadata(cached)["source_refs"] == ["1"]
    projected = registry.model_text(cached, 400)
    assert "h_" in projected and "[1]" in projected and tokens(projected) <= 400
    assert runtime.events[-1][1]["display"]["kind"] == "quote"
    assert runtime.tool_count == 3


@pytest.mark.asyncio
async def test_read_data_pages_and_artifacts_preserve_stored_numbers(runtime):
    handle = seed(runtime)
    registry = ToolRegistry(runtime)
    original = deepcopy(runtime.data.records)
    result = await registry.execute(call("read_data", {"handle": handle, "columns": ["day", "close"], "offset": 1, "limit": 1}), "root", "root")
    assert result.data["rows"] == [{"day": "2026-11-11", "close": 2.3456}]
    assert result.data["row_count"] == 2 and result.data["next_offset"] == 2
    for name, args in [("render_table", {"columns": ["day", "close", "volume"]}),
                       ("render_chart", {"chart_type": "line", "x": "day", "series": [{"field": "close"}]})]:
        artifact = await registry.execute(call(name, {"handle": handle, "title": "真实数据", **args}), "root", "root")
        assert artifact.status == "ok" and artifact.data["source_refs"] == ["1"]
        assert artifact.data["data"]["rows"][0]["close"] == 1.2345
        assert artifact.data["data"]["rows"][0]["volume"] is None
    assert runtime.data.records == original and len(runtime.data.sources) == 1
    assert len([event for event in runtime.events if event[0] == "artifact.ready"]) == 2


@pytest.mark.asyncio
async def test_propose_action_always_requires_confirmation(runtime):
    runtime.ui_context["watchlist_auto_confirm"] = True
    registry = ToolRegistry(runtime)
    result = await registry.execute(call("propose_action", {"kind": "watchlist.add", "ticker": "nvda", "note": "模型提出的建议"}), "root", "root")
    assert result.status == "ok" and result.data["status"] == "confirmation_required"
    assert result.data["action"]["status"] == "proposed"
    assert result.data["action"]["ticker"] == "NVDA"
    assert [event[0] for event in runtime.events] == ["tool.started", "action.proposed", "tool.result"]
    assert runtime.data.sources == {}


@pytest.mark.asyncio
async def test_spawn_agents_share_data_but_cannot_nest_or_write(runtime):
    handle = seed(runtime)
    registry = ToolRegistry(runtime)
    entered = []

    async def run_agent(agent_id, role, task, refs, depth):
        entered.append((role, refs, depth))
        await registry.execute(call("read_data", {"handle": refs[0]}), agent_id, role, depth)
        return {"summary": task + "已完成", "data_refs": [], "stopped": False}

    runtime.run_agent = run_agent
    result = await registry.execute(call("spawn_agents", {"tasks": [
        {"role": "fundamental", "task": "现金流", "handles": [handle]},
        {"role": "risk", "task": "下行风险", "handles": [handle]}]}), "root", "root")
    assert result.status == "ok" and len(result.data["agents"]) == 2
    assert all(refs == [handle] and depth == 1 for _, refs, depth in entered)
    assert runtime.children == set()
    tools = registry.available("child", "fundamental_agent", 1)
    assert not {"spawn_agents", "propose_action", "mark_report", "update_plan"} & tools.keys()


@pytest.mark.asyncio
async def test_skills_loaded_only_by_declared_name_and_root_tools_directly_available(runtime):
    runtime.base_tools["get_stock_price"] = ToolSpec("get_stock_price", "报价", schema({}, []), lambda _: None, True)
    registry = ToolRegistry(runtime)
    assert "get_stock_price" in registry.available("root", "root")
    assert "get_stock_price" not in registry.available("child", "news", 1)
    assert "valuation-analysis" in registry.skills_index()
    result = await registry.execute(call("load_skill", {"name": "valuation-analysis"}), "root", "root")
    assert result.status == "ok" and "## 方法" in result.data
    invalid = await registry.execute(call("load_skill", {"name": "../../actions.py"}), "root", "root")
    assert invalid.status == "error"


@pytest.mark.asyncio
async def test_python_uses_isolated_helper_and_tracks_derived_refs(runtime, monkeypatch):
    handle = seed(runtime)
    calls = []

    async def compute(data, code, dataset_refs, timeout):
        calls.append((code, dataset_refs, timeout))
        output = {"rows": [{"answer": 3.5801, "missing": None}], "units": {"answer": "USD"}}
        ref = data.record("run_analysis_code", {"dataset_refs": dataset_refs}, output)
        return {"status": "ok", "result": output, "data_refs": [ref]}

    monkeypatch.setattr("backend.agent_runtime.registry.run_analysis_code", compute)
    registry = ToolRegistry(runtime)
    result = await registry.execute(call("run_python", {"code": "result = 1", "handles": [handle]}), "root", "root")
    assert calls == [("result = 1", [handle], 60)]
    assert result.status == "ok" and registry.metadata(result)["source_refs"] == ["1"]
    ref = registry.metadata(result)["handles"][0]
    assert runtime.data.rows(ref) == [{"answer": 3.5801, "missing": None}]
    assert len(runtime.data.sources) == 1
    rendered = registry.model_text(result, 500)
    assert "answer (USD)" in rendered and "3.5801" in rendered
    assert "column_units" not in result.data["result"]


@pytest.mark.asyncio
async def test_pure_assumption_python_allows_empty_handles_without_financial_source(runtime, monkeypatch):
    async def compute(data, code, dataset_refs, timeout):
        assert dataset_refs == []
        result = {"rows": [{"assumed_eps": 3, "multiple": 20, "value": 60}]}
        ref = data.record("run_analysis_code", {"dataset_refs": []}, result)
        return {"status": "ok", "result": result, "data_refs": [ref]}

    monkeypatch.setattr("backend.agent_runtime.registry.run_analysis_code", compute)
    registry = ToolRegistry(runtime)
    result = await registry.execute(call("run_python", {"code": "result = 3 * 20", "handles": []}), "root", "research_lead")
    assert result.status == "ok" and registry.metadata(result)["handles"]
    assert registry.metadata(result)["source_refs"] == []


@pytest.mark.asyncio
async def test_nested_chart_schema_rejects_executable_extra_fields(runtime):
    handle = seed(runtime)
    registry = ToolRegistry(runtime)
    result = await registry.execute(call("render_chart", {"handle": handle, "title": "图", "chart_type": "line", "x": "day",
        "series": [{"field": "close", "formatter": "alert(1)"}]}), "root", "research_lead")
    assert result.status == "error" and runtime.data.artifacts == []


@pytest.mark.asyncio
async def test_failed_child_does_not_discard_completed_sibling_data(runtime):
    registry = ToolRegistry(runtime)
    runtime.base_tools["get_stock_price"] = ToolSpec("get_stock_price", "报价", schema({"ticker": {"type": "string"}}, ["ticker"]),
        lambda _: ToolResult(status="ok", kind="quote", data={"price": 10}), True)

    async def run_agent(agent_id, role, task, refs, depth):
        if role == "risk_agent":
            raise RuntimeError("provider failed")
        await registry.execute(call("get_stock_price", {"ticker": "NVDA"}), agent_id, role, depth)
        return {"summary": "已取得报价", "stopped": False}

    runtime.run_agent = run_agent
    result = await registry.execute(call("spawn_agents", {"tasks": [
        {"role": "price", "task": "报价", "handles": []},
        {"role": "risk", "task": "风险", "handles": []}]}), "root", "research_lead")
    assert result.status == "ok" and len(result.data["data_refs"]) == 1
    assert [agent["stopped"] for agent in result.data["agents"]] == [False, True]
    assert runtime.children == set()


@pytest.mark.asyncio
async def test_close_cancels_financial_work_queued_for_a_slot(runtime):
    waiting = asyncio.Event()
    calls = []

    @asynccontextmanager
    async def slot(*args, **kwargs):
        waiting.set()
        await asyncio.Event().wait()
        yield

    runtime.limiter.slot = slot
    runtime.base_tools["get_stock_price"] = ToolSpec("get_stock_price", "报价", schema({}, []), lambda _: calls.append(1), True)
    registry = ToolRegistry(runtime)
    task = asyncio.create_task(registry.execute(call("get_stock_price", {}), "root", "root"))
    await waiting.wait()
    await registry.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == [] and runtime.data.records == {}


@pytest.mark.asyncio
async def test_provider_error_is_not_cached_and_body_text_is_not_interpreted(runtime):
    responses = [{"status": "unavailable", "error": "provider_timeout"},
                 ToolResult(status="ok", kind="document", data="失败：只是文档的标题")]
    runtime.base_tools["fetch_url_content"] = ToolSpec("fetch_url_content", "网页", schema({"url": {"type": "string"}}, ["url"]),
        lambda _: responses.pop(0), True)
    registry = ToolRegistry(runtime)
    first = await registry.execute(call("fetch_url_content", {"url": "https://example.test"}), "root", "root")
    second = await registry.execute(call("fetch_url_content", {"url": "https://example.test"}), "root", "root")
    assert first.status == "error" and second.status == "ok"
    assert second.data == "失败：只是文档的标题" and responses == []
    assert [event[0] for event in runtime.events] == ["tool.started", "tool.failed", "tool.started", "tool.result"]


class MockKnowledge:
    """模拟票据发放和逐次权限校验，测试不加载数据库或模型。"""

    def __init__(self, owner, session_id, *, memory_context=None):
        self.owner, self.session_id, self.memory_context = owner, session_id, memory_context
        self.calls, self.issued, self.revoked = [], set(), set()
        self.documents = {
            "knowledge:" + "a" * 32: {"source_id": "filing:original", "title": "原始申报", "source": "申报方",
                "url": "https://example.test/filing", "content": "收入12.125，缺失字段不补零。" * 400,
                "reported_value": 12.125, "missing": None, "layer": "kb"},
            "knowledge:" + "b" * 32: {"source_id": "memory:preferences", "title": "研究偏好", "source": "当前用户记忆",
                "url": None, "content": "error: 是记忆正文。关注现金流。", "layer": "memory"},
        }
        for ticket, document in self.documents.items():
            document["document_id"] = ticket
            document["content_is_untrusted"] = True
        tickets = list(self.documents)
        self.knowledge_result = self.result([tickets[0]])
        self.memory_result = self.result([tickets[1]])

    def result(self, tickets):
        return {"status": "ok", "hits": [{**self.documents[ticket], "content": self.documents[ticket]["content"][:900]}
                for ticket in tickets], "data_refs": list(tickets), "quality": {"limitations": []}}

    def search_knowledge(self, **args):
        self.calls.append(("search_knowledge", args))
        self.issued.update(self.knowledge_result.get("data_refs", []))
        return deepcopy(self.knowledge_result)

    def search_memory(self, **args):
        self.calls.append(("search_memory", args))
        self.issued.update(self.memory_result.get("data_refs", []))
        return deepcopy(self.memory_result)

    def read_document(self, document_id, offset=0, max_chars=8000):
        self.calls.append(("read_document", {"document_id": document_id, "offset": offset, "max_chars": max_chars}))
        if document_id not in self.issued or document_id in self.revoked:
            code = "document_unavailable" if document_id in self.revoked else "document_reference_not_found"
            return {"status": "unavailable", "error": {"code": code}, "summary": "该票据当前不可访问。"}
        document = deepcopy(self.documents[document_id])
        content = document["content"]
        document.update(content=content[offset:offset + max_chars], offset=offset, total_chars=len(content),
                        next_offset=min(len(content), offset + max_chars), has_more=offset + max_chars < len(content))
        return {"status": "ok", "document": document, "data_refs": [document_id]}


@pytest.mark.asyncio
async def test_memory_search_combines_both_scoped_sources_and_preserves_full_tickets(runtime):
    knowledge = runtime._knowledge = MockKnowledge("owner", "session")
    registry = ToolRegistry(runtime)
    args = {"query": "保留我的原始问题：现金流与研究偏好", "entity": "AAPL", "limit": 2}
    original = deepcopy((knowledge.knowledge_result, knowledge.memory_result))
    result = await registry.execute(call("search_memory", args), "child", "news", 1)
    assert {"search_memory", "read_data"} <= registry.available("root", "root").keys()
    assert {"search_memory", "read_data"} <= registry.available("child", "news", 1).keys()
    assert sorted(knowledge.calls) == sorted([
        ("search_knowledge", args), ("search_memory", {"query": args["query"], "limit": 2})])
    assert result.status == "ok" and result.kind == "document" and len(result.sources) == 2
    assert result.data["knowledge"] == original[0] and result.data["memory"] == original[1]
    assert (knowledge.knowledge_result, knowledge.memory_result) == original
    assert [hit["document_id"] for hit in result.data["results"]] == list(knowledge.documents)
    assert result.data["data_refs"] == list(knowledge.documents)
    metadata = registry.metadata(result)
    assert metadata["source_refs"] == ["1", "2"] and len(runtime.data.sources) == 2
    assert runtime.data.records[metadata["handles"][0]]["output"] == result.data
    assert runtime.data.sources["2"]["url"] is None
    rendered = registry.model_text(result, 3000)
    assert all(ticket in rendered for ticket in knowledge.documents)
    assert "[1]" in rendered and "[2]" in rendered
    assert runtime.slots == []
    runtime.model.stream.assert_not_called()


@pytest.mark.asyncio
async def test_knowledge_tools_are_lazy_and_bound_to_authenticated_history(runtime, monkeypatch):
    instances = []

    def factory(owner, session_id, **kwargs):
        value = MockKnowledge(owner, session_id, **kwargs)
        instances.append(value)
        return value

    module = ModuleType("backend.rag.tools")
    module.KnowledgeTools = factory
    monkeypatch.setitem(sys.modules, "backend.rag.tools", module)
    runtime.history = [{"role": "system", "content": "不应进入轻记忆"},
                       {"role": "user", "content": "用户历史" * 1000},
                       {"role": "assistant", "content": "助手正文也不进入轻记忆"}]
    registry = ToolRegistry(runtime)
    registry.available("root", "root")
    url = await registry.execute(call("read_data", {"handle": "https://example.test/filing"}), "root", "root")
    assert url.status == "error" and url.error.code == "dataset_not_found_in_this_run"
    assert instances == []
    await registry.execute(call("search_memory", {"query": "用户历史"}), "root", "root")
    await registry.execute(call("search_memory", {"query": "再查资料"}), "root", "root")
    assert len(instances) == 1 and runtime._knowledge is instances[0]
    assert (instances[0].owner, instances[0].session_id) == ("owner", "session")
    assert instances[0].memory_context == {"recent_topics": [runtime.history[1]["content"][:2000]]}
    runtime.model.stream.assert_not_called()


@pytest.mark.asyncio
async def test_document_read_revalidates_tickets_and_preserves_sources_and_page_values(runtime):
    knowledge = runtime._knowledge = MockKnowledge("owner", "session")
    registry = ToolRegistry(runtime)
    searched = await registry.execute(call("search_memory", {"query": "现金流"}), "root", "root")
    ticket, memory_ticket = list(knowledge.documents)
    result = await registry.execute(call("read_data", {"handle": ticket, "offset": 2, "limit": 1000}), "child", "fundamental", 1)
    assert result.status == "ok" and result.data["document"]["document_id"] == ticket
    assert result.data["document"]["content"] == knowledge.documents[ticket]["content"][2:1002]
    assert result.data["document"]["reported_value"] == 12.125 and result.data["document"]["missing"] is None
    assert knowledge.calls[-1] == ("read_document", {"document_id": ticket, "offset": 2, "max_chars": 1000})
    assert registry.metadata(result)["source_refs"] == ["1"]
    raw = deepcopy(result.data)
    page = json.loads(registry.model_text(result, 800).rsplit("\n\n", 1)[1])
    assert page["document_id"] == ticket
    assert page["content"] == raw["document"]["content"][:len(page["content"])]
    assert page["next_offset"] == 2 + len(page["content"])
    assert page["has_more"] and result.data == raw
    memory = await registry.execute(call("read_data", {"handle": memory_ticket}), "root", "root")
    assert memory.status == "ok" and registry.metadata(memory)["source_refs"] == ["2"]
    assert len(runtime.data.sources) == 2 and registry.metadata(searched)["source_refs"] == ["1", "2"]
    knowledge.revoked.add(ticket)
    denied = await registry.execute(call("read_data", {"handle": ticket}), "root", "root")
    assert denied.status == "error" and denied.error.code == "document_unavailable"
    assert registry.metadata(denied)["source_refs"] == []
    assert len([name for name, _ in knowledge.calls if name == "read_document"]) == 3
    runtime.model.stream.assert_not_called()


@pytest.mark.asyncio
async def test_unissued_ticket_cannot_cross_owner_or_session_scope(runtime):
    issuer = MockKnowledge("owner", "session")
    ticket = issuer.search_knowledge(query="现金流")["data_refs"][0]
    runtime._knowledge = MockKnowledge("another-owner", "another-session")
    registry = ToolRegistry(runtime)
    result = await registry.execute(call("read_data", {"handle": ticket}), "root", "root")
    assert result.status == "error" and result.error.code == "document_reference_not_found"
    assert result.data["status"] == "unavailable"
    assert runtime.data.sources == {}
    runtime.model.stream.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["owner", "session_id", "collection"])
async def test_memory_tool_cannot_override_runtime_scope(runtime, field):
    knowledge = runtime._knowledge = MockKnowledge("owner", "session")
    result = await ToolRegistry(runtime).execute(call("search_memory", {"query": "现金流", field: "foreign"}), "root", "root")
    assert result.status == "error" and result.error.code == "invalid_tool_arguments"
    assert knowledge.calls == [] and runtime.data.records == {}


@pytest.mark.asyncio
async def test_strict_selection_blocks_search_unselected_tickets_and_broad_cached_results(runtime):
    knowledge = runtime._knowledge = MockKnowledge("owner", "session")
    registry = ToolRegistry(runtime)
    searched = await registry.execute(call("search_memory", {"query": "现金流"}), "root", "root")
    ticket, memory_ticket = list(knowledge.documents)
    runtime.ui_context = {"strict_selection": True, "selection": {"id": memory_ticket, "type": "doc", "title": "选中记忆"}}
    before = list(knowledge.calls)
    for agent_id, role, depth in [("root", "root", 0), ("child", "news", 1)]:
        assert "search_memory" not in registry.available(agent_id, role, depth)
        rejected = await registry.execute(call("search_memory", {"query": "现金流"}), agent_id, role, depth)
        assert rejected.status == "error" and rejected.error.code == "tool_not_allowed"
    for handle in [ticket, registry.metadata(searched)["handles"][0]]:
        rejected = await registry.execute(call("read_data", {"handle": handle}), "root", "root")
        assert rejected.status == "error" and rejected.error.code == "selection_scope_violation"
    assert knowledge.calls == before
    accepted = await registry.execute(call("read_data", {"handle": memory_ticket}), "child", "news", 1)
    assert accepted.status == "ok" and accepted.data["document"]["document_id"] == memory_ticket
    assert knowledge.calls[-1][0] == "read_document"
    runtime.model.stream.assert_not_called()


@pytest.mark.asyncio
async def test_partial_knowledge_failure_keeps_scoped_memory_and_empty_store_has_no_sources(runtime):
    knowledge = runtime._knowledge = MockKnowledge("owner", "session")
    knowledge.knowledge_result = {"status": "unavailable", "error": {"code": "provider_timeout"}, "hits": []}
    registry = ToolRegistry(runtime)
    result = await registry.execute(call("search_memory", {"query": "现金流"}), "root", "root")
    assert result.status == "ok" and len(result.data["results"]) == 1
    assert result.data["knowledge"] == knowledge.knowledge_result
    assert result.data["memory"] == knowledge.memory_result
    assert result.notes and registry.metadata(result)["source_refs"] == ["1"]
    assert len(runtime.data.sources) == 1 and runtime.data.sources["1"]["title"] == "研究偏好"
    knowledge.knowledge_result = knowledge.memory_result = {
        "status": "empty", "items": [], "source": "evaluation_isolated_store", "summary": "隔离账号无历史资料。"}
    empty = await registry.execute(call("search_memory", {"query": "任何问题"}), "root", "root")
    assert empty.status == "empty" and empty.data["results"] == []
    assert registry.metadata(empty)["source_refs"] == [] and len(runtime.data.sources) == 1
    runtime.model.stream.assert_not_called()
