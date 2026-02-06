# -*- coding: utf-8 -*-
"""
LLM retry helper

Why:
- Some free/proxy LLM endpoints enforce strict rate limits (e.g. N calls / 5 minutes).
- LangChain's built-in retries are often short backoffs and may still fail.

This module provides a conservative "wait and retry" loop for *rate limit* errors.
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import Any, Callable, Optional


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "429",
            "rate limit",
            "too many requests",
            "quota",
            "exceeded",
            "resource_exhausted",
        )
    )


async def ainvoke_with_rate_limit_retry(
    llm: Any,
    messages: list[Any],
    *,
    max_attempts: Optional[int] = None,
    sleep_seconds: Optional[float] = None,
    jitter_seconds: Optional[float] = None,
    acquire_token: bool = True,
    acquire_timeout_seconds: Optional[float] = None,
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
) -> Any:
    """
    Retry an async LLM call when we hit rate limits (429 / quota).

    Defaults (env overridable):
    - LLM_RATE_LIMIT_RETRY_MAX_ATTEMPTS=200
    - LLM_RATE_LIMIT_RETRY_SLEEP_SECONDS=310
    - LLM_RATE_LIMIT_RETRY_JITTER_SECONDS=3
    - LLM_RATE_LIMIT_RETRY_ACQUIRE_TIMEOUT_SECONDS=3600
    """
    if max_attempts is None:
        max_attempts = _env_int("LLM_RATE_LIMIT_RETRY_MAX_ATTEMPTS", 200)
    if sleep_seconds is None:
        sleep_seconds = _env_float("LLM_RATE_LIMIT_RETRY_SLEEP_SECONDS", 310.0)
    if jitter_seconds is None:
        jitter_seconds = _env_float("LLM_RATE_LIMIT_RETRY_JITTER_SECONDS", 3.0)
    if acquire_timeout_seconds is None:
        acquire_timeout_seconds = _env_float("LLM_RATE_LIMIT_RETRY_ACQUIRE_TIMEOUT_SECONDS", 3600.0)

    enabled = _env_bool("LLM_RATE_LIMIT_RETRY_ENABLED", True)
    if not enabled or max_attempts <= 1:
        return await llm.ainvoke(messages)

    acquire_fn = None
    if acquire_token:
        try:
            from backend.services.rate_limiter import acquire_llm_token  # type: ignore

            acquire_fn = acquire_llm_token
        except Exception:
            acquire_fn = None

    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        if acquire_fn is not None:
            try:
                ok = await acquire_fn(timeout=float(acquire_timeout_seconds))
                if not ok:
                    raise RuntimeError("rate_limiter_timeout")
            except Exception as exc:
                # Treat as rate-limit-like and retry.
                last_exc = exc
                if attempt >= max_attempts:
                    raise
                wait = float(sleep_seconds) + random.uniform(0, float(jitter_seconds))
                if on_retry:
                    on_retry(attempt, exc)
                await asyncio.sleep(wait)
                continue

        try:
            return await llm.ainvoke(messages)
        except Exception as exc:
            last_exc = exc
            if not is_rate_limit_error(exc) or attempt >= max_attempts:
                raise
            wait = float(sleep_seconds) + random.uniform(0, float(jitter_seconds))
            if on_retry:
                on_retry(attempt, exc)
            await asyncio.sleep(wait)

    if last_exc:
        raise last_exc
    raise RuntimeError("llm_call_failed")


__all__ = ["ainvoke_with_rate_limit_retry", "is_rate_limit_error"]
