"""同会话切换标的仍须保留取证能力，旧资料不能触发本轮提前收尾。"""
from dataclasses import replace

import pytest

from backend.agent_runtime.context import dumps
from backend.agent_runtime.loop import AgentRuntime
from backend.agent_runtime.tools import ToolSpec, schema
from backend.services.run_context import RunContext
from backend.tests.test_agent_runtime import FakeModel, call, finish


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FINSIGHT_RUNTIME_QUOTA_DB", str(tmp_path / "quota.sqlite"))
    monkeypatch.setenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")


class ToolAwareModel(FakeModel):
    """供应商在没有工具定义时只能返回文本，不能伪造一次成功工具调用。"""
    def __init__(self, turns):
        super().__init__(turns)
        self.tool_names = []

    async def stream(self, messages, tools, **kwargs):
        self.tool_names.append({tool["function"]["name"] for tool in tools})
        if not tools:
            self.inputs.append(messages)
            for chunk in finish("目前只有英特尔资料，无法确认英伟达情况。"):
                yield chunk
            return
        async for chunk in super().stream(messages, tools, **kwargs):
            yield chunk


def make_runtime(model, *, history=None, tools=None):
    context = RunContext.create(owner="topic-switch-test", entry="chat", budget_seconds=90)
    context.quota_checker = lambda _: None

    async def emit(*_args, **_kwargs):
        pass

    runtime = AgentRuntime(context=context, session_id="same-session",
        query="英伟达的黄仁勋最近开闻有什么影响", model=model, emit=emit,
        history=history or [{"role": "user", "content": "英特尔为什么下跌"}],
        ui_context={"active_symbol": "INTC"}, tools=tools)
    runtime.data.record("get_stock_price", {"ticker": "INTC"},
        {"price": 42, "currency": "USD", "source": "测试报价"})
    return runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("check_time", [False, True])
async def test_inherited_evidence_does_not_stop_discovery_before_new_subject_fetch(check_time):
    invoked = []
    price = ToolSpec("get_stock_price", "获取行情", schema({"ticker": {"type": "string"}}, ["ticker"]),
        lambda args: (invoked.append(args["ticker"]), {"price": 100, "source": "测试报价"})[1], True)
    clock = ToolSpec("get_current_datetime", "当前时间", schema({}, []), lambda _: "2026-11-08", True)
    preparation = [call("get_current_datetime", {}), call("discover_skills", {})] if check_time else []
    model = ToolAwareModel([*preparation, call("discover_tools", {}), call("enable_tools", {"names": ["get_stock_price"]}),
        call("get_stock_price", {"ticker": "NVDA"}), finish("已经查询英伟达。")])
    runtime = make_runtime(model, tools={price.name: price, clock.name: clock})
    # 测试工具流不回报usage，预留足够预算以单独验证提前收尾边界。
    runtime.budget.maximum = 400_000
    try:
        await runtime.run_agent("root", "research_lead", runtime.query)
        assert invoked == ["NVDA"]
        assert "get_stock_price" in model.tool_names[len(preparation) + 2]
        assert '"active_symbol": "INTC"' not in model.inputs[0][0]["content"]
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_long_conversation_compacts_history_without_disabling_research():
    from backend.agent_runtime.tools import financial_tools

    invoked = []
    tools = financial_tools()
    tools["get_stock_price"] = replace(tools["get_stock_price"],
        invoke=lambda args: (invoked.append(args["ticker"]), {"price": 100, "source": "测试报价"})[1])
    history = [{"role": role, "content": "英特尔此前的经营现金流和市场表现。" * 400}
               for _ in range(5) for role in ("user", "assistant")]
    model = ToolAwareModel([call("get_stock_price", {"ticker": "NVDA"}), finish("已取得英伟达报价。")])
    runtime = make_runtime(model, history=history, tools=tools)
    runtime.instruct("只核实公开报道，保持简短。", "current-correction")
    try:
        await runtime.run_agent("root", "research_lead", runtime.query)
        assert invoked == ["NVDA"]
        assert "get_stock_price" in model.tool_names[0]
        assert runtime.query in dumps(model.inputs[0])
        assert "只核实公开报道，保持简短。" in dumps(model.inputs[0])
    finally:
        await runtime.close()


