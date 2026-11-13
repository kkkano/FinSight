# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import json
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
    from backend.graph.execution.request_data import current_request_data
    data = current_request_data()
    for name in names:
        tool = get_tool_by_name(name)
        if not tool:
            continue
        def invoke(inputs, _tool=tool, _name=name):
            def fetch():
                value = _tool.invoke(inputs)
                # registry 的 JSON 文本在执行入口还原；采集、业务错误和 Agent 共享同一种结构。
                if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
                    try:
                        return json.loads(value)
                    except ValueError:
                        pass
                return value
            if data is None:
                return fetch()
            schema = getattr(_tool, "args_schema", None)
            normalized = schema.model_validate(inputs).model_dump() if hasattr(schema, "model_validate") else dict(inputs)
            return data.call(_name, normalized, fetch)
        invokers[name] = invoke

    return invokers


__all__ = ["build_tool_invokers"]
