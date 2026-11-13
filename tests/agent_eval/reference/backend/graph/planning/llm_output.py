# -*- coding: utf-8 -*-
"""Planner LLM 输出的 JSON 提取、修复与顶层结构校验。"""
from __future__ import annotations

import json
import re
from typing import Any


def _extract_json_object(text: str) -> str:
    """
    Extract the first JSON object from a model response.
    Handles code fences and surrounding commentary.
    """
    if not text:
        raise ValueError("empty model output")

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no json object found")
    return cleaned[start : end + 1]


def _extract_error_snippet(text: str, pos: int, *, radius: int = 220) -> str:
    raw = str(text or "")
    idx = max(0, min(len(raw), int(pos or 0)))
    start = max(0, idx - radius)
    end = min(len(raw), idx + radius)
    return raw[start:end].strip()


def _build_parse_error_info(raw_output: str, exc: BaseException) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": str(exc)}
    raw = str(raw_output or "")

    try:
        json_candidate = _extract_json_object(raw)
    except Exception:
        json_candidate = raw

    payload["output_preview"] = json_candidate[:1200]
    if isinstance(exc, json.JSONDecodeError):
        payload["line"] = int(exc.lineno)
        payload["column"] = int(exc.colno)
        payload["pos"] = int(exc.pos)
        payload["snippet"] = _extract_error_snippet(json_candidate, exc.pos)
    else:
        payload["snippet"] = json_candidate[:320]
    return payload


def _repair_json_text(text: str) -> str:
    repaired = str(text or "")
    if not repaired:
        return repaired

    repaired = repaired.replace("\ufeff", "")
    repaired = repaired.translate(
        str.maketrans(
            {
                "“": '"',
                "”": '"',
                "‘": "'",
                "’": "'",
                "，": ",",
                "：": ":",
            }
        )
    )
    repaired = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", repaired)
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    repaired = re.sub(r"([{,]\s*)'([^'\\]+?)'(\s*:)", r'\1"\2"\3', repaired)
    repaired = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_\-]*)(\s*:)", r'\1"\2"\3', repaired)
    repaired = re.sub(
        r'((?:"(?:[^"\\]|\\.)*"|[\]\}]|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?))(\s*\n\s*)"([^"\n]+)"(\s*:)',
        r'\1,\2"\3"\4',
        repaired,
    )

    def _replace_single_quoted_value(match: re.Match[str]) -> str:
        body = match.group(1).replace('\\"', '"').replace("\\'", "'")
        escaped = json.dumps(body, ensure_ascii=False)
        return f": {escaped}{match.group(2)}"

    repaired = re.sub(r":\s*'([^'\\]*(?:\\.[^'\\]*)*)'(\s*[,}])", _replace_single_quoted_value, repaired)
    return repaired


def _load_json_with_repair(json_text: str) -> tuple[Any, dict[str, Any]]:
    raw = str(json_text or "")
    attempts: list[tuple[str, str]] = [("raw", raw)]

    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw)
    if sanitized != raw:
        attempts.append(("control_char_sanitized", sanitized))

    repaired = _repair_json_text(sanitized)
    if repaired != sanitized:
        attempts.append(("syntax_repaired", repaired))

    last_exc: BaseException | None = None
    for mode, candidate in attempts:
        try:
            return json.loads(candidate, strict=False), {"parse_mode": mode}
        except Exception as exc:  # noqa: PERF203
            last_exc = exc

    if last_exc is not None:
        raise last_exc
    raise ValueError("json_parse_failed")


