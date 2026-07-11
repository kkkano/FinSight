# -*- coding: utf-8 -*-
"""Synthesis input/output normalization helpers."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from backend.graph.json_utils import json_dumps_safe
from backend.graph.memory_scope import prompt_memory_context
from backend.graph.state import GraphState

logger = logging.getLogger(__name__)

_MAX_SYNTH_HISTORY_MESSAGES = 8


def _clamp_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(int(value), maximum))


def _sanitize_user_facing_markdown(markdown: str) -> str:
    cleaned = str(markdown or "")
    cleaned = cleaned.replace("**后续关注：**", "**后续观察**")
    cleaned = cleaned.replace("后续关注：", "后续观察：")
    return cleaned


def _format_conversation_history_for_synth(state: GraphState) -> str:
    """
    Extract recent conversation history from state messages for synthesize context.
    Shorter than planner's version — only includes enough for pronoun resolution.
    """
    messages = state.get("messages") or []
    if not messages:
        return ""

    current_query = (state.get("query") or "").strip()
    history_msgs = []

    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content.strip() if isinstance(msg.content, str) else str(msg.content).strip()
            # Skip the current query
            if content == current_query and not any(
                isinstance(m, HumanMessage) and
                (m.content.strip() if isinstance(m.content, str) else str(m.content).strip()) == current_query
                for m in messages[messages.index(msg) + 1:]
                if isinstance(m, HumanMessage)
            ):
                continue
            history_msgs.append(f"[user]: {content}")
        elif isinstance(msg, AIMessage):
            content = msg.content.strip() if isinstance(msg.content, str) else str(msg.content).strip()
            if content and len(content) > 200:
                content = content[:200] + "..."
            if content:
                history_msgs.append(f"[assistant]: {content}")

    if not history_msgs:
        return ""

    recent = history_msgs[-_MAX_SYNTH_HISTORY_MESSAGES:]
    return (
        "<conversation_history>\n"
        + "\n".join(recent)
        + "\n</conversation_history>\n"
    )


def _format_memory_context_for_synth(state: GraphState) -> str:
    memory_context = state.get("memory_context")
    if not isinstance(memory_context, dict) or not memory_context:
        return ""

    payload = prompt_memory_context(memory_context)
    if not payload:
        return ""

    return (
        "<memory_context>\n"
        + json_dumps_safe(payload, ensure_ascii=False, indent=2)
        + "\n</memory_context>\n"
    )


def _env_str(key: str, default: str) -> str:
    raw = os.getenv(key)
    return raw.strip() if isinstance(raw, str) and raw.strip() else default


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _extract_json_object(text: str) -> str:
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


_DISALLOWED_SNIPPET_MARKERS = (
    "Search Results",
    "Performance Comparison",
    "get_",
    " output",
    "Notes:",
    "====",
    "```",
    "<inputs>",
    "</inputs>",
    "<output_format>",
    "</output_format>",
)
_DISCLAIMER_PHRASES = ("不构成投资建议", "仅供参考", "历史不代表未来", "非投资建议")


def _normalize_llm_section_line(line: str) -> str:
    cleaned = str(line or "").strip()
    if not cleaned:
        return ""

    if cleaned.startswith("- "):
        cleaned = cleaned[2:].strip()

    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            obj = json.loads(cleaned)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            event = str(obj.get("event") or "").strip()
            impact = str(obj.get("impact") or "").strip()
            if event and impact:
                return f"{event}：{impact}"

            risk = str(obj.get("risk") or "").strip()
            detail = str(obj.get("detail") or "").strip()
            if risk and detail:
                return f"{risk}：{detail}"

            title = str(obj.get("title") or obj.get("name") or "").strip()
            desc = str(obj.get("summary") or obj.get("reason") or obj.get("value") or "").strip()
            if title and desc:
                return f"{title}：{desc}"

            pairs: list[str] = []
            for key, value in obj.items():
                key_text = str(key).strip()
                value_text = str(value).strip()
                if not key_text or not value_text:
                    continue
                if any(phrase in value_text for phrase in _DISCLAIMER_PHRASES):
                    continue
                pairs.append(f"{key_text}: {value_text}")
                if len(pairs) >= 3:
                    break
            if pairs:
                return "；".join(pairs)

    return cleaned


def _sanitize_llm_section(text: str, *, max_lines: int = 8, max_chars: int = 900) -> str:
    if not isinstance(text, str):
        return ""
    cleaned_lines: list[str] = []
    for raw in text.splitlines():
        line = _normalize_llm_section_line(raw)
        if not line:
            continue
        if any(marker in line for marker in _DISALLOWED_SNIPPET_MARKERS):
            continue
        if any(phrase in line for phrase in _DISCLAIMER_PHRASES):
            continue
        cleaned_lines.append(line)
        if len(cleaned_lines) >= max_lines:
            break
    if not cleaned_lines:
        return ""
    normalized = "\n".join(
        [line if line.startswith("-") else f"- {line}" for line in cleaned_lines]
    ).strip()
    if len(normalized) > max_chars:
        normalized = normalized[:max_chars].rstrip()
    return normalized


# ==================== 幻觉事件正则模式 ====================
# 覆盖四类模式：
#   A) 「预计/计划」前缀 + 未来年份 + 事件动词
#   B) 事件动词 + 括号内月份/季度（直陈式，最危险）
#      例：「Gemini 1.5模型发布（2月底）」「新品推出（2026Q1）」
#   C) 括号内年份/季度 + 事件动词（倒装格式）
_FUTURE_EVENT_VERBS = r"(?:发布|推出|上线|发售|量产|落地|开售|开源|并购|收购|拆分|披露|宣布|实施|完成)"
# 时间短语：「2月底」「3月中旬」「Q1」「2026Q2」「下半年」等
_FUTURE_DATE_PHRASE = (
    r"(?:"
    r"\d{1,2}月[初中底前后旬]?"
    r"|[上下]半年|年[初中底]"
    r"|Q[1-4]\s*\d{0,4}"
    r"|\d{4}\s*年\s*\d{1,2}月"
    r"|\d{4}\s*Q[1-4]"
    r")"
)
_HALLUCINATION_EVENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # A-1: 前缀式 — 「预计/计划/拟于/即将/有望」+ 年份 + 动词
    re.compile(
        r"(?:预计|计划|拟于|即将|有望(?:于)?)\s*20\d{2}\s*(?:年|Q[1-4])"
        r"[^\n。；;]{0,26}" + _FUTURE_EVENT_VERBS +
        r"[^\n。；;]{0,28}",
        flags=re.IGNORECASE,
    ),
    # A-2: 前缀式 — 动词先出，年份后出
    re.compile(
        r"(?:预计|计划|拟于|即将|有望(?:于)?)[^\n。；;]{0,20}" + _FUTURE_EVENT_VERBS +
        r"[^\n。；;]{0,20}(?:20\d{2}\s*(?:年|Q[1-4]))"
        r"[^\n。；;]{0,16}",
        flags=re.IGNORECASE,
    ),
    # B: 直陈式 — 事件名 + 括号时间（最危险，模型直接当事实输出）
    # 例：「Gemini 1.5模型发布（2月底）」「Adani数据合作（2026Q1）」
    re.compile(
        r"[^\n。；;]{0,35}" + _FUTURE_EVENT_VERBS +
        r"\s*[（(]\s*" + _FUTURE_DATE_PHRASE + r"\s*[）)]",
        flags=re.IGNORECASE,
    ),
    # C: 倒装式 — 括号时间在前，动词在后
    re.compile(
        r"[（(]\s*" + _FUTURE_DATE_PHRASE + r"\s*[）)]"
        r"[^\n。；;]{0,40}" + _FUTURE_EVENT_VERBS,
        flags=re.IGNORECASE,
    ),
)
_HALLUCINATION_SAFE_PLACEHOLDER = "[此处信息未经证据验证，已移除]"


def _normalize_for_match(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _claim_supported_by_evidence(claim: str, evidence_text: str) -> bool:
    normalized_claim = _normalize_for_match(claim)
    normalized_evidence = _normalize_for_match(evidence_text)
    if not normalized_claim or not normalized_evidence:
        return False

    if normalized_claim in normalized_evidence:
        return True

    year_match = re.search(r"20\d{2}(?:年|q[1-4])?", claim, flags=re.IGNORECASE)
    # 同时检测模糊月份短语，如「2月底」「3月中旬」「Q1」
    month_match = re.search(
        r"(?:\d{1,2}月[初中底前后旬]?|[上下]半年|年[初中底]|Q[1-4])",
        claim, flags=re.IGNORECASE
    )
    date_match = year_match or month_match
    verb_match = re.search(
        r"(发布|推出|上线|发售|量产|落地|开售|开源|并购|收购|拆分|披露|宣布|实施|完成)",
        claim
    )
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9._-]{2,}|[\u4e00-\u9fff]{2,}", claim)
    stopwords = {"预计", "计划", "拟于", "即将", "有望", "发布", "推出", "上线", "发售", "量产", "落地",
                 "开售", "开源", "并购", "收购", "拆分", "披露", "宣布", "实施", "完成"}

    key_tokens: list[str] = []
    if year_match:
        key_tokens.append(year_match.group(0))
    elif month_match:
        # 模糊月份权重与年份等同：必须在证据中明确出现才算支撑
        key_tokens.append(month_match.group(0))
    if verb_match:
        key_tokens.append(verb_match.group(0))
    for token in tokens:
        token_norm = token.lower()
        if token in stopwords or token_norm in stopwords:
            continue
        key_tokens.append(token)

    hits = 0
    for token in key_tokens[:8]:
        if _normalize_for_match(token) in normalized_evidence:
            hits += 1

    # 有明确时间锚（年份或月份）时，要求同时命中实体 token → 阈值 2
    # 无时间锚时，要求 3 个 token 全命中（更严格）
    if date_match:
        return hits >= 2
    return hits >= 3


def _scrub_unverified_future_claims(text: str, evidence_text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        return ""

    cleaned = text
    for pattern in _HALLUCINATION_EVENT_PATTERNS:
        def _replace(match: re.Match[str]) -> str:
            claim = match.group(0)
            if _claim_supported_by_evidence(claim, evidence_text):
                return claim
            logger.warning("[Synthesize] scrubbed unverified future claim: %s", claim)
            return _HALLUCINATION_SAFE_PLACEHOLDER

        cleaned = pattern.sub(_replace, cleaned)

    cleaned = re.sub(
        rf"(?:{re.escape(_HALLUCINATION_SAFE_PLACEHOLDER)}\s*){{2,}}",
        _HALLUCINATION_SAFE_PLACEHOLDER + " ",
        cleaned,
    ).strip()
    return cleaned


def _is_deep_research_run(state: GraphState) -> bool:
    """判断是否需要运行深度核查 Verifier。

    修复：原来只有 analysis_depth==deep_research 时才触发，导致普通
    investment_report 模式完全跳过二次 LLM 事实核查，幻觉漏网。
    新策略：所有 investment_report 模式均触发；deep_research 深度时
    进一步可扩展核查强度（预留 flag）。
    """
    output_mode = str(state.get("output_mode") or "").strip().lower()
    return output_mode == "investment_report"












def _section_limits(output_mode: str, key: str) -> tuple[int, int]:
    if output_mode == "investment_report" and key in {
        "investment_thesis",
        "investment_summary",
        "company_overview",
        "catalysts",
        "valuation",
        "conclusion",
        "impact_analysis",
        "next_watch",
        "analysis",
        "highlights",
        "summary",
        "comparison_conclusion",
    }:
        max_lines = max(10, _env_int("LANGGRAPH_SYNTHESIZE_LONGFORM_MAX_LINES", 18))
        max_chars = max(1200, _env_int("LANGGRAPH_SYNTHESIZE_LONGFORM_MAX_CHARS", 3200))
        return max_lines, max_chars
    return 8, 900


def _coerce_payload_to_strings(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Best-effort coercion so RenderVars validation doesn't fail when the LLM returns
    lists/dicts for string fields (e.g. risks: ["...", "..."]).
    """
    if not isinstance(payload, dict):
        return {}

    coerced: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            coerced[key] = ""
            continue

        if isinstance(value, str):
            coerced[key] = value
            continue

        if isinstance(value, list):
            lines: list[str] = []
            for item in value[:20]:
                if item is None:
                    continue
                if isinstance(item, str):
                    line = item.strip()
                else:
                    try:
                        line = json_dumps_safe(item, ensure_ascii=False)
                    except Exception:
                        line = str(item)
                if line:
                    lines.append(line)
            coerced[key] = "\n".join(lines)
            continue

        if isinstance(value, dict):
            try:
                coerced[key] = json_dumps_safe(value, ensure_ascii=False)
            except Exception:
                coerced[key] = str(value)
            continue

        coerced[key] = str(value)

    return coerced


