# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/report_builder.py（WP3 Task5，零行为变更）。
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)

def _flatten_json_like_line(line: str) -> str:
    text = _safe_str(line).strip()
    if not text:
        return ""

    was_bullet = text.startswith("- ")
    candidate = text[2:].strip() if was_bullet else text
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return text

    try:
        obj = json.loads(candidate)
    except Exception:
        return text
    if not isinstance(obj, dict):
        return text

    event = _safe_str(obj.get("event")).strip()
    impact = _safe_str(obj.get("impact")).strip()
    if event and impact:
        merged = f"{event}：{impact}"
        return f"- {merged}" if was_bullet else merged

    risk = _safe_str(obj.get("risk")).strip()
    detail = _safe_str(obj.get("detail")).strip()
    if risk and detail:
        merged = f"{risk}：{detail}"
        return f"- {merged}" if was_bullet else merged

    title = _safe_str(obj.get("title") or obj.get("name")).strip()
    summary = _safe_str(obj.get("summary") or obj.get("reason") or obj.get("value")).strip()
    if title and summary:
        merged = f"{title}：{summary}"
        return f"- {merged}" if was_bullet else merged

    pairs: list[str] = []
    for key, value in obj.items():
        key_text = _safe_str(key).strip()
        value_text = _safe_str(value).strip()
        if not key_text or not value_text:
            continue
        pairs.append(f"{key_text}: {value_text}")
        if len(pairs) >= 3:
            break
    if not pairs:
        return text
    merged = "；".join(pairs)
    return f"- {merged}" if was_bullet else merged

def _sanitize_report_text_block(text: str, *, max_lines: int = 24, max_chars: int = 4000) -> str:
    raw = _safe_str(text)
    if not raw.strip():
        return ""

    out_lines: list[str] = []
    for line in raw.splitlines():
        normalized = _flatten_json_like_line(line)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            continue
        if any(marker in normalized for marker in ("<inputs>", "</inputs>", "```", "待实现", "TBD", "TODO")):
            continue
        out_lines.append(normalized)
        if len(out_lines) >= max_lines:
            break

    if not out_lines:
        return ""

    normalized_text = "\n".join(out_lines)
    if len(normalized_text) > max_chars:
        normalized_text = normalized_text[:max_chars].rstrip(" ,.;，。；") + "…"
    return normalized_text

def _parse_iso_datetime(value: str) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # Accept a few common formats.
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None

def _freshness_hours(published_date: str | None) -> float:
    if not published_date:
        return 24.0
    dt = _parse_iso_datetime(str(published_date))
    if not dt:
        return 24.0
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    delta = now - dt
    return max(0.0, delta.total_seconds() / 3600.0)

def _safe_confidence(value: Any, default: float = 0.7) -> float:
    """Convert confidence to float safely — handles 'high'/'medium'/'low' strings."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def _classify_report_type(query: str) -> str:
    q = _safe_str(query).strip().lower()
    technical_tokens = (
        "technical",
        "macd",
        "rsi",
        "技术分析",
        "支撑",
        "阻力",
        "趋势",
    )
    news_tokens = (
        "news",
        "新闻",
        "影响分析",
        "事件",
    )
    deep_tokens = (
        "deep report",
        "longform",
        "filing",
        "10-k",
        "10-q",
        "earnings call",
        "transcript",
        "deep research",
        "深度",
        "研报",
        "财报",
        "电话会",
    )
    if any(token in q for token in technical_tokens):
        return "technical"
    if any(token in q for token in news_tokens):
        return "news"
    if any(token in q for token in deep_tokens):
        return "deep_financial"
    return "general"
