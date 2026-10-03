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
            if data is None:
                return _tool.invoke(inputs)
            schema = getattr(_tool, "args_schema", None)
            normalized = schema.model_validate(inputs).model_dump() if hasattr(schema, "model_validate") else dict(inputs)
            def fetch():
                value = _tool.invoke(inputs)
                # 新闻 registry 使用 JSON 文本，Agent 原工具使用列表；缓存统一原始数据。
                if _name == "get_company_news" and isinstance(value, str):
                    try:
                        return json.loads(value)
                    except ValueError:
                        pass
                return value
            return data.call(_name, normalized, fetch)
        invokers[name] = invoke

    return invokers


__all__ = ["build_tool_invokers"]
