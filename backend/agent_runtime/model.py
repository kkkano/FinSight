"""原生工具调用和真实 SSE；对外输出后绝不透明拼接另一端点。"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import AsyncIterator

import httpx

from .config import ModelConfig
from .context import tokens


class ModelProtocolError(RuntimeError):
    def __init__(self, code: str, *, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


class ModelTransport:
    def __init__(self, config: ModelConfig, *, client: httpx.AsyncClient | None = None):
        self.config = config
        self.client = client
        self.last_provider_error: dict | None = None

    async def stream(self, messages: list[dict], tools: list[dict], *,
                     max_tokens: int | None = None, tool_choice=None,
                     timeout: float = 60) -> AsyncIterator[dict]:
        payload = {"model": self.config.model, "messages": messages, "stream": True,
                   "max_tokens": max_tokens or self.config.max_output,
                   "stream_options": {"include_usage": True}}
        if self.config.effort:
            payload["reasoning_effort"] = self.config.effort
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        elif tool_choice is not None:
            payload["tool_choice"] = tool_choice
        client = self.client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(15, timeout)),
                                                 follow_redirects=False)
        try:
            deadline = time.monotonic() + timeout
            for attempt in range(3):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ModelProtocolError("model_timeout")
                retry_after = None
                async with asyncio.timeout(remaining), client.stream("POST", self.config.base_url.rstrip("/") + "/chat/completions",
                                         headers={"Authorization": "Bearer " + self.config.api_key},
                                         json=payload, timeout=httpx.Timeout(remaining, connect=min(15, remaining))) as response:
                    if response.status_code == 429 and attempt < 2:
                        from .diagnostics import clean_text
                        try:
                            await response.aread()
                            error = response.json().get("error", {})
                            self.last_provider_error = {"status": 429, "code": clean_text(str(error.get("code") or ""), 80),
                                "message": clean_text(str(error.get("message") or ""), 300).replace(self.config.api_key, "[hidden]")}
                        except (ValueError, AttributeError):
                            self.last_provider_error = {"status": 429}
                        try:
                            retry_after = float(response.headers.get("Retry-After", str(10 * (attempt + 1))))
                        except ValueError:
                            retry_after = 10 * (attempt + 1)
                        retry_after = max(1.0, min(20.0, retry_after))
                        if deadline - time.monotonic() < retry_after + 5:
                            raise ModelProtocolError("model_http_429", status=429)
                    elif response.status_code != 200:
                        # 只重试本次尚未收到正文/工具片段的429；不换端点、不重放已流出的内容。
                        raise ModelProtocolError("model_http_" + str(response.status_code), status=response.status_code)
                    else:
                        data_lines: list[str] = []
                        async for line in response.aiter_lines():
                            if line.startswith("data:"):
                                data_lines.append(line[5:].lstrip())
                                continue
                            if line != "" or not data_lines:
                                continue
                            raw = "\n".join(data_lines)
                            data_lines = []
                            if raw.strip() == "[DONE]":
                                return
                            try:
                                item = json.loads(raw)
                            except ValueError:
                                raise ModelProtocolError("model_invalid_stream_json") from None
                            if item.get("error"):
                                raise ModelProtocolError("model_stream_error")
                            yield item
                        if data_lines:
                            raw = "\n".join(data_lines)
                            if raw.strip() != "[DONE]":
                                try:
                                    yield json.loads(raw)
                                except ValueError:
                                    raise ModelProtocolError("model_invalid_stream_json") from None
                        return
                if retry_after is not None:
                    yield {"runtime_retry": {"reason": "模型服务繁忙，正在等待后重试。", "retry_after_seconds": retry_after, "attempt": attempt + 1}}
                    await asyncio.sleep(retry_after)
        except (httpx.TimeoutException, TimeoutError):
            raise ModelProtocolError("model_timeout") from None
        except httpx.HTTPError:
            raise ModelProtocolError("model_connection_error") from None
        finally:
            if self.client is None:
                await client.aclose()


_CAPABILITIES: dict[str, tuple[float, dict]] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def cached_tool_capability(config: ModelConfig) -> dict | None:
    cached = _CAPABILITIES.get(config.identity())
    return dict(cached[1]) if cached and cached[0] > time.monotonic() else None


async def verify_tool_capability(transport: ModelTransport, *, timeout: float = 60) -> dict:
    key = transport.config.identity()
    cached = cached_tool_capability(transport.config)
    if cached:
        return cached
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        cached = cached_tool_capability(transport.config)
        if cached:
            return cached
        schema = {"type": "function", "function": {"name": "capability_probe",
                  "description": "Synthetic no-op. No data access or side effects.",
                  "parameters": {"type": "object", "properties": {"value": {"type": "integer"}},
                                 "required": ["value"], "additionalProperties": False}}}
        calls: dict[int, dict] = {}
        finish = None
        usage = {}
        async with asyncio.timeout(timeout):
            async for chunk in transport.stream(
                [{"role": "user", "content": "Call capability_probe with value=7. This is a synthetic compatibility test."}],
                [schema], max_tokens=1024,
                tool_choice="auto", timeout=timeout,
            ):
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices", []):
                    finish = choice.get("finish_reason") or finish
                    for call in (choice.get("delta") or {}).get("tool_calls") or []:
                        accumulated = calls.setdefault(call.get("index", 0), {"name": "", "arguments": "", "id": ""})
                        function = call.get("function") or {}
                        accumulated["name"] += function.get("name") or ""
                        accumulated["arguments"] += function.get("arguments") or ""
                        accumulated["id"] += call.get("id") or ""
        valid = False
        for call in calls.values():
            try:
                valid |= call["name"] == "capability_probe" and bool(call["id"]) and json.loads(call["arguments"]) == {"value": 7}
            except ValueError:
                pass
        if not valid:
            if finish == "length":
                raise ModelProtocolError("model_probe_inconclusive")
            raise ModelProtocolError("model_tool_calling_unsupported")
        result = {"native_tool_calls": True, "streaming": True, "streaming_tool_calls": True,
                  "verified": True, "model": transport.config.model, "probe_usage": usage}
        _CAPABILITIES[key] = (time.monotonic() + 3600, result)
        if len(_CAPABILITIES) > 256:
            oldest = next(iter(_CAPABILITIES))
            _CAPABILITIES.pop(oldest, None)
            _LOCKS.pop(oldest, None)
        return dict(result)



class BudgetedModel:
    def __init__(self, runtime, spec):
        self.runtime, self.spec = runtime, spec
        self.target = spec.model or runtime.model
        self.config = self.target.config

    async def stream(self, messages, tools, **kwargs):
        rt, usage, reservation, started_network, finished = self.runtime, None, None, False, False
        started, status = time.monotonic(), "error"
        amount = await rt.budget.reserve(tokens(messages) + tokens(tools) + kwargs.get("max_tokens", self.config.max_output))
        try:
            async with rt.limiter.slot("model", rt.context.owner,
                    max(1, int(os.getenv("FINSIGHT_AGENT_MODEL_CONCURRENCY", "2"))),
                    timeout=rt.context.remaining_seconds, ttl=rt.context.remaining_seconds + 15):
                spacing = max(0, float(os.getenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")))
                while spacing and await asyncio.to_thread(rt.limiter.reserve_window,
                        "pace:" + self.config.provider_identity(), 0, maximum=1, requests=1, window=spacing) is None:
                    rt.context.guard()
                    await asyncio.sleep(min(1, rt.context.remaining_seconds))
                reservation = await asyncio.to_thread(rt.limiter.reserve_window,
                    "provider:" + self.config.provider_identity(), amount,
                    maximum=int(os.getenv("FINSIGHT_AGENT_TPM_LIMIT", "250000")),
                    requests=int(os.getenv("FINSIGHT_AGENT_RPM_LIMIT", "30")))
                if reservation is None:
                    raise ModelProtocolError("provider_local_quota_exhausted")
                kwargs["timeout"] = rt.context.timeout(min(90, kwargs.get("timeout", 90)))
                started_network = True
                async for chunk in self.target.stream(messages, tools, **kwargs):
                    rt.context.guard()
                    usage = chunk.get("usage") or usage
                    finished |= any(choice.get("finish_reason") is not None for choice in chunk.get("choices", []))
                    yield chunk
                if not finished:
                    raise ModelProtocolError("model_incomplete_response")
                status = "success"
        finally:
            if status == "success":
                rt.model_duration_seconds[self.spec.agent_id] = time.monotonic() - started
            prompt, completion = int((usage or {}).get("prompt_tokens", 0)), int((usage or {}).get("completion_tokens", 0))
            actual = prompt + completion if usage is not None else None if started_network else 0
            await rt.budget.settle(amount, actual)
            if reservation is not None:
                await asyncio.to_thread(rt.limiter.settle_window, reservation, actual)
            if started_network:
                from backend.services.llm_usage import LLMAttribution
                rt.context.usage.add(self.config.model, prompt, completion)
                rt.context.usage.add_attributed_attempt(model=self.config.model, status=status,
                    duration_ms=int((time.monotonic() - started) * 1000), prompt=prompt, completion=completion,
                    attribution=LLMAttribution(agent=self.spec.role, layer="agent_runtime"), usage_reported=usage is not None)