def _build_json_retry_prompt(
    *,
    base_prompt: str,
    parse_error: dict[str, Any],
    invalid_output: str,
) -> str:
    line = parse_error.get("line")
    col = parse_error.get("column")
    position = f"line={line}, col={col}" if line and col else "unknown"
    snippet = str(parse_error.get("snippet") or "")[:800]
    preview = str(invalid_output or "")[:3200]
    return (
        f"{base_prompt}\n\n"
        "[FORMAT_RECOVERY]\n"
        "Your previous output was not valid JSON.\n"
        f"- Parse error: {parse_error.get('error')}\n"
        f"- Parse position: {position}\n"
        f"- Error snippet: {snippet}\n\n"
        "Return ONLY a valid JSON object. Do not include markdown/code fences/explanations.\n"
        "Rules:\n"
        "1) Use double quotes for every key and string value.\n"
        "2) No trailing commas.\n"
        "3) Output must be parseable by Python json.loads.\n\n"
        "[PREVIOUS_INVALID_OUTPUT]\n"
        f"{preview}\n"
    )


_PLAN_SHAPE_REQUIRED_KEYS = ("goal", "subject", "output_mode", "steps", "budget", "synthesis")


class PlannerSchemaShapeError(ValueError):
    """Raised when JSON is parseable but is not shaped like a PlanIR payload."""


def _parse_planner_json_output(raw_text: str) -> tuple[Any, dict[str, Any]]:
    json_text = _extract_json_object(raw_text)
    return _load_json_with_repair(json_text)


def _assert_planner_payload_shape(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise PlannerSchemaShapeError("PlanIR payload must be a JSON object")

    missing = [key for key in _PLAN_SHAPE_REQUIRED_KEYS if key not in payload]
    type_errors: list[str] = []
    if "goal" in payload and not isinstance(payload.get("goal"), str):
        type_errors.append("goal must be a string")
    if "subject" in payload and not isinstance(payload.get("subject"), dict):
        type_errors.append("subject must be an object")
    if "output_mode" in payload and not isinstance(payload.get("output_mode"), str):
        type_errors.append("output_mode must be a string")
    if "steps" in payload and not isinstance(payload.get("steps"), list):
        type_errors.append("steps must be an array")
    if "budget" in payload and not isinstance(payload.get("budget"), dict):
        type_errors.append("budget must be an object")
    if "synthesis" in payload and not isinstance(payload.get("synthesis"), dict):
        type_errors.append("synthesis must be an object")

    if missing or type_errors:
        details = []
        if missing:
            details.append("missing keys: " + ", ".join(missing))
        if type_errors:
            details.append("type errors: " + "; ".join(type_errors))
        raise PlannerSchemaShapeError("planner_schema_shape_invalid: " + " | ".join(details))


def _build_schema_error_info(raw_output: str, exc: BaseException) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": str(exc)}
    payload["output_preview"] = str(raw_output or "")[:1200]
    payload["required_keys"] = list(_PLAN_SHAPE_REQUIRED_KEYS)
    return payload


def _build_schema_retry_prompt(
    *,
    base_prompt: str,
    schema_error: dict[str, Any],
    invalid_output: str,
) -> str:
    preview = str(invalid_output or "")[:3200]
    return (
        f"{base_prompt}\n\n"
        "[SCHEMA_RECOVERY]\n"
        "Your previous output was valid JSON, but it was not a valid PlanIR object.\n"
        f"- Schema error: {schema_error.get('error')}\n\n"
        "Return ONLY one JSON object with exactly this top-level shape:\n"
        "{\n"
        '  "goal": "short objective",\n'
        '  "subject": {"subject_type": "company|macro|unknown", "tickers": [], "selection_payload": []},\n'
        '  "output_mode": "chat|brief|investment_report",\n'
        '  "steps": [],\n'
        '  "budget": {"max_rounds": 3, "max_tools": 4},\n'
        '  "synthesis": {"style": "concise", "sections": []}\n'
        "}\n"
        "No markdown, no prose, no extra top-level answer/commentary field.\n\n"
        "[PREVIOUS_INVALID_OUTPUT]\n"
        f"{preview}\n"
    )


__all__ = [
    "PlannerSchemaShapeError",
    "_assert_planner_payload_shape",
    "_build_json_retry_prompt",
    "_build_parse_error_info",
    "_build_schema_error_info",
    "_build_schema_retry_prompt",
    "_extract_error_snippet",
    "_extract_json_object",
    "_load_json_with_repair",
    "_parse_planner_json_output",
    "_repair_json_text",
]
