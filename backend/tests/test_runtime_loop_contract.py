"""真实循环的模型协议边界；模型替身只发送工具或文本流片段。"""
from __future__ import annotations

import ast
import asyncio
from copy import deepcopy
import inspect
import json
from pathlib import Path
import time

import pytest
import pytest_asyncio

from backend.agent_runtime import loop
from backend.agent_runtime.config import ModelConfig
from backend.agent_runtime.envelope import ToolResult
from backend.agent_runtime.limits import LeaseLimiter
from backend.agent_runtime.model import ModelProtocolError
from backend.agent_runtime.registry import ToolSpec, schema
from backend.services.run_context import RunContext


RAW_ANSWER = "价格 42.123 美元；h_deadbeef、data_ref=record_123、source_refs 均为原文。\n[数据缺失] 仍按原样保留。"


def text_turn(text, *, finish="stop"):
    return [{"choices": [{"delta": {"content": text}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": finish}],
             "usage": {"prompt_tokens": 30, "completion_tokens": 10}}]


def tool_turn(*calls):
    return [{"choices": [{"delta": {"tool_calls": [
        {"index": index, "id": identity, "type": "function",
         "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}
        for index, (identity, name, arguments) in enumerate(calls)]}, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 10}}]


class ScriptedModel:
    def __init__(self, turns, *, after_chunk=None):
        self.config = ModelConfig("protocol-fixture", "https://model.invalid/v1", "fixture-key",
                                  context_window=65536, max_output=1024)
        self.turns = deepcopy(turns)
        self.inputs = []
        self.after_chunk = after_chunk

    async def stream(self, messages, tools, **kwargs):
        turn = len(self.inputs)
        self.inputs.append({"messages": deepcopy(messages), "tools": deepcopy(tools), "kwargs": kwargs})
        assert turn < len(self.turns), "循环发起了脚本之外的模型调用"
        for index, chunk in enumerate(self.turns[turn]):
            yield deepcopy(chunk)
            if self.after_chunk:
                await self.after_chunk(turn, index)


@pytest.fixture
def runtime_environment(monkeypatch, tmp_path):
    for key, value in {
        "FINSIGHT_RUNTIME_QUOTA_DB": str(tmp_path / "quota.sqlite"),
        "FINSIGHT_ACTION_STORE": str(tmp_path / "actions.sqlite"),
        "FINSIGHT_ARTIFACT_DIR": str(tmp_path / "artifacts"),
        "FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS": "0",
        "FINSIGHT_AGENT_MAX_TURNS": "4",
        "FINSIGHT_AGENT_MODEL_CONCURRENCY": "4",
        "FINSIGHT_AGENT_TPM_LIMIT": "1000000",
        "FINSIGHT_AGENT_RPM_LIMIT": "100",
        "FINSIGHT_AGENT_TOKEN_BUDGET": "300000",
    }.items():
        monkeypatch.setenv(key, value)
    from backend.services import agent_run_archive
    archived = []
    from types import SimpleNamespace
    monkeypatch.setattr(agent_run_archive, "get_agent_run_archive", lambda: SimpleNamespace(
        archive_usage_summary=lambda **kwargs: archived.append(kwargs)))
    return {"path": tmp_path, "archived_usage": archived}


@pytest_asyncio.fixture
async def make_runtime(runtime_environment):
    instances = []

    def create(turns, *, tools=None, query="协议请求", history=None, after_chunk=None):
        events = []

        async def emit(kind, payload, agent_id):
            events.append((kind, deepcopy(payload), agent_id))

        context = RunContext.create(owner="fixture-owner", entry="chat", budget_seconds=120)
        context.quota_checker = lambda _owner: None
        model = ScriptedModel(turns, after_chunk=after_chunk)
        runtime = loop.AgentRuntime(context=context, session_id="fixture-session", query=query,
            model=model, emit=emit, history=history, tools=tools or {},
            limiter=LeaseLimiter(runtime_environment["path"] / "quota.sqlite"))
        instances.append(runtime)
        return runtime, model, events

    yield create
    for instance in instances:
        await instance.close()


def control_tool(name, invoke):
    return ToolSpec(name, "测试协议工具", schema({"value": {"type": "string"}}, ["value"]), invoke)


@pytest.mark.asyncio
async def test_raw_numbers_and_internal_looking_words_are_never_rewritten(make_runtime):
    runtime, model, events = make_runtime([text_turn(RAW_ANSWER)])
    result = await runtime.run_agent()
    assert result["summary"] == runtime.root_content == RAW_ANSWER
    assert "".join(payload["delta"] for kind, payload, _ in events if kind == "content.delta") == RAW_ANSWER
    assert len(model.inputs) == 1
    assert runtime.tool_count == 0


@pytest.mark.asyncio
async def test_final_review_rejects_new_instructions_but_keeps_existing_receipts(make_runtime):
    runtime, _model, _events = make_runtime([])
    receipt = runtime.instruct("原要求", "instruction-1")
    runtime.accepting_instructions = False
    assert runtime.instruct("原要求", "instruction-1") == receipt
    with pytest.raises(ValueError, match="run_not_accepting_instructions"):
        runtime.instruct("新要求", "instruction-2")
    assert "instruction-2" not in runtime.instructions


@pytest.mark.asyncio
async def test_tool_names_in_prose_do_not_execute_tools(make_runtime):
    invoked = []
    tool = control_tool("fixture_read", lambda args: invoked.append(args) or ToolResult(status="ok", kind="control"))
    runtime, _model, _events = make_runtime([text_turn("文中提到 fixture_read 和 run_python。")],
        tools={tool.name: tool}, query="fixture_read、run_python 是什么工具名称")
    await runtime.run_agent()
    assert invoked == []
    assert runtime.tool_count == 0


@pytest.mark.asyncio
async def test_only_protocol_requested_tool_executes_and_result_returns_to_same_history(make_runtime):
    invoked = []
    tools = {name: control_tool(name, lambda args, name=name: invoked.append((name, args)) or
        ToolResult(status="ok", kind="control", data={"value": args["value"]}))
        for name in ("fixture_read", "unused_read")}
    history = [{"role": "user", "content": "保留此前提问 12.5"}, {"role": "assistant", "content": "此前原文"}]
    runtime, model, _events = make_runtime([
        tool_turn(("read-call", "fixture_read", {"value": "真实返回 42.123"})), text_turn("完成")],
        tools=tools, history=history)
    await runtime.run_agent()
    assert invoked == [("fixture_read", {"value": "真实返回 42.123"})]
    assert model.inputs[1]["messages"][1:3] == history
    tool_messages = [item for item in model.inputs[1]["messages"] if item["role"] == "tool"]
    assert len(tool_messages) == 1 and tool_messages[0]["tool_call_id"] == "read-call"
    assert "真实返回 42.123" in tool_messages[0]["content"]


@pytest.mark.asyncio
async def test_tool_group_executes_concurrently_without_synthesized_calls(make_runtime):
    entered = {name: asyncio.Event() for name in ("read_a", "read_b")}
    order = []

    def reader(name, other):
        async def invoke(args):
            order.append(("start", name))
            entered[name].set()
            await asyncio.wait_for(entered[other].wait(), timeout=2)
            order.append(("finish", name))
            return ToolResult(status="ok", kind="control", data=args)
        return control_tool(name, invoke)

    runtime, _model, events = make_runtime([
        tool_turn(("a", "read_a", {"value": "A"}), ("b", "read_b", {"value": "B"})), text_turn("完成")],
        tools={"read_a": reader("read_a", "read_b"), "read_b": reader("read_b", "read_a")})
    await runtime.run_agent()
    assert {tuple(item) for item in order[:2]} == {("start", "read_a"), ("start", "read_b")}
    results = [payload for kind, payload, _ in events if kind == "tool.result"]
    assert len(results) == runtime.tool_count == 2
    assert {item["tool_call_id"] for item in results} == {"a", "b"}


@pytest.mark.asyncio
async def test_last_allowed_model_turn_has_no_tool_schemas(make_runtime):
    tool = control_tool("fixture_read", lambda args: ToolResult(status="ok", kind="control", data=args))
    runtime, model, _events = make_runtime([
        tool_turn(("a", "fixture_read", {"value": "一"})),
        tool_turn(("b", "fixture_read", {"value": "二"})), text_turn("完成")], tools={tool.name: tool})
    result = await runtime.run_agent(max_turns=3)
    assert result["stopped"] == "completed"
    assert all(item["tools"] for item in model.inputs[:-1])
    assert model.inputs[-1]["tools"] == []
    assert runtime.tool_count == 2


@pytest.mark.asyncio
async def test_final_response_margin_uses_observed_model_time_without_extending_deadline(make_runtime):
    runtime, model, _events = make_runtime([text_turn("基于已有资料收尾。")])
    deadline = time.monotonic() + 40
    runtime.context.deadline = deadline
    runtime.model_duration_seconds["root"] = 25
    await runtime.run_agent()
    assert model.inputs[0]["tools"] == []
    assert runtime.context.deadline == deadline
    assert runtime.root_content == "基于已有资料收尾。"


@pytest.mark.asyncio
async def test_successful_model_request_records_actual_budget_duration(make_runtime, monkeypatch):
    from backend.agent_runtime import model as model_module
    from types import SimpleNamespace
    clock = [100.0]
    async def advance_clock(_turn, _chunk):
        clock[0] = 125.0
    runtime, _model, _events = make_runtime([text_turn("完成")], after_chunk=advance_clock)
    monkeypatch.setattr(model_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    await runtime.run_agent()
    assert runtime.model_duration_seconds == {"root": 25.0}


@pytest.mark.asyncio
async def test_tool_call_without_offered_tools_is_a_protocol_error(make_runtime):
    called = []
    tool = control_tool("fixture_read", lambda args: called.append(args))
    runtime, model, _events = make_runtime([tool_turn(("late", "fixture_read", {"value": "一"}))],
                                         tools={tool.name: tool})
    with pytest.raises(ModelProtocolError, match="model_unrequested_tool_call"):
        await runtime.run_agent(max_turns=1)
    assert model.inputs[0]["tools"] == [] and called == []


@pytest.mark.asyncio
async def test_length_continuation_keeps_prior_history_and_joins_at_exact_character(make_runtime):
    prefix, suffix = "原文 42.12 的句子尚未", "结束，h_abcdef 也要保留。"
    runtime, model, _events = make_runtime([text_turn(prefix, finish="length"), text_turn(suffix)])
    result = await runtime.run_agent(max_turns=2)
    assert result["summary"] == runtime.root_content == prefix + suffix
    second = model.inputs[1]["messages"]
    assert second[:len(model.inputs[0]["messages"])] == model.inputs[0]["messages"]
    assert {"role": "assistant", "content": prefix} in second
    assert second[-1]["role"] == "user"


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["stop", "length"])
async def test_instruction_arriving_during_output_is_in_next_model_history(make_runtime, finish):
    instruction = "保留 12.345 原值；新增要求原文 h_xyz"

    async def after_chunk(turn, index):
        if turn == index == 0:
            assert runtime.stages["root"] == "model_response"
            runtime.instruct(instruction, "followup")
            runtime.instruct(instruction, "followup")

    runtime, model, _events = make_runtime([text_turn("已流出的正文", finish=finish), text_turn("补充回答"),
                                          text_turn("不应延迟到第三轮")],
                                         after_chunk=after_chunk)
    await runtime.run_agent(max_turns=3)
    second = model.inputs[1]["messages"]
    assert {"role": "assistant", "content": "已流出的正文"} in second
    assert second.count({"role": "user", "content": instruction}) == 1
    assert runtime.applied_instructions == {"followup"}
    assert len(model.inputs) == 2


@pytest.mark.asyncio
async def test_instruction_during_tool_execution_preserves_tool_response_order(make_runtime):
    instruction = "把区间明确写为 2026-01-02 至 2026-02-03"

    async def invoke(args):
        assert runtime.stages["root"] == "tool_execution"
        runtime.instruct(instruction, "tool-boundary")
        return ToolResult(status="ok", kind="control", data=args)

    tool = control_tool("fixture_read", invoke)
    runtime, model, _events = make_runtime([
        tool_turn(("read", tool.name, {"value": "已获取"})), text_turn("完成")], tools={tool.name: tool})
    await runtime.run_agent()
    second = model.inputs[1]["messages"]
    result_index = next(index for index, item in enumerate(second) if item.get("tool_call_id") == "read")
    assert second[result_index + 1] == {"role": "user", "content": instruction}


def test_loop_stays_small_and_does_not_import_retired_answer_patches():
    source = Path(inspect.getfile(loop)).read_text(encoding="utf-8")
    assert len(source.splitlines()) <= 250
    forbidden = {"completeness", "grounding", "presentation", "fact_answer", "permissions", "agent2", "tools"}
    for node in ast.walk(ast.parse(source)):
        names = [node.module or ""] if isinstance(node, ast.ImportFrom) else (
            [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
        assert all(not forbidden.intersection(name.split(".")) for name in names)
