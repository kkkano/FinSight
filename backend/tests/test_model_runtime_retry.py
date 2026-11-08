"""只在尚未收到内容的 HTTP 429 上做有限重试，所有供应商响应均由 MockTransport 提供。"""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.agent_runtime import model
from backend.agent_runtime.config import ModelConfig
from backend.agent_runtime.model import ModelProtocolError, ModelTransport


def config():
    return ModelConfig("fixture-model", "https://models.example/v1", "fixture-only-key")


def event(item):
    return ("data: " + json.dumps(item, ensure_ascii=False) + "\n\n").encode()


def complete():
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=event({
        "choices": [{"delta": {"content": "成功回答"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
    }) + b"data: [DONE]\n\n")


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(now=0.0, sleeps=[], oversleep=0.0)

    async def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds + state.oversleep

    monkeypatch.setattr(model, "time", SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr(model, "asyncio", SimpleNamespace(**{**vars(asyncio), "sleep": sleep}))
    return state


@pytest.mark.asyncio
async def test_one_429_then_success_retries_same_payload_and_emits_visible_wait(clock):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "3"}) if len(requests) == 1 else complete()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        chunks = [chunk async for chunk in ModelTransport(config(), client=client).stream(
            [{"role": "user", "content": "查公开资料"}], [], timeout=30)]

    assert len(requests) == 2
    assert requests[0].url == requests[1].url
    assert requests[0].content == requests[1].content
    assert clock.sleeps == [3]
    assert chunks[0]["runtime_retry"]["retry_after_seconds"] == 3
    assert chunks[-1]["choices"][0]["delta"]["content"] == "成功回答"


@pytest.mark.asyncio
async def test_persistent_429_stops_after_three_attempts_and_caps_retry_after(clock):
    requests, chunks = [], []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "999"}, json={"error": "PRIVATE_PROVIDER_DETAIL"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelProtocolError, match="^model_http_429$") as error:
            async for chunk in ModelTransport(config(), client=client).stream([], [], timeout=120):
                chunks.append(chunk)

    assert len(requests) == 3 and clock.sleeps == [20, 20]
    assert [chunk["runtime_retry"]["attempt"] for chunk in chunks] == [1, 2]
    assert error.value.status == 429
    assert "PRIVATE_PROVIDER_DETAIL" not in str(error.value)


@pytest.mark.asyncio
async def test_429_does_not_wait_when_retry_cannot_fit_shared_deadline(clock):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "20"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelProtocolError, match="^model_http_429$"):
            _ = [chunk async for chunk in ModelTransport(config(), client=client).stream([], [], timeout=10)]

    assert len(requests) == 1 and clock.sleeps == []


@pytest.mark.asyncio
async def test_retry_does_not_start_new_request_after_deadline_was_exhausted_during_sleep(clock):
    clock.oversleep = 15
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "1"}) if len(requests) == 1 else complete()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelProtocolError, match="model_timeout|run_deadline_exceeded"):
            _ = [chunk async for chunk in ModelTransport(config(), client=client).stream([], [], timeout=10)]

    assert len(requests) == 1


@pytest.mark.asyncio
async def test_each_retry_request_timeout_uses_remaining_shared_budget(clock):
    requests = []

    def handler(request):
        requests.append((request, clock.now))
        if len(requests) == 1:
            clock.now += 2
            return httpx.Response(429, headers={"Retry-After": "1"})
        return complete()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=80) as client:
        _ = [chunk async for chunk in ModelTransport(config(), client=client).stream([], [], timeout=10)]

    assert len(requests) == 2
    for request, started_at in requests:
        configured = request.extensions["timeout"]
        assert 0 < configured["read"] <= 10 - started_at
        assert 0 < configured["connect"] <= 10 - started_at


@pytest.mark.asyncio
@pytest.mark.parametrize("delta", [
    {"content": "已经交付的半段正文"},
    {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "get_stock_price", "arguments": '{"ticker":'}}]},
])
async def test_stream_interruption_after_content_or_tool_fragment_never_replays_request(clock, delta):
    requests, delivered = [], []

    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield event({"choices": [{"delta": delta, "finish_reason": None}]})
            raise httpx.ReadError("PRIVATE_PROVIDER_DETAIL")

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Interrupted())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelProtocolError, match="^model_connection_error$"):
            async for chunk in ModelTransport(config(), client=client).stream([], [], timeout=30):
                delivered.append(chunk)

    assert len(requests) == 1 and not clock.sleeps
    assert [chunk["choices"][0]["delta"] for chunk in delivered] == [delta]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 500, 503])
async def test_non_429_http_errors_are_not_retried(clock, status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelProtocolError, match=f"^model_http_{status}$"):
            _ = [chunk async for chunk in ModelTransport(config(), client=client).stream([], [], timeout=30)]

    assert len(requests) == 1 and not clock.sleeps
