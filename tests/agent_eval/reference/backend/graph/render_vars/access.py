# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/synthesize.py 的 _stub_render_vars（WP3 Task4，零行为变更）。
from __future__ import annotations

import json
import os
import re
from typing import Any

from backend.graph.executor import summarize_selection
from backend.graph.json_utils import json_dumps_safe
from backend.graph.state import GraphState
from backend.graph.render_vars.model import RenderVars


def _get_tool_output(ctx, tool_name: str) -> Any:
    if not isinstance(ctx.step_results, dict) or not ctx.step_results:
        return None
    for step_id, item in ctx.step_results.items():
        if not isinstance(item, dict):
            continue
        output = item.get("output")
        if isinstance(output, dict) and output.get("skipped"):
            continue
        step = ctx.step_index.get(step_id) or {}
        if step.get("kind") == "tool" and step.get("name") == tool_name:
            return output
    return None


def _get_agent_output(ctx, agent_name: str) -> dict[str, Any] | None:
    """Read a successful agent's output dict from step_results."""
    if not isinstance(ctx.step_results, dict) or not ctx.step_results:
        return None
    for step_id, item in ctx.step_results.items():
        if not isinstance(item, dict):
            continue
        output = item.get("output")
        if isinstance(output, dict) and output.get("skipped"):
            continue
        step = ctx.step_index.get(step_id) or {}
        if step.get("kind") == "agent" and step.get("name") == agent_name:
            return output if isinstance(output, dict) else None
    return None
