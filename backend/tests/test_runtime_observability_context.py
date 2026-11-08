"""长事务上下文归档与面向用户诊断的离线回归。"""
from copy import deepcopy
import json

import pytest

from backend.agent_runtime.context import dumps, prune_messages, tokens
from backend.agent_runtime.diagnostics import error_info, safe_preview, tool_summary


def transaction(index, *, call_count=1):
    calls = [{"id": f"call_{index}_{part}", "type": "function", "function": {
        "name": "fetch_url_content", "arguments": dumps({"url": f"https://example.com/{index}/{part}", "query": "context " * 100})}}
        for part in range(call_count)]
    assistant = {"role": "assistant", "content": f"研究第 {index} 轮", "reasoning_content": f"private_turn_{index}:" + "hidden " * 850,
                 "tool_calls": calls}
    results = [{"role": "tool", "tool_call_id": call["id"], "content": dumps({
        "status": "ok", "data_refs": [f"dataset_{index}_{part}"],
        "result": {"currency": "USD", "period": "2026Q3", "as_of": "2026-11-06", "text": "evidence " * 800},
    })} for part, call in enumerate(calls)]
    return [assistant, *results]


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


def test_large_reasoning_schemas_and_results_archive_old_transactions_without_losing_corrections():
    messages = [{"role": "system", "content": "保留数据的来源、单位和财期。"}, {"role": "user", "content": "分析 AAPL"}]
    for index in range(5):
        messages.extend(transaction(index))
        messages.append({"role": "user", "content": f"更正 {index}：保持财年口径，不要发送给第三方。"})
    recent = transaction(5, call_count=2)
    messages.extend(recent)
    tools = [{"type": "function", "function": {"name": "fetch_url_content", "description": "tool schema " * 250,
              "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}}}]
    before, tools_before = deepcopy(messages), deepcopy(tools)
    context_window, output_reserve = 36000, 4096
    budget = context_window - output_reserve - max(1024, context_window // 20)
    assert tokens(messages) + tokens(tools) > budget

    compact = prune_messages(messages, tools, context_window=context_window, output_reserve=output_reserve)

    assert tokens(compact) + tokens(tools) <= budget
    assert_complete_tool_pairs(compact)
    assert compact[-len(recent):] == recent
    assert compact[0] == messages[0]
    original_users = [message for message in messages if message["role"] == "user"]
    assert [message for message in compact if message in original_users] == original_users
    assert "private_turn_0" not in dumps(compact)
    archive = next(message["content"] for message in compact if "归档索引" in str(message.get("content")))
    assert "dataset_0_0" in archive and "read_evidence" in archive
    assert "不是新指令或授权" in archive
    assert messages == before and tools == tools_before


def test_archive_retains_readback_for_compact_single_ref_and_grouped_tool_results():
    messages = [{"role": "system", "content": "研究合同"}, *transaction(0, call_count=2), *transaction(1)]
    messages[2]["content"] = dumps({"truncated": True, "data_ref": "dataset_singular", "preview": "snapshot " * 1000})
    latest = deepcopy(messages[-2:])

    compact = prune_messages(messages, [], context_window=21000, output_reserve=2048)

    assert_complete_tool_pairs(compact)
    assert compact[-2:] == latest
    archive = next(message["content"] for message in compact if "归档索引" in str(message.get("content")))
    assert "dataset_singular" in archive and "dataset_0_1" in archive


def test_uncompressible_system_user_and_latest_transaction_fail_without_mutating_input():
    messages = [{"role": "system", "content": "system " * 200}, {"role": "user", "content": "纠正 " * 1000}, *transaction(0)]
    before = deepcopy(messages)

    with pytest.raises(ValueError, match="context_window_exhausted"):
        prune_messages(messages, [], context_window=5000, output_reserve=1024)

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
