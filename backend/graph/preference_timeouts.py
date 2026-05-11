# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


MIN_USER_TIMEOUT_SECONDS = 30.0
MAX_USER_TIMEOUT_SECONDS = 1200.0


def normalize_timeout_seconds(raw: Any) -> float | None:
    """Return a validated user timeout preference, or None for system default."""
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip().lower() in {"", "0", "auto", "default", "system"}:
        return None
    try:
        value = float(raw)
    except Exception:
        return None
    if value <= 0:
        return None
    return max(MIN_USER_TIMEOUT_SECONDS, min(MAX_USER_TIMEOUT_SECONDS, value))


def timeout_seconds_from_preferences(preferences: Any) -> float | None:
    if not isinstance(preferences, Mapping):
        return None
    candidates = (
        preferences.get("timeoutSeconds"),
        preferences.get("timeout_seconds"),
        preferences.get("requestTimeoutSeconds"),
        preferences.get("request_timeout_seconds"),
    )
    for candidate in candidates:
        normalized = normalize_timeout_seconds(candidate)
        if normalized is not None:
            return normalized
    timeouts = preferences.get("timeouts")
    if isinstance(timeouts, Mapping):
        for key in ("requestSeconds", "request_seconds", "seconds"):
            normalized = normalize_timeout_seconds(timeouts.get(key))
            if normalized is not None:
                return normalized
    return None


def timeout_seconds_from_ui_context(ui_context: Any) -> float | None:
    if not isinstance(ui_context, Mapping):
        return None
    return timeout_seconds_from_preferences(ui_context.get("agent_preferences"))


def timeout_seconds_from_state(state: Any) -> float | None:
    if not isinstance(state, Mapping):
        return None
    return timeout_seconds_from_ui_context(state.get("ui_context"))


def apply_preferred_timeout(default_seconds: float | int, *, state: Any = None, ui_context: Any = None) -> float:
    preferred = timeout_seconds_from_state(state)
    if preferred is None:
        preferred = timeout_seconds_from_ui_context(ui_context)
    if preferred is not None:
        return preferred
    try:
        return float(default_seconds)
    except Exception:
        return MIN_USER_TIMEOUT_SECONDS


__all__ = [
    "MAX_USER_TIMEOUT_SECONDS",
    "MIN_USER_TIMEOUT_SECONDS",
    "apply_preferred_timeout",
    "normalize_timeout_seconds",
    "timeout_seconds_from_preferences",
    "timeout_seconds_from_state",
    "timeout_seconds_from_ui_context",
]
