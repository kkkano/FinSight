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
from backend.graph.render_vars.access import _get_agent_output, _get_tool_output


def _fmt_technical_snapshot(ctx) -> str:
    out = _get_tool_output(ctx, "get_technical_snapshot")
    if out is None:
        # Fallback: use technical_agent output when tool not scheduled directly
        agent_out = _get_agent_output(ctx, "technical_agent")
        if isinstance(agent_out, dict) and agent_out.get("summary"):
            return f"- {str(agent_out['summary']).strip()[:600]}"
        return "- （暂无技术指标；如需可启用 live tools）"

    if isinstance(out, str):
        try:
            out = json.loads(out)
        except Exception:
            out = {"raw": out}

    if not isinstance(out, dict):
        return f"- {str(out)[:800]}"

    if out.get("error"):
        return f"- 技术指标不可用：{out.get('error')}（points={out.get('points','N/A')}）"

    close = out.get("close")
    ma20 = out.get("ma20")
    ma50 = out.get("ma50")
    ma200 = out.get("ma200")
    rsi14 = out.get("rsi14")
    rsi_state = out.get("rsi_state")
    macd = out.get("macd")
    signal = out.get("macd_signal")
    momentum = out.get("momentum")
    trend = out.get("trend")
    as_of = out.get("as_of")

    lines = []
    if as_of:
        lines.append(f"- as_of: {as_of}")
    if close is not None:
        lines.append(f"- close: {close}")
    parts = []
    if ma20 is not None:
        parts.append(f"MA20 {ma20:.2f}" if isinstance(ma20, (int, float)) else f"MA20 {ma20}")
    if ma50 is not None:
        parts.append(f"MA50 {ma50:.2f}" if isinstance(ma50, (int, float)) else f"MA50 {ma50}")
    if ma200 is not None:
        parts.append(f"MA200 {ma200:.2f}" if isinstance(ma200, (int, float)) else f"MA200 {ma200}")
    if parts:
        lines.append("- " + " | ".join(parts))
    if rsi14 is not None:
        if isinstance(rsi14, (int, float)):
            lines.append(f"- RSI(14): {rsi14:.2f} ({rsi_state})")
        else:
            lines.append(f"- RSI(14): {rsi14} ({rsi_state})")
    if macd is not None and signal is not None:
        if isinstance(macd, (int, float)) and isinstance(signal, (int, float)):
            lines.append(f"- MACD: {macd:.4f} vs signal {signal:.4f} ({momentum})")
        else:
            lines.append(f"- MACD: {macd} vs signal {signal} ({momentum})")
    if trend:
        lines.append(f"- trend: {trend}")
    return "\n".join(lines) if lines else "- （技术指标为空）"
