"""同会话切换标的仍能调用真实工具，并向模型保留完整问题与追加要求。"""
from dataclasses import replace
import pytest
from backend.agent_runtime.context import dumps
from backend.agent_runtime.envelope import ToolResult
from backend.agent_runtime.loop import AgentRuntime
from backend.agent_runtime.registry import ToolSpec, schema
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
    clock = ToolSpec("get_current_datetime", "当前时间", schema({}, []), lambda _: ToolResult(status="ok", kind="control", data={"date":"2026-11-08"}))
    preparation = [call("get_current_datetime", {})] if check_time else []
    model = ToolAwareModel([*preparation, call("get_stock_price", {"ticker": "NVDA"}), finish("已经查询英伟达。")])
    rt = make_runtime(model, tools={price.name: price, clock.name: clock})
    try:
        result = await rt.run_agent()
        assert result["stopped"] == "completed" and invoked == ["NVDA"]
        assert all("get_stock_price" in tools for tools in model.tool_names)
        assert rt.query in dumps(model.inputs[0])
        assert rt.observed_tickers == ["NVDA"]
        assert any(record["inputs"].get("ticker") == "INTC" for record in rt.data.records.values())
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_long_conversation_compacts_history_without_disabling_research():
    invoked = []
    price = ToolSpec("get_stock_price", "行情", schema({"ticker": {"type": "string"}}, ["ticker"]),
        lambda args: (invoked.append(args["ticker"]), {"price": 100, "currency": "USD"})[1], True)
    history = [{"role": role, "content": "英特尔此前的经营现金流和市场表现。" * 400}
               for _ in range(5) for role in ("user", "assistant")]
    notes = {"known_facts": [], "unresolved_questions": [], "user_requirements": ["保留历史口径"]}
    class HistoryModel(ToolAwareModel):
        def __init__(self):
            super().__init__([call("get_stock_price", {"ticker": "NVDA"}), finish("已取得英伟达报价。")])
            self.summaries = []
        async def stream(self, messages, tools, **kwargs):
            if not tools:
                self.summaries.append(messages)
                for chunk in finish(dumps(notes)):
                    yield chunk
            else:
                async for chunk in super().stream(messages, tools, **kwargs):
                    yield chunk
    model = HistoryModel()
    model.config = replace(model.config, context_window=90000, max_output=2048)
    rt = make_runtime(model, history=history, tools={price.name: price})
    rt.instruct("只核实公开报道，保持简短。", "current-correction")
    # 工具调用夹具不返回 usage，预留估算预算以单独验证上下文与工具能力。
    rt.budget.maximum = 400_000
    try:
        result = await rt.run_agent()
        assert result["stopped"] == "completed" and invoked == ["NVDA"]
        assert "get_stock_price" in model.tool_names[0] and len(model.summaries) == 1
        assert rt.query in dumps(model.inputs[0]) and "只核实公开报道，保持简短。" in dumps(model.inputs[0])
        assert all(message in model.inputs[0] for message in history if message["role"] == "user")
    finally:
        await rt.close()
