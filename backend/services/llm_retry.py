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
import logging
import os
import random
import re
from typing import Any, Callable, Optional

from backend.llm_config import report_llm_failure, report_llm_success

logger = logging.getLogger(__name__)


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


def _extract_http_status_code(text: str) -> int | None:
    match = re.search(r"\b([1-5]\d{2})\b", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def is_endpoint_retryable_error(exc: BaseException) -> bool:
    """
    Errors that should trigger endpoint rotation when multiple endpoints exist.

    We keep this intentionally broader than rate-limit only:
    - auth/provider routing failures on one endpoint (401/403/404)
    - transient infra failures (408/429/5xx, timeout, connection reset, ssl eof)
    """
    text = str(exc).lower()

    if is_rate_limit_error(exc):
        return True

    status = _extract_http_status_code(text)
    if status in {401, 403, 404, 408, 409, 425, 429, 500, 502, 503, 504}:
        return True

    transient_tokens = (
        "unauthorized",
        "forbidden",
        "blocked",
        "request was blocked",
        "content blocked",
        "safety",
        "policy violation",
        "authentication",
        "invalid api key",
        "invalid token",
        "no available channel",
        "service unavailable",
        "gateway timeout",
        "bad gateway",
        "connection",
        "timed out",
        "timeout",
        "ssl",
        "eof",
        "无效的令牌",
        "该令牌额度已用尽",
        "无可用渠道",
    )
    return any(token in text for token in transient_tokens)


async def ainvoke_with_rate_limit_retry(
    llm: Any,
    messages: list[Any],
    *,
    llm_factory: Optional[Callable[[], Any]] = None,
    max_attempts: Optional[int] = None,
    sleep_seconds: Optional[float] = None,
    jitter_seconds: Optional[float] = None,
    acquire_token: bool = True,
    acquire_timeout_seconds: Optional[float] = None,
    agent_name: Optional[str] = None,
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
) -> Any:
    """
    Retry an async LLM call when we hit rate limits (429 / quota).

    When *llm_factory* is provided, on a rate-limit error the loop creates a
    **new** LLM instance (bound to a different endpoint via EndpointManager
    round-robin) instead of retrying the same failed endpoint.

    *agent_name* is passed through to the rate limiter for per-agent
    guaranteed quota tracking (ADR-004).

    Defaults (env overridable):
    - LLM_RATE_LIMIT_RETRY_MAX_ATTEMPTS=6
    - LLM_RATE_LIMIT_RETRY_SLEEP_SECONDS=5
    - LLM_RATE_LIMIT_RETRY_JITTER_SECONDS=2
    - LLM_RATE_LIMIT_RETRY_ACQUIRE_TIMEOUT_SECONDS=3600
    """
    if max_attempts is None:
        max_attempts = _env_int("LLM_RATE_LIMIT_RETRY_MAX_ATTEMPTS", 6)
    if sleep_seconds is None:
        sleep_seconds = _env_float("LLM_RATE_LIMIT_RETRY_SLEEP_SECONDS", 5.0)
    if jitter_seconds is None:
        jitter_seconds = _env_float("LLM_RATE_LIMIT_RETRY_JITTER_SECONDS", 2.0)
    if acquire_timeout_seconds is None:
        acquire_timeout_seconds = _env_float("LLM_RATE_LIMIT_RETRY_ACQUIRE_TIMEOUT_SECONDS", 3600.0)

    enabled = _env_bool("LLM_RATE_LIMIT_RETRY_ENABLED", True)
    if not enabled or max_attempts <= 1:
        result = await llm.ainvoke(messages)
        report_llm_success(llm)
        return result

    acquire_fn = None
    if acquire_token:
        try:
            from backend.services.rate_limiter import acquire_llm_token  # type: ignore

            acquire_fn = acquire_llm_token
        except Exception:
            acquire_fn = None

    current_llm = llm
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        if acquire_fn is not None:
            try:
                ok = await acquire_fn(timeout=float(acquire_timeout_seconds), agent_name=agent_name)
                if not ok:
                    raise RuntimeError("rate_limiter_timeout")
            except Exception as exc:
                # Treat as rate-limit-like and retry.
                last_exc = exc
                if attempt >= max_attempts:
                    raise
                wait = float(sleep_seconds) + random.uniform(0, float(jitter_seconds))
                logger.info(
                    "[LLM] Rate limit token acquire retry %d/%d (agent=%s): %s",
                    attempt, max_attempts, agent_name or "unknown", exc,
                )
                if on_retry:
                    on_retry(attempt, exc)
                await asyncio.sleep(wait)
                continue

        try:
            result = await current_llm.ainvoke(messages)
            report_llm_success(current_llm)
            return result
        except Exception as exc:
            last_exc = exc
            report_llm_failure(current_llm, exc)

            retryable = (
                is_endpoint_retryable_error(exc)
                if llm_factory is not None
                else is_rate_limit_error(exc)
            )

            if not retryable or attempt >= max_attempts:
                raise

            # Log with appropriate level
            if is_rate_limit_error(exc):
                logger.info(
                    "[LLM] Rate limit retry %d/%d (agent=%s): %s",
                    attempt, max_attempts, agent_name or "unknown", exc,
                )
            else:
                logger.warning(
                    "[LLM] Execution error retry %d/%d (agent=%s): %s",
                    attempt, max_attempts, agent_name or "unknown", exc,
                )

            # Rotate to next endpoint when factory is available
            if llm_factory is not None:
                try:
                    current_llm = llm_factory()
                except Exception:
                    pass  # factory failed; keep current_llm for next attempt

            # Multi-endpoint rotation: small delay on first cycle through
            # endpoints, then ramp up backoff on subsequent cycles to let
            # external rate-limit windows expire.
            if llm_factory is not None:
                # After first full cycle (attempt > num_endpoints estimate),
                # add progressive backoff so we wait for recovery.
                if attempt <= 3:
                    wait = 0.8 + random.uniform(0, 0.5)
                else:
                    wait = float(sleep_seconds) * 0.6 + random.uniform(0, float(jitter_seconds))
            else:
                wait = float(sleep_seconds) + random.uniform(0, float(jitter_seconds))
            if on_retry:
                on_retry(attempt, exc)
            if wait > 0:
                await asyncio.sleep(wait)

    if last_exc:
        raise last_exc
    raise RuntimeError("llm_call_failed")


__all__ = [
    "ainvoke_with_rate_limit_retry",
    "is_rate_limit_error",
    "is_endpoint_retryable_error",
]
