"""非流式协议、观测和模型共享配额合同；不调用真实端点。"""
import asyncio
from copy import deepcopy
import json
import sqlite3

import httpx
import pytest

from backend.agent_runtime.config import ModelConfig
from backend.agent_runtime.limits import CapacityExceeded, LeaseLimiter
from backend.agent_runtime.model import ModelProtocolError, ModelTransport

from .eval_transport import EvaluationLimiter, json_completions, observe_chunks


@pytest.mark.asyncio
async def test_json_completions_preserves_original_text_tool_calls_and_parameters():
    messages = [{"role": "user", "content": "完整输入"},
                {"role": "assistant", "content": "前文", "reasoning_content": "private-fixture"}]
    tools = [{"type": "function", "function": {"name": "first", "parameters": {"type": "object"}}}]
    original = {"role": "assistant", "content": "原文\n<think>不剥离</think>[1]",
                "reasoning_content": "private-provider-value", "tool_calls": [
                    {"id": "call-original-1", "type": "function", "function": {"name": "first", "arguments": '{\n "value":1\n}'}},
                    {"id": "call-original-2", "index": 7, "type": "function", "function": {"name": "second", "arguments": '{}'}}]}
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert payload["messages"] == messages and payload["tools"] == tools
        assert payload["tool_choice"] == "required" and payload["max_tokens"] == 512
        assert payload["stream"] is False and "response_format" not in payload and "stream_options" not in payload
        return httpx.Response(200, json={"choices": [{"index": 0, "message": original, "finish_reason": "tool_calls"}],
                                        "usage": {"prompt_tokens": 40, "completion_tokens": 2, "total_tokens": 42}})

    untouched = deepcopy(original)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = ModelTransport(ModelConfig("fixture", "https://fixture.invalid/v1", "fixture-key"), client=client)
        chunks = [chunk async for chunk in json_completions(model, messages, tools, max_tokens=512, tool_choice="required")]
    assert len(chunks) == 1 and len(seen) == 1
    delta = chunks[0]["choices"][0]["delta"]
    expected = deepcopy(original)
    expected["tool_calls"][0]["index"] = 0
    assert delta == expected and original == untouched
    assert chunks[0]["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[0]["usage"]["total_tokens"] == 42


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,code", [
    (503, {}, "model_http_503"),
    (200, "not-json", "model_invalid_response_json"),
    (200, {"error": {"code": "fixture_failure"}}, "model_response_error"),
    (200, {"choices": []}, "model_invalid_completion_json"),
    (200, {"choices": [{"message": "invalid"}]}, "model_invalid_completion_json"),
])
async def test_json_completions_reports_http_and_json_errors_without_fallback(status, body, code):
    def handler(_request):
        return httpx.Response(status, text=body) if isinstance(body, str) else httpx.Response(status, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = ModelTransport(ModelConfig("fixture", "https://fixture.invalid/v1", "fixture-key"), client=client)
        with pytest.raises(ModelProtocolError) as caught:
            _chunks = [chunk async for chunk in json_completions(model, [], [])]
    assert caught.value.code == code


@pytest.mark.asyncio
async def test_json_completions_keeps_missing_usage_unknown():
    def handler(request):
        body = json.loads(request.content)
        assert body["tool_choice"] == "none" and "tools" not in body
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "原文"},
                                                       "finish_reason": "stop"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = ModelTransport(ModelConfig("fixture", "https://fixture.invalid/v1", "fixture-key"), client=client)
        chunks = [chunk async for chunk in json_completions(model, [], [], tool_choice="none")]
    assert chunks[0]["usage"] is None


@pytest.mark.asyncio
async def test_observer_records_counts_and_timing_without_raw_reasoning():
    async def source():
        yield {"choices": [{"delta": {"reasoning_content": "private-raw-reasoning"}}]}
        yield {"usage": {"total_tokens": 5}}

    outcome = {"model": "fixture"}
    chunks = [chunk async for chunk in observe_chunks(source(), outcome)]
    assert len(chunks) == 2 and outcome["status"] == "completed" and outcome["received_chunks"] == 2
    assert 0 <= outcome["first_chunk_seconds"] <= outcome["elapsed_seconds"]
    assert "private-raw-reasoning" not in json.dumps(outcome)


@pytest.mark.asyncio
async def test_observer_preserves_caller_timeout_cancellation():
    async def blocked():
        await asyncio.Event().wait()
        yield {}

    outcome = {}
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            async for _chunk in observe_chunks(blocked(), outcome):
                pass
    assert outcome["status"] == "cancelled" and outcome["received_chunks"] == 0
    assert outcome["first_chunk_seconds"] is None and "error_code" not in outcome


@pytest.mark.asyncio
async def test_observer_preserves_protocol_failure_and_error_code():
    async def failure():
        raise ModelProtocolError("model_http_403", status=403)
        yield {}

    outcome = {}
    with pytest.raises(ModelProtocolError):
        async for _chunk in observe_chunks(failure(), outcome):
            pass
    assert outcome["status"] == "failed" and outcome["error_code"] == "model_http_403"


@pytest.mark.asyncio
async def test_model_slots_are_shared_while_root_slots_remain_case_local(tmp_path):
    shared_path = tmp_path / "model.sqlite"
    first = EvaluationLimiter(LeaseLimiter(tmp_path / "a.sqlite"), LeaseLimiter(shared_path))
    second = EvaluationLimiter(LeaseLimiter(tmp_path / "b.sqlite"), LeaseLimiter(shared_path))
    assert first.path != second.path and first.shared.path == second.shared.path
    async with first.slot("research", "same-owner", 2, owner_max=1):
        async with second.slot("research", "same-owner", 2, owner_max=1):
            async with first.slot("model", "same-owner", 2):
                async with second.slot("model", "same-owner", 2):
                    with pytest.raises(CapacityExceeded):
                        async with first.slot("model", "same-owner", 2, timeout=0.01):
                            pass
                    with sqlite3.connect(shared_path) as connection:
                        assert connection.execute("SELECT COUNT(*) FROM runtime_leases WHERE bucket='model'").fetchone()[0] == 2


def test_model_rate_and_pace_windows_are_shared_and_settle_in_shared_store(tmp_path):
    shared_path = tmp_path / "model.sqlite"
    first = EvaluationLimiter(LeaseLimiter(tmp_path / "a.sqlite"), LeaseLimiter(shared_path))
    second = EvaluationLimiter(LeaseLimiter(tmp_path / "b.sqlite"), LeaseLimiter(shared_path))
    reservation = first.reserve_window("provider:fixture", 50, maximum=100, requests=3)
    assert reservation is not None
    assert second.reserve_window("provider:fixture", 60, maximum=100, requests=3) is None
    other = second.reserve_window("provider:fixture", 50, maximum=100, requests=3)
    assert other is not None
    first.settle_window(reservation, 10)
    assert second.reserve_window("provider:fixture", 30, maximum=100, requests=3) is not None
    second.cancel_window(other)
    assert first.reserve_window("pace:fixture", 0, maximum=1, requests=1) is not None
    assert second.reserve_window("pace:fixture", 0, maximum=1, requests=1) is None
    assert first.reserve_window("case-local", 0, maximum=1, requests=1) is not None
    assert second.reserve_window("case-local", 0, maximum=1, requests=1) is not None
