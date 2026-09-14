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


def _parse_comparison_table(ctx, text: str) -> dict[str, dict[str, str]]:
    if not text or "Performance Comparison" not in text:
        return {}
    rows: dict[str, dict[str, str]] = {}
    for line in str(text).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("Ticker", "-", "Performance", "Notes")):
            continue
        parts = stripped.split()
        if len(parts) < 4:
            continue
        label = " ".join(parts[:-3]).strip()
        if not label:
            continue
        current = parts[-3]
        ytd = parts[-2]
        one_year = parts[-1]
        rows[label] = {"current": current, "ytd": ytd, "1y": one_year}
    return rows


def _find_row_for_ticker(ctx, ticker: str) -> dict[str, str]:
    if not ticker or not ctx.parsed:
        return {}
    ticker_u = ticker.strip().upper()

    for key, row in ctx.parsed.items():
        if isinstance(key, str) and key.strip().upper() == ticker_u:
            return row

    label = ctx.label_by_ticker.get(ticker_u)
    if isinstance(label, str) and label.strip():
        label_u = label.strip().upper()
        for key, row in ctx.parsed.items():
            if isinstance(key, str) and key.strip().upper() == label_u:
                return row

    return {}


def _parse_pct(ctx, value: str) -> float | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.upper() == "N/A":
        return None
    cleaned = cleaned.replace("%", "")
    try:
        return float(cleaned)
    except Exception:
        return None
