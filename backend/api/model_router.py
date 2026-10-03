"""Public model metadata and an explicitly requested, bounded connection test."""
from __future__ import annotations

import asyncio
import time
import threading
from collections import deque

import httpx
from fastapi import APIRouter, HTTPException, Request

from backend.services.model_selection import (
    ModelSelectionError, model_capabilities, resolve_selection, system_models, require_model_user, default_model_id,
)

router = APIRouter(prefix="/api/models", tags=["Models"])
PROVIDER_FAILURE_MESSAGE = "连接未成功，请检查配置或稍后重试"


class ModelTestLimiter:
    def __init__(self, limit=3, window_seconds=60, clock=time.monotonic):
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.buckets = {}
        self.lock = threading.Lock()

    def allow(self, user_id: str) -> bool:
        now = self.clock()
        with self.lock:
            for key in list(self.buckets):
                bucket = self.buckets[key]
                while bucket and bucket[0] <= now - self.window_seconds:
                    bucket.popleft()
                if not bucket:
                    del self.buckets[key]
            bucket = self.buckets.setdefault(user_id, deque())
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


@router.get("")
async def list_models():
    return {"models": system_models(), "default_model_id": default_model_id()}


@router.get("/capabilities")
async def capabilities(model: str = "", base_url: str = ""):
    return model_capabilities(model[:200], base_url[:2048])


@router.post("/test")
async def test_model(request: Request):
    user = await require_model_user(request)
    limiter = getattr(request.app.state, "model_test_limiter", None)
    if limiter is None:
        limiter = ModelTestLimiter()
        request.app.state.model_test_limiter = limiter
    if not limiter.allow(str(user["user_id"])):
        raise HTTPException(status_code=429, detail="模型测试过于频繁，请稍后重试", headers={"Retry-After": "60"})
    try:
        if int(request.headers.get("content-length", "0")) > 16384:
            raise ModelSelectionError("模型配置过长")
        raw = await request.body()
        if len(raw) > 16384:
            raise ModelSelectionError("模型配置过长")
        import json
        selected = await resolve_selection(json.loads(raw))
    except (ValueError, TypeError) as exc:
        message = str(exc) if isinstance(exc, ModelSelectionError) else "模型配置无法解析"
        raise HTTPException(status_code=400, detail=message) from None

    body = {
        "model": selected.model, "max_tokens": 65536,
        "messages": [{"role": "user", "content": "这是连接测试。请仅回复：连接成功"}],
    }
    if selected.effort:
        body["reasoning_effort"] = selected.effort
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await asyncio.wait_for(client.post(
                selected.base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + selected.api_key}, json=body,
            ), timeout=60)
        elapsed = round((time.monotonic() - started) * 1000)
        if not response.is_success:
            return {"success": False, "model": selected.model, "latency_ms": elapsed,
                    "message": PROVIDER_FAILURE_MESSAGE}
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("invalid completion response")
        choices = data.get("choices") or []
        if not isinstance(choices, list) or (choices and not isinstance(choices[0], dict)):
            raise ValueError("invalid completion choices")
        message = choices[0].get("message") if choices else None
        if message is not None and not isinstance(message, dict):
            raise ValueError("invalid completion message")
        content = (message or {}).get("content")
        completed = bool(content) and choices[0].get("finish_reason") != "length"
        return {"success": completed, "model": selected.model, "latency_ms": elapsed,
                "message": "连接成功，模型已返回完整回复" if completed else PROVIDER_FAILURE_MESSAGE}
    except (httpx.HTTPError, asyncio.TimeoutError, ValueError, KeyError, TypeError):
        return {"success": False, "model": selected.model,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "message": PROVIDER_FAILURE_MESSAGE}
