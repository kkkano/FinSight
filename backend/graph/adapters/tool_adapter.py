# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


def build_tool_invokers(*, allowed_tools: Iterable[str]) -> dict[str, Callable[[dict[str, Any]], Any]]:
    """
    Build tool invokers for graph executor.

    The node layer only depends on this adapter and never imports legacy tool modules directly.
    """
    names = [str(n).strip() for n in (allowed_tools or []) if str(n).strip()]
    if not names:
        return {}

    try:  # pragma: no cover - runtime dependency path
        from backend.langchain_tools import get_tool_by_name
    except Exception:
        logger.exception("tool adapter failed to import registry")
        return {}

    invokers: dict[str, Callable[[dict[str, Any]], Any]] = {}
    for name in names:
        tool = get_tool_by_name(name)
        if not tool:
            continue
        invokers[name] = lambda inputs, _tool=tool: _tool.invoke(inputs)

    return invokers


__all__ = ["build_tool_invokers"]

