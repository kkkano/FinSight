# -*- coding: utf-8 -*-
"""
LLM retry helper

Why:
- Some free/proxy LLM endpoints enforce strict rate limits (e.g. N calls / 5 minutes).
- LangChain's built-in retries are often short backoffs and may still fail.

This module provides a conservative retry loop for rate limits and transient
transport/provider failures.
"""

from __future__ import annotations

from backend.utils.env import env_bool as _env_bool
from backend.utils.env import env_float as _env_float
from backend.utils.env import env_int as _env_int

import asyncio
import logging
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Awaitable, Callable, Collection, Mapping, Optional

from backend.llm_config import (
    AllEndpointsCoolingDown,
    EndpointConfig,
    EndpointManager,
    create_llm_for_endpoint,
    get_endpoint_manager,
    report_llm_failure,
    report_llm_success,
)
from backend.services.llm_usage import (
    TokenBudgetExceededError,
    check_token_budget,
    record_llm_attempt,
    record_llm_selection_failure,
    record_llm_usage,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMErrorClassification:
    kind: str
    code: str
    http_status: int | None
    retryable: bool
    endpoint_failure: bool


@dataclass
class LLMAttemptBudget:
    max_provider_attempts: int
    provider_attempts_used: int = 0
    rate_limit_token_acquired: bool = False

    def __post_init__(self) -> None:
        self.max_provider_attempts = max(1, min(3, int(self.max_provider_attempts)))

    @property
    def remaining(self) -> int:
        return self.max_provider_attempts - self.provider_attempts_used

    def reserve_provider_attempt(self) -> int:
        if self.remaining <= 0:
            raise RuntimeError("llm_provider_attempt_budget_exhausted")
        self.provider_attempts_used += 1
        return self.provider_attempts_used


@dataclass(frozen=True)
class LLMCallContext:
    logical_call_id: str
    stage: str
    agent: str
    layer: str
    budget: LLMAttemptBudget = field(compare=False)
    on_attempt: Callable[[Mapping[str, Any]], None] | None = field(default=None, compare=False)

    @classmethod
    def create(
        cls,
        *,
        stage: str,
        agent: str = "unattributed",
        layer: str = "unknown",
        max_provider_attempts: int = 3,
        on_attempt: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> "LLMCallContext":
        return cls(
            str(uuid.uuid4()),
            stage,
            agent,
            layer,
            LLMAttemptBudget(max_provider_attempts),
            on_attempt,
        )


def _status_from_exception(exc: BaseException) -> int | None:
    for current in _exception_chain(exc):
        for attribute in ("status_code", "status"):
            value = getattr(current, attribute, None)
            try:
                if value is not None and 100 <= int(value) <= 599:
                    return int(value)
            except (TypeError, ValueError):
                continue
    return _extract_http_status_code(_exception_chain_summary(exc))


def _exception_chain(exc: BaseException, *, max_depth: int = 4) -> list[BaseException]:
    result: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and len(result) < max_depth and id(current) not in seen:
        seen.add(id(current))
        result.append(current)
        current = current.__cause__ or current.__context__
    return result


def classify_llm_error(exc: BaseException) -> LLMErrorClassification:
    """Classify provider failures conservatively; unknown failures never retry."""
    text = _exception_chain_summary(exc).lower()
    status = _status_from_exception(exc)
    structured_codes = " ".join(
        str(getattr(item, field, "") or "").lower()
        for item in _exception_chain(exc)
        for field in ("code", "error_code", "type")
    )
    if isinstance(exc, (ValueError, KeyError)) and ("config" in text or "api key" in text or "not configured" in text):
        return LLMErrorClassification("configuration", "llm_configuration_error", status, False, False)
    if any(token in text for token in ("policy refusal", "content policy", "safety refusal")):
        return LLMErrorClassification("policy", "llm_policy_refusal", status, False, False)
    if any(code in structured_codes or code in text for code in ("insufficient_quota", "billing_hard_limit", "billing_not_active", "credit_balance_exhausted")):
        return LLMErrorClassification("quota_exhausted", "llm_quota_exhausted", status, False, False)
    if status in {401, 403} or "invalid api key" in text or "invalid token" in text:
        return LLMErrorClassification("authentication", "llm_authentication_failed", status, False, False)
    if status in {400, 404, 409, 422}:
        return LLMErrorClassification("invalid_request", "llm_invalid_request", status, False, False)
    if status == 429 or "rate limit" in text or "too many requests" in text:
        return LLMErrorClassification("rate_limit", "llm_rate_limited", status, True, True)
    if status in {408, 425} or isinstance(exc, TimeoutError) or "timed out" in text or "timeout" in text:
        return LLMErrorClassification("timeout", "llm_timeout", status, True, True)
    if status is not None and 500 <= status <= 599:
        return LLMErrorClassification("provider_5xx", "llm_provider_5xx", status, True, True)
    if any(token in text for token in ("connection reset", "remoteprotocol", "ssl eof", "name or service not known", "dns")):
        return LLMErrorClassification("transport", "llm_transport_error", status, True, True)
    return LLMErrorClassification("unknown", "llm_unknown_error", status, False, False)


def _retry_after_seconds(exc: BaseException) -> int | None:
    """Read a numeric Retry-After value from structured provider metadata."""
    for current in _exception_chain(exc):
        response = getattr(current, "response", None)
        headers = getattr(response, "headers", None) or getattr(current, "headers", None)
        if not headers:
            continue
        try:
            value = headers.get("Retry-After") or headers.get("retry-after")
            seconds = int(float(value))
        except (AttributeError, TypeError, ValueError):
            continue
        return min(300, max(0, seconds))
    return None


def _usage_or_none(response: Any) -> tuple[int | None, int | None]:
    metadata = getattr(response, "usage_metadata", None)
    if isinstance(metadata, dict) and any(key in metadata for key in ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens")):
        return int(metadata.get("input_tokens", metadata.get("prompt_tokens", 0)) or 0), int(metadata.get("output_tokens", metadata.get("completion_tokens", 0)) or 0)
    metadata = getattr(response, "response_metadata", None)
    if isinstance(metadata, dict):
        usage = metadata.get("token_usage") or metadata.get("usage")
        if isinstance(usage, dict):
            return int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0), int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    return None, None


def _emit(event: str, payload: dict[str, Any]) -> None:
    payload["event"] = event
    payload["timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    logger.info("%s", payload)


def _observe_attempt(context: LLMCallContext, payload: Mapping[str, Any]) -> None:
    observer = context.on_attempt
    if observer is None:
        return
    try:
        observer(dict(payload))
    except Exception:
        logger.debug("LLM attempt observer failed", exc_info=True)


def _filtered_endpoint_manager(
    manager: EndpointManager,
    endpoint_names: Collection[str] | None,
) -> EndpointManager:
    if endpoint_names is None:
        return manager

    requested = tuple(dict.fromkeys(str(name or "").strip() for name in endpoint_names))
    requested = tuple(name for name in requested if name)
    if not requested:
        raise ValueError("No LLM endpoint names configured")

    runtimes = {runtime.cfg.name: runtime for runtime in manager.endpoints if runtime.cfg.enabled}
    missing = tuple(name for name in requested if name not in runtimes)
    if missing:
        raise ValueError(f"Configured LLM endpoint unavailable: {','.join(missing)}")

    # 过滤视图复用全局运行时冷却和锁，但不改写全局 endpoint 集合。
    return EndpointManager(
        endpoints=[runtimes[name] for name in requested],
        fingerprint=manager.fingerprint,
        lock=manager.lock,
    )


async def ainvoke_llm(
    *,
    messages: Any,
    context: LLMCallContext,
    endpoint_manager: EndpointManager,
    client_factory: Callable[[EndpointConfig], Any],
    invoke: Callable[[Any, Any], Awaitable[Any]],
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    """Single provider-attempt state machine for one logical LLM call."""
    attempted: set[str] = set()
    last_domain: str | None = None
    endpoint_count = len([ep for ep in endpoint_manager.endpoints if ep.cfg.enabled])
    single_endpoint = endpoint_count == 1
    while context.budget.remaining > 0:
        try:
            if single_endpoint and attempted:
                endpoint = endpoint_manager.endpoints[0].cfg
            else:
                endpoint = endpoint_manager.select(
                    exclude_names=attempted,
                    prefer_different_failure_domain=last_domain,
                )
        except AllEndpointsCoolingDown as exc:
            record_llm_selection_failure()
            _emit("llm.call", {
                "logical_call_id": context.logical_call_id, "stage": context.stage, "agent": context.agent,
                "layer": context.layer, "status": "selection_failed",
                "provider_attempts_used": context.budget.provider_attempts_used,
                "error_code": exc.code, "retry_after_seconds": exc.retry_after_seconds,
            })
            raise
        client = client_factory(endpoint)
        attempt = context.budget.reserve_provider_attempt()
        started = perf_counter()
        try:
            result = await invoke(client, messages)
            prompt_tokens, completion_tokens = _usage_or_none(result)
            record_llm_usage(result, getattr(client, "model_name", endpoint.model), count_call=False)
            record_llm_attempt(model=getattr(client, "model_name", endpoint.model), status="success", duration_ms=int((perf_counter() - started) * 1000), response=result)
            attempt_payload = {
                "logical_call_id": context.logical_call_id, "stage": context.stage, "agent": context.agent, "layer": context.layer,
                "endpoint_name": endpoint.name, "provider": endpoint.provider,
                "failure_domain": endpoint.failure_domain, "model": endpoint.model,
                "attempt": attempt, "max_attempts": context.budget.max_provider_attempts, "status": "success",
                "error_kind": None, "error_code": None, "http_status": None, "retryable": False,
                "duration_ms": int((perf_counter() - started) * 1000),
                "usage_state": "reported" if prompt_tokens is not None else "not_reported",
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            }
            _emit("llm.attempt", attempt_payload)
            _observe_attempt(context, attempt_payload)
            return result
        except Exception as exc:
            classification = classify_llm_error(exc)
            record_llm_attempt(model=getattr(client, "model_name", endpoint.model), status="failed", duration_ms=int((perf_counter() - started) * 1000))
            attempt_payload = {
                "logical_call_id": context.logical_call_id, "stage": context.stage, "agent": context.agent, "layer": context.layer,
                "endpoint_name": endpoint.name, "provider": endpoint.provider,
                "failure_domain": endpoint.failure_domain, "model": endpoint.model,
                "attempt": attempt, "max_attempts": context.budget.max_provider_attempts, "status": "failed",
                "error_kind": classification.kind, "error_code": classification.code, "http_status": classification.http_status,
                "retryable": classification.retryable, "duration_ms": int((perf_counter() - started) * 1000),
                "usage_state": "unavailable_due_to_failure", "prompt_tokens": None, "completion_tokens": None,
            }
            _emit("llm.attempt", attempt_payload)
            _observe_attempt(context, attempt_payload)
            if not classification.retryable or context.budget.remaining <= 0 or (single_endpoint and attempt >= 2):
                if classification.endpoint_failure:
                    endpoint_manager.report_failure(
                        endpoint.name,
                        reason=classification.code,
                        retry_after_seconds=_retry_after_seconds(exc),
                    )
                raise
            attempted.add(endpoint.name)
            last_domain = endpoint.failure_domain
            if classification.endpoint_failure and not single_endpoint:
                endpoint_manager.report_failure(
                    endpoint.name,
                    reason=classification.code,
                    retry_after_seconds=_retry_after_seconds(exc),
                )
            if context.budget.remaining <= 0:
                raise
            await sleeper(random.uniform(0.25, 1.0))
    raise RuntimeError("llm_provider_attempt_budget_exhausted")


async def ainvoke_configured_llm(
    messages: Any,
    *,
    context: LLMCallContext,
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    request_timeout: int = 600,
    acquire_token: bool = True,
    acquire_timeout_seconds: float | None = None,
    client_transform: Callable[[Any], Any] | None = None,
    endpoint_names: Collection[str] | None = None,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    """Invoke the configured provider through the single endpoint state machine."""
    check_token_budget()
    if acquire_token and not context.budget.rate_limit_token_acquired:
        from backend.services.rate_limiter import acquire_llm_token

        timeout = (
            float(acquire_timeout_seconds)
            if acquire_timeout_seconds is not None
            else _env_float("LLM_RATE_LIMIT_RETRY_ACQUIRE_TIMEOUT_SECONDS", 15.0)
        )
        acquired = await acquire_llm_token(timeout=timeout, agent_name=context.agent)
        if not acquired:
            raise RuntimeError("llm_rate_limit_acquire_timeout")
        context.budget.rate_limit_token_acquired = True

    manager = _filtered_endpoint_manager(
        get_endpoint_manager(provider=provider, model=model),
        endpoint_names,
    )
    enabled_count = len([endpoint for endpoint in manager.endpoints if endpoint.cfg.enabled])
    allowed_attempts = min(3, max(2, enabled_count))
    context.budget.max_provider_attempts = min(context.budget.max_provider_attempts, allowed_attempts)

    def _factory(endpoint: EndpointConfig) -> Any:
        client = create_llm_for_endpoint(
            endpoint,
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=request_timeout,
        )
        return client_transform(client) if client_transform is not None else client

    return await ainvoke_llm(
        messages=messages,
        context=context,
        endpoint_manager=manager,
        client_factory=_factory,
        invoke=lambda client, payload: client.ainvoke(payload),
        sleeper=sleeper,
    )


def _exception_chain_summary(exc: BaseException, *, max_depth: int = 4) -> str:
    """Return exception types/causes without request payloads or credentials."""
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and len(parts) < max_depth and id(current) not in seen:
        seen.add(id(current))
        message = str(current).replace("\n", " ").strip()
        parts.append(f"{current.__class__.__name__}: {message[:240]}")
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)


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


def _is_transient_transport_error(exc: BaseException) -> bool:
    """Retry the same endpoint only for failures that can recover in-place."""
    text = str(exc).lower()
    status = _extract_http_status_code(text)
    if status in {408, 409, 425, 500, 502, 503, 504}:
        return True
    return any(
        token in text
        for token in (
            "service unavailable",
            "gateway timeout",
            "bad gateway",
            "connection",
            "timed out",
            "timeout",
            "ssl",
            "eof",
        )
    )


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

    # P1-5: 调用前检查单请求 token 预算（超限直接抛错，不消耗 LLM 调用）
    check_token_budget()

    enabled = _env_bool("LLM_RATE_LIMIT_RETRY_ENABLED", True)
    if not enabled or max_attempts <= 1:
        started = perf_counter()
        model = getattr(llm, "model_name", None)
        try:
            result = await llm.ainvoke(messages)
        except Exception:
            record_llm_attempt(model=model, status="failed", duration_ms=int((perf_counter() - started) * 1000))
            raise
        report_llm_success(llm)
        record_llm_usage(result, model, count_call=False)
        record_llm_attempt(
            model=model, status="success", duration_ms=int((perf_counter() - started) * 1000), response=result,
        )
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
            # P1-5: 每次重试前也检查预算（重试循环本身也在消耗 token）
            check_token_budget()
            started = perf_counter()
            result = await current_llm.ainvoke(messages)
            report_llm_success(current_llm)
            model = getattr(current_llm, "model_name", None)
            record_llm_usage(result, model, count_call=False)
            record_llm_attempt(
                model=model, status="success", duration_ms=int((perf_counter() - started) * 1000), response=result,
            )
            return result
        except TokenBudgetExceededError:
            raise  # 预算超限不重试，直接上抛
        except Exception as exc:
            last_exc = exc
            record_llm_attempt(
                model=getattr(current_llm, "model_name", None),
                status="failed",
                duration_ms=int((perf_counter() - started) * 1000),
            )
            report_llm_failure(current_llm, exc)

            retryable = (
                is_endpoint_retryable_error(exc)
                if llm_factory is not None
                else is_rate_limit_error(exc) or _is_transient_transport_error(exc)
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
                    "[LLM] Execution error retry %d/%d (agent=%s): %s details=%s",
                    attempt,
                    max_attempts,
                    agent_name or "unknown",
                    exc,
                    _exception_chain_summary(exc),
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
    "LLMCallContext",
    "LLMAttemptBudget",
    "LLMErrorClassification",
    "ainvoke_llm",
    "ainvoke_configured_llm",
    "ainvoke_with_rate_limit_retry",
    "classify_llm_error",
    "is_rate_limit_error",
    "is_endpoint_retryable_error",
]
