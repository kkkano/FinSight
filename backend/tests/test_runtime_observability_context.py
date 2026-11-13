"""长事务上下文归档与面向用户诊断的离线回归。"""
from copy import deepcopy
import json
import math
from types import SimpleNamespace
import pytest

from backend.agent_runtime.compactor import Compactor, ContextBudgetExceeded
from backend.agent_runtime.context import dumps, tokens
from backend.agent_runtime.data import RunData
from backend.agent_runtime.diagnostics import error_info, safe_preview, tool_summary
from backend.agent_runtime.envelope import ToolResult
from backend.tests.test_agent_runtime import FakeModel, finish


def make_compactor(data):
    notes = {"known_facts": [{"fact": "已读取财报", "source_ids": ["1"]}],
             "unresolved_questions": [], "user_requirements": ["保持财年口径，不向第三方发送"]}
    return Compactor(data, FakeModel([finish(dumps(notes))]),
                     SimpleNamespace(guard=lambda: None, timeout=lambda seconds: seconds))


def transaction(data, index, *, call_count=1):
    calls, responses, handles = [], [], []
    for part in range(call_count):
        call_id = f"call_{index}_{part}"
        calls.append({"id": call_id, "type": "function", "function": {
            "name": "fetch_url_content", "arguments": dumps({"url": f"https://example.com/{index}/{part}"})}})
        raw = {"currency": "USD", "period": "2026Q3", "revenue": 16513000000, "net_income": 3320000000,
               "content": "原始财报 evidence " * 800}
        envelope = ToolResult(status="ok", kind="document", data=raw,
                             sources=[{"title": "财报", "url": f"https://example.com/{index}/{part}"}])
        handle = data.record("fetch_url_content", {"index": index, "part": part}, raw, envelope=envelope)
        handles.append(handle)
        responses.append({"role": "tool", "tool_call_id": call_id, "data_refs": [handle], "content": dumps(raw)})
    assistant = {"role": "assistant", "content": f"研究第{index}轮", "reasoning_content": f"private_turn_{index}:"+"hidden "*850,
                 "tool_calls": calls}
    return [assistant, *responses], handles


def assert_complete_tool_pairs(messages):
    pending = set()
    for message in messages:
        if message["role"] == "assistant" and message.get("tool_calls"):
            assert not pending
            pending = {call["id"] for call in message["tool_calls"]}
        elif message["role"] == "tool":
            assert message["tool_call_id"] in pending
            pending.remove(message["tool_call_id"])
        else:
            assert not pending
    assert not pending


