# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FAILURE_STRATEGY_VERSION = "failure.v1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_failure(
    trace: dict[str, Any],
    *,
    node: str,
    stage: str,
    error: str,
    fallback: str,
    retry_attempts: int = 0,
    retryable: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Append a normalized failure record into trace.
    """
    failures = trace.get("failures") or []
    if not isinstance(failures, list):
        failures = []

    failures.append(
        {
            "schema_version": FAILURE_STRATEGY_VERSION,
            "ts": utc_now_iso(),
            "node": node,
            "stage": stage,
            "error": error,
            "fallback": fallback,
            "retryable": retryable,
            "retry_attempts": max(0, int(retry_attempts)),
            "metadata": metadata or {},
        }
    )

    trace["failure_strategy_version"] = FAILURE_STRATEGY_VERSION
    trace["failures"] = failures
    return trace


def build_runtime(
    *,
    mode: str,
    fallback: bool,
    reason: str | None = None,
    retry_attempts: int = 0,
) -> dict[str, Any]:
    payload = {
        "mode": mode,
        "fallback": bool(fallback),
        "retry_attempts": max(0, int(retry_attempts)),
        "failure_strategy_version": FAILURE_STRATEGY_VERSION,
    }
    if reason:
        payload["reason"] = reason
    return payload


__all__ = ["FAILURE_STRATEGY_VERSION", "append_failure", "build_runtime", "utc_now_iso"]

