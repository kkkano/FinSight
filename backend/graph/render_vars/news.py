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


def _fmt_company_news_summary(ctx) -> str:
    out = _get_tool_output(ctx, "get_company_news")
    if out is None:
        return "- （暂无新闻数据）"

    if isinstance(out, str):
        try:
            out = json.loads(out)
        except Exception:
            out = {"raw": out}

    if isinstance(out, dict):
        maybe = out.get("items") or out.get("news") or out.get("results")
        if isinstance(maybe, list):
            out = maybe

    items: list[dict[str, Any]] = []
    if isinstance(out, list):
        for item in out[:10]:
            if isinstance(item, dict):
                items.append(item)

    if not items:
        return "- （未获取到相关新闻）"

    lines: list[str] = []
    for item in items[:6]:
        title = str(item.get("title") or item.get("headline") or "(untitled)").strip()
        url = str(item.get("url") or item.get("link") or item.get("article_url") or "").strip()
        source = str(item.get("source") or item.get("publisher") or "").strip()
        ts = str(item.get("published_date") or item.get("published_at") or item.get("datetime") or item.get("date") or "").strip()
        meta = " / ".join([x for x in [source, ts[:10] if ts else ""] if x])
        if url.startswith(("http://", "https://")):
            lines.append(f"- [{title}]({url})" + (f"（{meta}）" if meta else ""))
        else:
            lines.append(f"- {title}" + (f"（{meta}）" if meta else ""))

    return "\n".join(lines) if lines else "- （未获取到相关新闻）"