@pytest.mark.asyncio
async def test_large_reasoning_schemas_and_results_archive_old_transactions_without_losing_corrections():
    data = RunData("u", "s", "r", "财报")
    compactor = make_compactor(data)
    messages = [{"role": "system", "content": "保留来源、单位与财期"}, {"role": "user", "content": "分析 AAPL"}]
    all_handles = []
    for index in range(6):
        block, handles = transaction(data, index, call_count=2 if index == 5 else 1)
        messages.extend(block)
        all_handles.extend(handles)
        messages.append({"role": "user", "content": f"更正{index}：保持财年口径，不要发送给第三方。"})
    tools = [{"type": "function", "function": {"name": "fetch_url_content", "description": "tool schema " * 250,
              "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}}}]
    before, tools_before, records_before = deepcopy(messages), deepcopy(tools), deepcopy(data.records)
    available = math.ceil(tokens(messages) * .65)
    compact = await compactor.fit(messages, tools, available + tokens(tools) + 2048, 2048)
    assert tokens(compact) <= available
    assert_complete_tool_pairs(compact)
    assert compact[-10:] == [{k:v for k,v in message.items() if k != "data_refs"} for message in messages[-10:]]
    assert [m for m in compact if m["role"] in {"system", "user"}] == [m for m in messages if m["role"] in {"system", "user"}]
    assert compactor.archives and messages == before and tools == tools_before and data.records == records_before
    archive = compactor.archives["call_0_0"]
    assert archive["read_with"] == "read_data" and archive["results"][0]["handle"] == all_handles[0]
    assert archive["results"][0]["source_ids"] == ["1"]
    chunks, offset = [], 0
    while True:
        page = data.read(all_handles[0], offset=offset, max_chars=8000)
        chunks.append(page["content"])
        assert page["next_offset"] == offset + len(page["content"])
        if not page["has_more"]:
            break
        offset = page["next_offset"]
    original = json.loads("".join(chunks))
    assert original["output"]["revenue"] == 16513000000 and original["output"]["net_income"] == 3320000000


@pytest.mark.asyncio
async def test_archive_retains_readback_for_single_ref_and_grouped_tool_results():
    data = RunData("u", "s", "r", "财报")
    compactor = make_compactor(data)
    messages = [{"role": "system", "content": "研究合同"}]
    groups = []
    for index in range(6):
        block, handles = transaction(data, index, call_count=2 if index == 0 else 1)
        messages.extend(block)
        groups.append(handles)
    before = deepcopy(messages)
    projected = await compactor.fit(messages, [], math.ceil(tokens(messages)/.75) + 1024 + tokens([]), 1024)
    assert_complete_tool_pairs(projected)
    assert projected[-6:] == [{k:v for k,v in message.items() if k != "data_refs"} for message in before[-6:]]
    assert compactor.archives["call_0_0"]["results"][0]["handle"] == groups[0][0]
    assert compactor.archives["call_0_1"]["results"][0]["handle"] == groups[0][1]
    assert messages == before and not compactor.model.inputs


@pytest.mark.asyncio
async def test_uncompressible_system_user_and_latest_transaction_fail_without_mutating_input():
    data = RunData("u", "s", "r", "财报")
    block, _ = transaction(data, 0)
    messages = [{"role": "system", "content": "system " * 200}, {"role": "user", "content": "纠正 " * 1000}, *block]
    before = deepcopy(messages)
    with pytest.raises(ContextBudgetExceeded) as error:
        await make_compactor(data).fit(messages, [], 5000, 1024)
    assert error.value.required > error.value.available
    assert messages == before


@pytest.mark.parametrize("field", [
    "api_key", "client_secret", "password", "authorization", "cookie", "access_token", "refresh_token",
    "token", "private_key", "reasoning_content", "reasoning", "system_prompt",
])
def test_preview_never_exposes_nested_credentials_or_private_reasoning(field):
    payload = {"result": {"rows": [{"ticker": "AAPL", field: "PRIVATE_MARKER_392", "price": 42}]},
               "usage": {"prompt_tokens": 30, "completion_tokens": 5}}
    before = deepcopy(payload)

    preview = safe_preview(payload)
    serialized = json.dumps(preview, ensure_ascii=False)

    assert "PRIVATE_MARKER_392" not in serialized
    assert "AAPL" in serialized and "42" in serialized
    assert preview["usage"] == {"prompt_tokens": 30, "completion_tokens": 5}
    assert payload == before


@pytest.mark.parametrize("query_key", ["api_key", "token", "signature", "X-Amz-Signature", "X-Amz-Security-Token"])
def test_preview_removes_url_query_credentials_userinfo_and_fragment(query_key):
    url = f"https://probe-user:URL_PASSWORD@example.org/data?symbol=AAPL&{query_key}=URL_SECRET#FRAGMENT_SECRET"

    serialized = json.dumps(safe_preview({"nested": {"source_url": url}}), ensure_ascii=False)

    assert "URL_SECRET" not in serialized
    assert "URL_PASSWORD" not in serialized and "probe-user" not in serialized
    assert "FRAGMENT_SECRET" not in serialized
    assert "symbol=AAPL" in serialized and "example.org/data" in serialized


@pytest.mark.parametrize("max_chars", [500, 5000])
def test_preview_size_stays_bounded_even_when_json_escaping_expands_content(max_chars):
    payload = {"rows": [{f"field_{i}": '\\"' * 1800 for i in range(25)} for _ in range(100)],
               "nonfinite": float("nan")}

    preview = safe_preview(payload, max_chars=max_chars)
    serialized = json.dumps(preview, ensure_ascii=False, allow_nan=False)

    assert len(serialized) <= max_chars + 1000


def test_error_diagnostics_keep_actionable_capacity_reason_without_provider_secrets():
    details = error_info("analysis_capacity_insufficient", output={
        "available_memory_mb": 768, "required_memory_mb": 1408, "token": "PRIVATE_MARKER_392"})
    unknown = error_info("upstream https://user:PRIVATE_MARKER_392@example.org?token=PRIVATE_MARKER_392")

    assert "768" in details["reason"] and "1408" in details["reason"]
    assert details["recovery_action"]
    assert unknown["error_code"] == "runtime_internal_error"
    assert "PRIVATE_MARKER_392" not in dumps([details, unknown])
    assert "PRIVATE_MARKER_392" not in tool_summary({"summary": "failed https://example.org?token=PRIVATE_MARKER_392"})
