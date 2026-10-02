"""One bounded model attempt on a frozen snapshot, with no forecast fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from backend.research.prediction_contract import (
    DirectionForecastPayload,
    DrawdownForecastPayload,
    ForecastContext,
    ForecastResult,
    PredictionType,
    parse_utc,
)
from backend.utils.llm_json import _extract_json


FORECAST_TIMEOUT_SECONDS = 60.0
FORECAST_INPUT_TOKEN_LIMIT = 4000
FORECAST_MIN_OUTPUT_TOKENS = 2048
FORECAST_DEFAULT_OUTPUT_TOKENS = 4096
_PARAMETER_NAMES = {
    "temperature", "top_p", "seed", "max_tokens", "max_completion_tokens",
    "max_retries", "request_timeout", "timeout", "reasoning_effort",
}
_USAGE_NAMES = {
    "input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens",
    "reasoning_tokens", "reasoning", "cache_read", "cache_creation", "cached_tokens",
    "audio", "audio_tokens", "accepted_prediction_tokens", "rejected_prediction_tokens",
    "input_token_details", "output_token_details", "prompt_tokens_details", "completion_tokens_details",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_parameters(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item for key, item in value.items()
        if key in _PARAMETER_NAMES
        and (
            item is None or isinstance(item, (bool, int, float)) or item == "unknown"
            or (key == "reasoning_effort" and item in {"none", "minimal", "low", "medium", "high", "xhigh", "max"})
        )
    }


def _call_metadata(llm: Any) -> dict[str, Any]:
    # This getter reads the selected instance; querying get_llm_config would rotate it.
    from backend.llm_config import get_llm_call_metadata

    selected = get_llm_call_metadata(llm)
    return {
        "endpoint_alias": selected.get("endpoint_alias", "unknown"),
        "configured_model": selected.get("configured_model", "unknown"),
        "request_parameters": _safe_parameters(selected.get("request_parameters")),
        "submitted_parameters": _safe_parameters(selected.get("submitted_parameters")),
        "actual_model": "unknown",
        "model_confirmed": False,
        "finish_reason": "unknown",
        "usage": {},
        "provider_parameters": {"temperature": "unknown", "top_p": "unknown", "seed": "unknown"},
    }


def _safe_usage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if key not in _USAGE_NAMES:
            continue
        if isinstance(item, dict):
            result[key] = _safe_usage(item)
        elif isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item):
            result[key] = item
    return result


def _response_metadata(response: Any, metadata: dict[str, Any]) -> None:
    reported = getattr(response, "response_metadata", None)
    reported = reported if isinstance(reported, dict) else {}
    actual_model = reported.get("model_name") or reported.get("model")
    if isinstance(actual_model, str) and actual_model.strip() and "://" not in actual_model:
        metadata["actual_model"] = actual_model.strip()[:160]
        metadata["model_confirmed"] = True
    finish_reason = reported.get("finish_reason") or reported.get("stop_reason")
    if isinstance(finish_reason, str):
        metadata["finish_reason"] = finish_reason[:64]
    usage = _safe_usage(reported.get("token_usage") or reported.get("usage"))
    usage.update(_safe_usage(getattr(response, "usage_metadata", None)))
    metadata["usage"] = usage
    # Values in the client config are requested values, never evidence of provider behavior.
    provider_parameters = _safe_parameters(reported.get("provider_parameters"))
    provider_parameters.update(_safe_parameters(reported.get("parameters")))
    provider_parameters.update(_safe_parameters(reported))
    metadata["provider_parameters"].update(provider_parameters)


def _exception_failure(exc: Exception) -> tuple[str, bool]:
    """Classify without storing provider messages, request URLs or credentials."""
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "llm_authentication", False
    if status in (400, 404, 405, 422):
        return "llm_configuration", False
    if status in (408, 409, 425, 429) or (isinstance(status, int) and status >= 500):
        return "llm_service_unavailable", True
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "llm_timeout", True
    if isinstance(exc, (ConnectionError, OSError)) or type(exc).__name__ in {
        "APIConnectionError", "APITimeoutError", "ConnectError", "ReadError", "RemoteProtocolError",
        "ConnectTimeout", "ReadTimeout", "PoolTimeout",
    }:
        return "llm_network", True
    if isinstance(exc, (TypeError, ValueError)):
        return "llm_configuration", False
    return "llm_call_failed", False


def _snapshot_features(snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    raw = snapshot.get("features")
    if not isinstance(raw, dict):
        return {}, []
    features, missing = {}, []
    for key, value in raw.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key):
            continue
        available = (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        ) or (isinstance(value, str) and bool(value.strip()) and len(value) <= 160)
        if available:
            features[key] = value
        else:
            missing.append(key)
    return features, missing


async def run_forecast(
    llm: Any,
    context: ForecastContext,
    snapshot: dict[str, Any],
    *,
    prediction_type: PredictionType,
    prompt: str,
    prompt_version: str,
) -> ForecastResult:
    """Run one request. The batch runner alone owns any second attempt."""
    started = time.monotonic()
    metadata: dict[str, Any] = {
        "actual_model": "unknown", "model_confirmed": False,
        "finish_reason": "unknown", "usage": {},
    }

    def result(status: str = "failed", *, code: str | None = None, retryable: bool = False,
               reason: str | None = None, **judgment: Any) -> ForecastResult:
        metadata["duration_ms"] = round((time.monotonic() - started) * 1000)
        if code:
            metadata["error_code"] = code
        return ForecastResult(
            status=status, prediction_type=prediction_type,
            reason=reason if reason is not None else (code or ""),
            error_code=code, retryable=retryable, metadata=metadata,
            prompt_version=prompt_version,
            issued_at=_utc_now().isoformat().replace("+00:00", "Z"), **judgment,
        )

    if llm is None:
        return result(code="llm_unavailable")
    try:
        metadata.update(_call_metadata(llm))
    except Exception:
        return result(code="llm_metadata_unavailable")

    submitted = metadata["submitted_parameters"]
    output_budget = submitted.get("max_completion_tokens", submitted.get("max_tokens"))
    retries = submitted.get("max_retries", getattr(llm, "max_retries", None))
    if (
        not isinstance(output_budget, int) or output_budget < FORECAST_MIN_OUTPUT_TOKENS
        or retries != 0
    ):
        return result(code="llm_configuration")
    remaining = (parse_utc(context.deadline_at) - _utc_now()).total_seconds()
    timeout = min(FORECAST_TIMEOUT_SECONDS - (time.monotonic() - started), remaining)
    if timeout <= 0:
        return result(code="issuance_deadline")

    async def attempt() -> ForecastResult:
        features, missing = _snapshot_features(snapshot)
        metadata.update({"input_features": sorted(features), "missing_features": sorted(missing)})
        last_close = features.get("last_close")
        if not isinstance(last_close, (int, float)) or last_close <= 0:
            return result(code="missing_market_data")
        required = ("realized_vol20", "max_drawdown60") if prediction_type == "drawdown" else ()
        if any(not isinstance(features.get(key), (int, float)) for key in required):
            return result(code="missing_market_data")
        if prediction_type == "direction" and not any(
            isinstance(features.get(key), (int, float)) for key in ("ma20", "rsi", "macd")
        ):
            return result(code="missing_market_data")
        try:
            as_of = parse_utc(snapshot["as_of"])
        except (KeyError, TypeError, ValueError):
            return result(code="invalid_snapshot_time")
        if as_of > parse_utc(context.knowledge_cutoff):
            return result(code="snapshot_after_cutoff")
        model_input = {
            "context": context.model_dump(mode="json"),
            "snapshot": {"as_of": snapshot["as_of"], "source": snapshot.get("source"), "features": features},
        }
        request_text = prompt + "\nFrozen input:\n" + json.dumps(model_input, ensure_ascii=False, separators=(",", ":"))
        # A conservative byte-token bound avoids claiming a tokenizer for an unconfirmed model.
        # Only one HumanMessage is sent; 32 tokens cover its role/framing overhead.
        input_bound = len(request_text.encode("utf-8")) + 32
        metadata.update({
            "input_token_upper_bound": input_bound,
            "input_token_count_method": "utf8_bytes_plus_message_overhead",
            "input_token_limit": FORECAST_INPUT_TOKEN_LIMIT,
        })
        if input_bound > FORECAST_INPUT_TOKEN_LIMIT:
            return result(code="input_budget_exceeded")

        from backend.services.llm_retry import ainvoke_with_rate_limit_retry
        from backend.services.rate_limiter import acquire_llm_token

        token_ready = await acquire_llm_token(timeout=timeout, agent_name=f"forecast_{prediction_type}")
        if not token_ready:
            return result(code="rate_limiter_timeout", retryable=True)
        response = await ainvoke_with_rate_limit_retry(
            llm, [HumanMessage(content=request_text)],
            llm_factory=None, max_attempts=1, acquire_token=False,
            agent_name=f"forecast_{prediction_type}",
        )
        _response_metadata(response, metadata)
        if metadata["finish_reason"].lower() in {"length", "max_tokens", "max_output_tokens"}:
            return result(code="output_truncated", retryable=True)
        content = getattr(response, "content", None)
        if isinstance(content, list):
            # Anthropic messages separate text and thinking blocks; only text is a final answer.
            content = "\n".join(
                block["text"] for block in content
                if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
            )
        if not isinstance(content, str):
            return result(code="invalid_json", retryable=True)
        metadata["output_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if content.count("<think>") != content.count("</think>"):
            return result(code="incomplete_thinking", retryable=True)
        parsed = _extract_json(content)
        if parsed is None:
            return result(code="invalid_json", retryable=True)
        payload_type = DirectionForecastPayload if prediction_type == "direction" else DrawdownForecastPayload
        try:
            payload = payload_type.model_validate(parsed)
        except ValidationError:
            return result(code="invalid_forecast_contract", retryable=True)
        if any(ref not in features for ref in payload.evidence_refs):
            return result(code="invalid_evidence_reference", retryable=True)
        if _utc_now() >= parse_utc(context.deadline_at):
            return result(code="issuance_deadline")
        if time.monotonic() - started >= FORECAST_TIMEOUT_SECONDS:
            return result(code="llm_timeout", retryable=True)
        return result(**payload.model_dump())

    try:
        return await asyncio.wait_for(attempt(), timeout=timeout)
    except Exception as exc:
        code, retryable = _exception_failure(exc)
        if _utc_now() >= parse_utc(context.deadline_at):
            return result(code="issuance_deadline")
        return result(code=code, retryable=retryable)
