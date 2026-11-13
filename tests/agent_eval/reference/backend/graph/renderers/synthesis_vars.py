# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/chat_renderer.py（WP3 Task1，零行为变更）。
from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import quote_plus

from backend.agents.profiles import profile
from backend.graph.state import GraphState
from backend.graph.renderers.shared import _parse_jsonish, _step_outputs


def _render_vars(state: GraphState) -> dict[str, str]:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    raw = artifacts.get("render_vars") if isinstance(artifacts.get("render_vars"), dict) else {}
    return {str(key): str(value).strip() for key, value in raw.items() if isinstance(value, str) and value.strip()}


def _useful_render_var(render_vars: dict[str, str], key: str) -> str:
    value = str(render_vars.get(key) or "").strip()
    if not value:
        return ""
    if any(
        marker in value
        for marker in (
            "暂无",
            "未获取到",
            "未执行",
            "当前缺少明确对象",
            "operation=`",
            "当前操作",
            "点击“生成研报”",
            "你想先看哪一条",
            "如需我解读",
        )
    ):
        return ""
    return value


def _successful_synthesis_render_vars(state: GraphState) -> dict[str, str]:
    trace = state.get("trace") if isinstance(state.get("trace"), dict) else {}
    runtime = trace.get("synthesize_runtime") if isinstance(trace.get("synthesize_runtime"), dict) else {}
    legacy_runtime = trace.get("synthesize") if isinstance(trace.get("synthesize"), dict) else {}
    synthesized = (
        str(runtime.get("mode") or "").strip().lower() == "llm"
        and runtime.get("fallback") is False
    ) or (
        str(legacy_runtime.get("mode") or "").strip().lower() == "llm"
        and legacy_runtime.get("fallback") is False
    )
    if not synthesized:
        return {}
    return _render_vars(state)


def _synthesis_points(state: GraphState, keys: tuple[str, ...], *, limit: int = 4) -> list[str]:
    render_vars = _successful_synthesis_render_vars(state)
    points: list[str] = []
    seen: set[str] = set()
    for key in keys:
        value = _useful_render_var(render_vars, key)
        if not value:
            continue
        for line in value.splitlines():
            text = line.strip(" -•\t")
            if not text or text in seen:
                continue
            seen.add(text)
            points.append(text)
            if len(points) >= limit:
                return points
    return points


def _sanitize_agent_summary(summary: str) -> str:
    cleaned = str(summary or "").strip()
    cleaned = re.sub(r"^(?:[A-Za-z]+Agent|[A-Za-z]+_agent)\s*[:：]\s*", "", cleaned)

    def _compact_money(match: re.Match[str]) -> str:
        raw = match.group(1).replace(",", "")
        try:
            return _format_compact_number(float(raw), money=True)
        except Exception:
            return match.group(0)

    cleaned = re.sub(r"\$(\d{1,3}(?:,\d{3}){2,}|\d{9,})", _compact_money, cleaned)
    return cleaned[:900]


def _agent_summary(state: GraphState, names: set[str]) -> str:
    for step, output in _step_outputs(state):
        agent_name = str(step.get("name") or "").strip()
        if agent_name not in names:
            continue
        parsed = _parse_jsonish(output)
        summary = ""
        if isinstance(parsed, dict):
            summary = str(parsed.get("summary") or parsed.get("analysis") or "").strip()
        elif isinstance(parsed, str):
            summary = parsed.strip()
        if not summary:
            continue
        cleaned = _sanitize_agent_summary(summary)
        try:
            return f"{profile(agent_name).name_zh}：{cleaned}"
        except KeyError:
            return cleaned
    return ""


def _agent_risks(state: GraphState, names: set[str]) -> list[str]:
    risks: list[str] = []
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") not in names:
            continue
        parsed = _parse_jsonish(output)
        if isinstance(parsed, dict):
            raw = parsed.get("risks")
            if isinstance(raw, list):
                for item in raw:
                    text = str(item or "").strip()
                    if text and text not in risks:
                        risks.append(text[:260])
            summary = str(parsed.get("summary") or "").strip()
            if summary and any(token in summary for token in ("风险", "回撤", "跌破", "risk", "drawdown")):
                clipped = summary[:420]
                if clipped not in risks:
                    risks.append(clipped)
        elif isinstance(parsed, str) and parsed.strip():
            text = parsed.strip()
            if any(token in text for token in ("风险", "回撤", "跌破", "risk", "drawdown")):
                clipped = text[:420]
                if clipped not in risks:
                    risks.append(clipped)
    return risks[:4]


def _python_compute_metric_lines(state: GraphState, *, limit: int = 8) -> list[str]:
    lines: list[str] = []
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") != "run_python_compute":
            continue
        parsed = _parse_jsonish(output)
        if not isinstance(parsed, dict):
            continue
        metrics = parsed.get("metrics")
        if not isinstance(metrics, dict):
            continue
        for key, value in metrics.items():
            if value is None or value == "":
                continue
            formatted = _format_compact_number(value) if isinstance(value, (int, float)) else str(value).strip()
            if not formatted:
                continue
            lines.append(f"{key}: {formatted}")
            if len(lines) >= limit:
                return lines
    return lines


def _format_compact_number(value: Any, *, money: bool = False) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value or "").strip()
    abs_number = abs(number)
    prefix = "$" if money else ""
    if abs_number >= 1_000_000_000:
        return f"{prefix}{number / 1_000_000_000:.2f}B"
    if abs_number >= 1_000_000:
        return f"{prefix}{number / 1_000_000:.2f}M"
    if abs_number >= 1_000:
        return f"{prefix}{number / 1_000:.2f}K"
    return f"{prefix}{number:.2f}"
