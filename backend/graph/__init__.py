# -*- coding: utf-8 -*-
"""
LangGraph runtime for FinSight.

This package is the single orchestration entry point going forward.
Phase 1 builds a minimal graph skeleton and runner; later phases will
replace legacy router/supervisor flows behind this entry.
"""

from importlib import import_module
from typing import Any

from backend.graph.checkpointer import get_graph_checkpointer_info

_RUNNER_EXPORTS = {
    "GraphRunner",
    "aget_graph_runner",
    "get_graph_runner",
    "graph_runner_ready",
    "reset_graph_runner",
}


def __getattr__(name: str) -> Any:
    """按需导出 runner API，避免导入 graph 子模块时加载完整运行图。"""
    if name not in _RUNNER_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("backend.graph.runner"), name)
    globals()[name] = value
    return value

__all__ = [
    "GraphRunner",
    "aget_graph_runner",
    "get_graph_runner",
    "graph_runner_ready",
    "reset_graph_runner",
    "get_graph_checkpointer_info",
]
