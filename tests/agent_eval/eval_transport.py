"""评测专用协议适配与配额边界；不理解问题或改写模型输出。"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import math
import time

import httpx


def validate_temperature(value, protocol):
    if value is None:
        return None
    if protocol != "json-completions":
        raise ValueError("evaluation_temperature_requires_json_completions")
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 2:
        raise ValueError("evaluation_temperature_out_of_range")
    return value


async def json_completions(transport, messages, tools, *, max_tokens=None, tool_choice=None, temperature=None, timeout=60):
    """保留真实非流式响应，仅投影为原循环消费的协议片段。"""
    from backend.agent_runtime.model import ModelProtocolError

    payload = {"model": transport.config.model, "messages": messages, "stream": False,
               "max_tokens": max_tokens or transport.config.max_output}
    temperature = validate_temperature(temperature, "json-completions")
    if temperature is not None:
        payload["temperature"] = temperature
    if transport.config.effort:
        payload["reasoning_effort"] = transport.config.effort
    if tools:
        payload.update(tools=tools, tool_choice=tool_choice or "auto")
    elif tool_choice is not None:
        payload["tool_choice"] = tool_choice
    supplied_client = transport.client
    client = supplied_client or httpx.AsyncClient(follow_redirects=False)
    try:
        async with asyncio.timeout(timeout):
            response = await client.post(transport.config.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + transport.config.api_key}, json=payload,
                timeout=httpx.Timeout(timeout, connect=min(15, timeout)))
            if response.status_code != 200:
                raise ModelProtocolError("model_http_" + str(response.status_code), status=response.status_code)
            try:
                result = response.json()
            except ValueError:
                raise ModelProtocolError("model_invalid_response_json") from None
            if isinstance(result, dict) and result.get("error"):
                raise ModelProtocolError("model_response_error")
            if not isinstance(result, dict) or not isinstance(result.get("choices"), list) or not result["choices"]:
                raise ModelProtocolError("model_invalid_completion_json")
            choices = []
            for index, choice in enumerate(result["choices"]):
                if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                    raise ModelProtocolError("model_invalid_completion_json")
                delta = deepcopy(choice["message"])
                for position, call in enumerate(delta.get("tool_calls") or []):
                    if not isinstance(call, dict):
                        raise ModelProtocolError("model_invalid_completion_json")
                    call.setdefault("index", position)
                choices.append({"index": choice.get("index", index), "delta": delta,
                                "finish_reason": choice.get("finish_reason")})
            yield {"choices": choices, "usage": result.get("usage")}
    except (httpx.TimeoutException, TimeoutError):
        raise ModelProtocolError("model_timeout") from None
    except httpx.HTTPError:
        raise ModelProtocolError("model_connection_error") from None
    finally:
        if supplied_client is None:
            await client.aclose()


async def observe_chunks(iterator, outcome):
    """只记录数量和时限；调用方取消保持原异常，不当成 HTTP 错误。"""
    started = time.monotonic()
    outcome.update(status="running", received_chunks=0, first_chunk_seconds=None, elapsed_seconds=None)
    try:
        async for chunk in iterator:
            if outcome["received_chunks"] == 0:
                outcome["first_chunk_seconds"] = round(time.monotonic() - started, 6)
            outcome["received_chunks"] += 1
            yield chunk
        outcome["status"] = "completed"
    except asyncio.CancelledError:
        outcome["status"] = "cancelled"
        raise
    except Exception as exc:
        outcome.update(status="failed", error_code=getattr(exc, "code", type(exc).__name__))
        raise
    finally:
        outcome["elapsed_seconds"] = round(time.monotonic() - started, 6)


class EvaluationLimiter:
    """模型 namespace 共用运行级账本；根运行和财务工具仍用各题本地账本。"""
    def __init__(self, local, shared):
        self.local, self.shared = local, shared
        self._windows = {}

    def _target(self, bucket):
        return self.shared if bucket == "model" or bucket.startswith(("pace:", "provider:")) else self.local

    def slot(self, bucket, *args, **kwargs):
        return self._target(bucket).slot(bucket, *args, **kwargs)

    def reserve_window(self, bucket, *args, **kwargs):
        target = self._target(bucket)
        identity = target.reserve_window(bucket, *args, **kwargs)
        if identity is not None:
            self._windows[identity] = target
        return identity

    def settle_window(self, identity, actual):
        target = self._windows.pop(identity, self.local)
        target.settle_window(identity, actual)

    def cancel_window(self, identity):
        target = self._windows.pop(identity, self.local)
        target.cancel_window(identity)

    def __getattr__(self, name):
        return getattr(self.local, name)
