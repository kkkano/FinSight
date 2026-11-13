# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any


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
    focus = current_thread_focus(memory_context)
    report = current_report_context(memory_context)

    payload: dict[str, Any] = {}
    if focus:
        payload["current_thread_focus"] = focus
    if report:
        payload["current_report"] = report
    return payload


__all__ = [
    "current_report_context",
    "current_thread_focus",
    "prompt_memory_context",
]
