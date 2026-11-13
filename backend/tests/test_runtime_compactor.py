"""上下文压缩只改模型投影，保留原始资料和协议配对。"""
import asyncio
from copy import deepcopy
import json
import math
from types import SimpleNamespace

import pytest

from backend.agent_runtime.compactor import Compactor, ContextBudgetExceeded
from backend.agent_runtime.context import tokens
from backend.agent_runtime.data import RunData
from backend.agent_runtime.envelope import ToolResult


NOTES = {"known_facts": [{"fact": "已查阅来源", "source_ids": ["1"]}],
         "unresolved_questions": ["估值待确认"], "user_requirements": ["保留原始口径"]}


class SummaryModel:
    def __init__(self, *, error=None, output=None, finish="stop"):
        self.calls = []
        self.error, self.output, self.finish = error, output, finish

    async def stream(self, messages, tools, **kwargs):
        self.calls.append((deepcopy(messages), tools, kwargs))
        if self.error:
            raise self.error
        text = self.output if self.output is not None else json.dumps(NOTES, ensure_ascii=False)
        yield {"choices": [{"delta": {"content": text[:12]}, "finish_reason": None}]}
        yield {"choices": [{"delta": {"content": text[12:]}, "finish_reason": self.finish}],
               "usage": {"prompt_tokens": 300, "completion_tokens": 30}}


@pytest.fixture
def data():
    return RunData("test", "session", "run", "研究")


@pytest.fixture
def context():
    return SimpleNamespace(guard=lambda: None, timeout=lambda seconds: min(seconds, 3.0))


def conversation(body="旧的研究分析。" * 200, tool_body="来源内容"):
    messages = [{"role": "system", "content": "保留此系统要求"},
                {"role": "user", "content": "比较企业并保留原始口径"}]
    for index in range(6):
        messages.extend([{"role": "assistant", "content": body if index < 3 else "最近的助手内容",
                          "tool_calls": [{"id": f"c{index}", "type": "function", "function": {
                              "name": "get_price_history", "arguments": "{}"}}]},
                         {"role": "tool", "tool_call_id": f"c{index}", "content": tool_body}])
        if index == 1:
            messages.append({"role": "user", "content": "追加要求：只用已公布数据"})
    return messages


def assert_pairs(messages):
    calls = [call["id"] for message in messages for call in message.get("tool_calls", [])]
    responses = [message["tool_call_id"] for message in messages if message["role"] == "tool"]
    assert sorted(calls) == sorted(responses)


@pytest.mark.asyncio
async def test_archive_registered_envelope_keeps_recent_turns_and_raw_history(data, context):
    model = SummaryModel()
    compactor = Compactor(data, model, context)
    result = ToolResult(status="ok", kind="series", data={"rows": [{"date": "2026-01-01", "close": 10}]},
                        sources=[{"title": "行情", "url": "https://example.com/price"}])
    handle = data.record("get_price_history", {}, result.data, envelope=result)
    messages = conversation(body="已收到资料", tool_body="完整行情内容 " * 300)
    for index in range(6):
        compactor.bind(f"c{index}", [handle])
    before, record_before = deepcopy(messages), deepcopy(data.records)
    available = math.ceil(tokens(messages) / .75)
    projected = await compactor.fit(messages, [], available + 1024 + tokens([]), 1024)

    assert messages == before and data.records == record_before
    assert not model.calls and len(compactor.archives) == 3
    stub = json.loads(next(message["content"] for message in projected if message.get("tool_call_id") == "c0"))
    assert stub["results"][0] == {"tool": "get_price_history", "kind": "series", "status": "ok",
                                    "handle": handle, "row_count": 1, "source_ids": ["1"]}
    assert projected[-6:] == before[-6:]
    assert_pairs(projected)


