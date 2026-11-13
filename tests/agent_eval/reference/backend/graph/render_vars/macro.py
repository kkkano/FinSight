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
from backend.graph.render_vars.access import _get_tool_output


def _fmt_macro_tool(ctx, tool_name: str, label: str) -> list[str]:
    out = _get_tool_output(ctx, tool_name)
    if out is None:
        return []
    if tool_name == "get_authoritative_media_news" and isinstance(out, dict):
        rows = []
        for item in out.get("articles") or []:
            if not isinstance(item, dict):
                continue
            text = " ".join(
                str(item.get(key) or "")
                for key in ("title", "snippet", "url")
            ).lower()
            if "cpi" in text and ("lse:cpi" in text or "london stock exchange:cpi" in text or "capita" in text):
                continue
            rows.append(item)
        out = {**out, "articles": rows, "count": len(rows)}
    if isinstance(out, (dict, list)):
        text = json_dumps_safe(out, ensure_ascii=False)[:900]
    else:
        text = str(out).strip()[:900]
    return [f"- {label}: {text}"] if text else []