@pytest.mark.parametrize("query", ["现在取", "重新取数英伟达", "重新获取英伟达数据"])
def test_fetch_followup_targets_latest_explicit_company(query):
    from backend.agent_runtime.completeness import ResearchCompleteness

    history = [{"role": "user", "content": "英特尔最新财报"},
               {"role": "user", "content": "英伟达的黄仁勋最近新闻有什么影响"},
               {"role": "assistant", "content": "目前只有英特尔 INTC 的资料。"}]
    check = ResearchCompleteness(query, history, {"active_symbol": "INTC"})
    assert check.tickers == ["NVDA"]
    assert check.refresh
    assert "news" in check.facets and "fresh_search" in check.facets
    assert "filings" not in check.facets
    calls = check.recovery_calls(check.missing(type("Data", (), {"records": {}, "artifacts": []})(), []),
        [], {"search": object(), "get_company_news": object()})
    assert any(name == "search" and "NVDA" in args["query"] and "黄仁勋" in args["query"] for name, args in calls)


@pytest.mark.asyncio
async def test_search_only_switch_updates_session_subject_and_frontend_focus(monkeypatch):
    from backend.agent_runtime.data import RunData
    from backend.tests.test_runtime_completeness import run, tool

    previous = RunData("completeness-user", "completion-session", "intc-parent", "英特尔最新新闻")
    previous.record("get_stock_price", {"ticker": "INTC"}, {"price": 42, "source": "测试报价"})
    previous.save()
    calls = []

    def search(args):
        calls.append(args)
        return [{"title": "NVIDIA announces public update", "url": "https://nvidianews.nvidia.com/news/test-update",
                 "published_date": "2026-11-08", "summary": "NVIDIA published an update."}]

    events, _ = await run(monkeypatch, "英伟达最新新闻", {"search": tool("search", search)},
        history=[{"role": "user", "content": "英特尔最新新闻"}], resume="intc-parent",
        turns=[call("search", {"query": "NVDA latest news"}), finish("已查询英伟达公开消息。")])
    done = events[-1]
    assert calls and all("NVDA" in args["query"] for args in calls)
    assert done["tickers"] == ["NVDA"] and done["current_focus"] == "NVDA"
    assert done["answer_status"] == "answered"


def test_refresh_does_not_import_previous_company_financial_task():
    from backend.agent_runtime.completeness import ResearchCompleteness

    check = ResearchCompleteness("重新取数英伟达", [{"role": "user", "content": "英特尔最新财报"}], {})
    assert check.tickers == ["NVDA"] and check.facets == ["fresh_search"]


def test_short_fetch_keeps_latest_company_question_even_with_unrecognized_facet():
    from backend.agent_runtime.completeness import ResearchCompleteness

    topic = "英伟达的黄仁勋最近开闻有什么影响"
    check = ResearchCompleteness("现在取", [
        {"role": "user", "content": "英特尔最近交易日的股价是多少"},
        {"role": "user", "content": topic},
        {"role": "user", "content": "重新取数英伟达"},
    ], {"active_symbol": "INTC"})
    assert check.tickers == ["NVDA"]
    assert topic in check.query


def test_intervening_pronoun_followup_does_not_restore_stale_dashboard_ticker():
    from backend.agent_runtime.completeness import ResearchCompleteness

    check = ResearchCompleteness("现在取", [
        {"role": "user", "content": "英特尔最近表现"},
        {"role": "user", "content": "英伟达最近消息"},
        {"role": "user", "content": "它的估值呢"},
    ], {"active_symbol": "INTC"})
    assert check.tickers == ["NVDA"]
    assert "它的估值呢" in check.query and "valuation" in check.facets