@pytest.mark.asyncio
async def test_summary_is_one_structured_stream_and_retains_all_users(data, context):
    model = SummaryModel()
    compactor = Compactor(data, model, context)
    messages = conversation()
    before = deepcopy(messages)
    available = math.ceil(tokens(messages) / .9)
    window = available + 512 + tokens([])
    projected = await compactor.fit(messages, [], window, 512)

    assert len(model.calls) == 1 and model.calls[0][1] == []
    assert model.calls[0][2]["max_tokens"] <= 512 and model.calls[0][2]["timeout"] == 3
    assert messages == before and projected[-6:] == before[-6:]
    assert [item for item in projected if item["role"] in {"system", "user"}] == [item for item in before if item["role"] in {"system", "user"}]
    assert compactor.summary == NOTES
    assert compactor.state["summary_usage"][0]["usage"]["completion_tokens"] == 30
    assert_pairs(projected)
    assert await compactor.fit(messages, [], window, 512) == projected
    assert len(model.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("model", [SummaryModel(error=RuntimeError("unavailable")),
                                   SummaryModel(output="不是 JSON"), SummaryModel(finish="length")])
async def test_failed_summary_keeps_archive_and_does_not_repeat_in_same_threshold(data, context, model):
    compactor = Compactor(data, model, context)
    messages = conversation(tool_body="原始文档内容 " * 100)
    result = ToolResult(status="ok", kind="document", data={"content": "原始文档"})
    handle = data.record("fetch_url", {}, result.data, envelope=result)
    for index in range(6):
        compactor.bind(f"c{index}", [handle])
    archived = await compactor.fit(messages, [], math.ceil(tokens(messages) / .75) + 512 + tokens([]), 512)
    assert not model.calls
    available = math.ceil(tokens(archived) / .9)
    window = available + 512 + tokens([])
    first = await compactor.fit(messages, [], window, 512)
    second = await compactor.fit(messages, [], window, 512)
    assert len(model.calls) == 1
    assert compactor.summary is None and compactor.summary_error
    assert first == second and len(compactor.archives) == 3
    assert_pairs(first)


@pytest.mark.asyncio
async def test_unregistered_text_is_not_guessed_and_latest_output_is_not_cut(data, context):
    model = SummaryModel()
    compactor = Compactor(data, model, context)
    messages = [{"role": "system", "content": "系统"}, {"role": "user", "content": "要求"},
                {"role": "assistant", "content": "最终长回答" * 1000}]
    before = deepcopy(messages)
    with pytest.raises(ContextBudgetExceeded) as error:
        await compactor.fit(messages, [], 1000, 200)
    assert error.value.required > error.value.available
    assert messages == before and not model.calls and not compactor.archives


@pytest.mark.asyncio
async def test_incomplete_old_tool_group_is_never_removed(data, context):
    messages = conversation()
    messages.pop(3)  # 第一组缺少工具响应，不能作为摘要替换单位。
    model = SummaryModel()
    compactor = Compactor(data, model, context)
    available = math.ceil(tokens(messages) / .9)
    projected = await compactor.fit(messages, [], available + 512 + tokens([]), 512)
    assert messages[2] in projected
    assert 2 not in compactor.state["summary_indices"]


@pytest.mark.asyncio
async def test_summary_timeout_falls_back_but_cancellation_propagates(data, context):
    class SlowModel:
        async def stream(self, *args, **kwargs):
            await asyncio.sleep(1)
            yield {}

    context.timeout = lambda _: .001
    messages = conversation()
    available = math.ceil(tokens(messages) / .9)
    compactor = Compactor(data, SlowModel(), context)
    assert await compactor.fit(messages, [], available + 512 + tokens([]), 512) == messages
    assert compactor.summary_error == "TimeoutError"

    def cancelled():
        raise asyncio.CancelledError()

    context.guard = cancelled
    with pytest.raises(asyncio.CancelledError):
        await compactor.fit(messages, [], available + 512 + tokens([]), 512)


@pytest.mark.asyncio
async def test_new_threshold_crossing_summarizes_new_complete_turns_with_prior_notes(data, context):
    messages = conversation()
    model = SummaryModel()
    compactor = Compactor(data, model, context)
    window = math.ceil(tokens(messages) / .9) + 512 + tokens([])
    await compactor.fit(messages, [], window, 512)
    original_indices = set(compactor.state["summary_indices"])
    messages.append({"role": "user", "content": "新增要求：注明假设"})
    messages.extend({"role": "assistant", "content": "新增研究笔记 " * 200} for _ in range(6))
    before = deepcopy(messages)
    projected = await compactor.fit(messages, [], 100_000, 512)
    window = math.ceil(tokens(projected) / .9) + 512 + tokens([])
    latest = await compactor.fit(messages, [], window, 512)
    assert len(model.calls) == 2
    assert "research_notes" in model.calls[1][0][1]["content"]
    assert set(compactor.state["summary_indices"]) > original_indices
    assert before == messages and latest[-3:] == before[-3:]
    assert all(message in latest for message in before if message["role"] == "user")
    assert_pairs(latest)