def _format_risks(candidate: Any, *, base_risks: str) -> str:
    base = base_risks.strip() if isinstance(base_risks, str) and base_risks.strip() else "- 注：以上仅供参考，不构成投资建议。"

    if candidate is None:
        return base

    raw_text = candidate.strip() if isinstance(candidate, str) else str(candidate).strip()

    parsed: dict[str, Any] | None = None
    if isinstance(candidate, dict):
        parsed = candidate
    elif isinstance(candidate, str) and raw_text.startswith("{") and raw_text.endswith("}"):
        try:
            obj = json.loads(raw_text)
            if isinstance(obj, dict):
                parsed = obj
        except Exception:
            parsed = None

    if isinstance(parsed, dict):
        lines: list[str] = []
        for k, v in parsed.items():
            if v is None:
                continue
            key = str(k).strip()
            if not key:
                continue
            key_lower = key.lower()
            if "disclaimer" in key_lower or "免责声明" in key:
                continue

            if isinstance(v, str):
                value = v.strip()
            else:
                try:
                    value = json_dumps_safe(v, ensure_ascii=False)
                except Exception:
                    value = str(v)
                value = value.strip()

            if not value:
                continue
            if any(phrase in value for phrase in _DISCLAIMER_PHRASES):
                continue

            # Prefer `AAPL: ...` style when keys look like tickers or named buckets.
            if key_lower in ("risk", "risks"):
                lines.append(f"- {value}")
            else:
                lines.append(f"- {key}：{value}")
            if len(lines) >= 6:
                break

        return "\n".join([*lines, base]).strip() if lines else base

    sanitized = _sanitize_llm_section(raw_text, max_lines=6)
    return "\n".join([sanitized, base]).strip() if sanitized else base
