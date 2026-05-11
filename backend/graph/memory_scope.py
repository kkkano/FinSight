# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any


def user_profile_memory(memory_context: dict[str, Any] | None) -> dict[str, Any]:
    """Return durable user preferences that are safe across conversations."""
    if not isinstance(memory_context, dict):
        return {}
    profile = memory_context.get("user_profile_memory")
    if isinstance(profile, dict):
        return {key: value for key, value in profile.items() if value is not None}

    payload: dict[str, Any] = {}
    for key in ("user_id", "risk_tolerance", "investment_style", "watchlist"):
        value = memory_context.get(key)
        if value is not None:
            payload[key] = value
    if payload:
        payload.setdefault("scope", "user_profile")
    return payload


def historical_focus_memory(memory_context: dict[str, Any] | None) -> dict[str, Any]:
    """Return user-level historical focus that must not imply current context."""
    if not isinstance(memory_context, dict):
        return {}
    historical = memory_context.get("historical_focus_memory")
    if isinstance(historical, dict):
        return {key: value for key, value in historical.items() if value is not None}

    payload: dict[str, Any] = {}
    for key in ("last_focus", "last_report", "recent_focuses"):
        value = memory_context.get(key)
        if value is not None:
            payload[key] = value
    if payload:
        payload.setdefault("scope", "legacy_user_history")
    return payload


def current_thread_focus(memory_context: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return focus persisted for the exact current thread/session."""
    if not isinstance(memory_context, dict):
        return None
    focus = memory_context.get("current_thread_focus")
    if isinstance(focus, dict):
        return focus
    return None


def current_report_context(memory_context: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a report that belongs to the current session only."""
    if not isinstance(memory_context, dict):
        return None
    report = memory_context.get("current_report")
    if isinstance(report, dict):
        return report
    focus = memory_context.get("current_thread_focus")
    if isinstance(focus, dict) and isinstance(focus.get("last_report"), dict):
        return focus["last_report"]
    return None


def prompt_memory_context(memory_context: dict[str, Any] | None) -> dict[str, Any]:
    """Build memory payload safe to expose to planner/synthesis prompts."""
    profile = user_profile_memory(memory_context)
    focus = current_thread_focus(memory_context)
    report = current_report_context(memory_context)

    payload: dict[str, Any] = {}
    if profile:
        payload["user_profile_memory"] = profile
    if focus:
        payload["current_thread_focus"] = focus
    if report:
        payload["current_report"] = report
    return payload


__all__ = [
    "current_report_context",
    "current_thread_focus",
    "historical_focus_memory",
    "prompt_memory_context",
    "user_profile_memory",
]
