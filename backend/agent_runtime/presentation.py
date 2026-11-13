"""本人研究消息的展示投影；思考与工具详情不作为金融证据或公开报告正文。"""
from __future__ import annotations

from copy import deepcopy

from .diagnostics import clean_text, safe_preview

MAX_PROVIDER_REASONING_CHARS = 20_000


def message_blocks(values) -> list[dict]:
    remaining = MAX_PROVIDER_REASONING_CHARS
    result = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict) or value.get("kind") not in {"text", "artifact", "action", "reasoning", "review"}:
            continue
        block = deepcopy(value)
        if block["kind"] == "reasoning":
            content = str(block.get("content") or "")
            if block.get("reasoning_kind") == "provider_raw":
                block["content"] = content[:remaining]
                block["truncated"] = bool(block.get("truncated") or len(content) > remaining)
                remaining -= len(block["content"])
            else:
                block["content"] = content[:8000]
        result.append(block)
    return result


def message_activities(values) -> list[dict]:
    result = []
    for step in values if isinstance(values, list) else []:
        if not isinstance(step, dict):
            continue
        detail = step.get("result") if isinstance(step.get("result"), dict) else {}
        kind = str(detail.get("runtime_type") or "")
        if not kind.startswith(("tool.", "agent.", "skill.", "activity.")):
            continue
        if str(detail.get("activity_id") or "").endswith("_model"):
            continue
        result.append({"stage": str(step.get("stage") or "trace"), "eventType": str(step.get("eventType") or "trace"),
                       "message": clean_text(str(step.get("message") or ""), 400),
                       "timestamp": str(step.get("timestamp") or ""), "runId": step.get("runId"),
                       "sessionId": step.get("sessionId"), "result": safe_preview(detail, max_chars=8000)})
    return result[-400:]

