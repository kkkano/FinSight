# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def should_use_deepagents(facets: dict[str, Any], ui_context: dict[str, Any] | None = None) -> bool:
    context = ui_context if isinstance(ui_context, dict) else {}
    if not _truthy(context.get("enable_deepagents")):
        return False
    needs = facets.get("analysis_need") if isinstance(facets.get("analysis_need"), list) else []
    return str(facets.get("primary_task") or "") == "deep_research" or "workspace" in needs or "multi_step" in needs


def build_deepagents_context(facets: dict[str, Any], ui_context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = ui_context if isinstance(ui_context, dict) else {}
    enabled = should_use_deepagents(facets, context)
    thread_id = str(context.get("thread_id") or "anonymous").strip() or "anonymous"
    return {
        "enabled": enabled,
        "workspace_scope": f"thread:{thread_id}",
        "facets": dict(facets),
        "mode": "explicit" if enabled else "off",
    }
