# -*- coding: utf-8 -*-
"""最终回答渲染边界。"""
from __future__ import annotations

from backend.graph.memory_snapshot import build_checkpoint_memory
from backend.graph.nodes.render_node import render_node
from backend.graph.state import GraphState


def render(state: GraphState) -> dict:
    result = render_node(state)
    memory = build_checkpoint_memory(
        state=state,
        rendered_artifacts=result.get("artifacts"),
    )
    if memory is not None:
        result["memory_context"] = memory
    return result

__all__ = ["render"]
