# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ConfigDict

from backend.graph.intent_contract import is_research_compare_contract
from backend.graph.nodes.compare_gate import (
    has_compare_render_contract,
    is_compare_operation,
    should_render_compare,
    should_render_performance_compare,
)
from backend.graph.executor import summarize_selection
from backend.graph.event_bus import emit_event
from backend.graph.failure import append_failure, build_runtime, utc_now_iso
from backend.graph.json_utils import json_dumps_safe
from backend.graph.memory_scope import prompt_memory_context
from backend.graph.preference_timeouts import timeout_seconds_from_state
from backend.graph.state import GraphState
from backend.services.llm_retry import ainvoke_with_rate_limit_retry, is_rate_limit_error

logger = logging.getLogger(__name__)

# Maximum messages to include in synthesize prompt context
_MAX_SYNTH_HISTORY_MESSAGES = 8
_REPORT_SYNTHESIS_MAX_REQUEST_TIMEOUT_SEC = 120
_REPORT_SYNTHESIS_MAX_ACQUIRE_TIMEOUT_SEC = 45
_REPORT_SYNTHESIS_MAX_ATTEMPTS = 1
_REPORT_SYNTHESIS_SDK_MAX_RETRIES = 0
_DEEP_VERIFIER_MAX_REQUEST_TIMEOUT_SEC = 45
_DEEP_VERIFIER_MAX_ATTEMPTS = 1
_DEEP_VERIFIER_MAX_ACQUIRE_TIMEOUT_SEC = 20


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
    normalized = "\n".join([l if l.startswith("-") else f"- {l}" for l in cleaned_lines]).strip()
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


from backend.graph.render_vars.model import RenderVars  # WP3-T4 拆分回接
from backend.graph.render_vars import build_render_vars  # WP3-T4 拆分回接
from backend.report.verifier import (  # WP3-T4 verifier 搬家回接
    _normalize_verifier_claims,
    _apply_verifier_redactions,
    _contains_claim_after_redaction,
    _compute_unresolved_unsupported_claims,
    _run_deep_report_verifier,
)


def _stub_render_vars(state: GraphState) -> dict[str, str]:
    """WP3-T4 拆分：实现已迁 backend/graph/render_vars（对拍测试守护零行为）。"""
    return build_render_vars(state)


def _skill_perspective_block(state: GraphState) -> str:
    """视角型 skill：把「解读视角」拼成 prompt 段落。

    skill 系统原本只控数据/agent，不控解读视角。此处从 policy.skill_selection
    读取 perspective，注入合成 prompt。无 skill / 无视角时返回空（向后兼容）。
    """
    skill_sel = (state.get("policy") or {}).get("skill_selection")
    skill_sel = skill_sel if isinstance(skill_sel, dict) else {}
    perspective = str(skill_sel.get("perspective") or "").strip()
    if not perspective:
        return ""
    display = str(skill_sel.get("display_name") or skill_sel.get("selected_skill") or "").strip()
    label = f"「{display}」" if display else ""
    return (
        "<analysis_perspective>\n"
        f"本次分析采用{label}视角，请在以下各章节解读中始终贯彻该视角的方法与侧重：\n"
        f"{perspective}\n"
        "</analysis_perspective>\n\n"
    )


async def _generate_narrative_draft(
    state: GraphState,
    render_vars: dict[str, str],
    trace: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """
    Call LLM to produce a complete markdown research report (narrative mode).

    Returns:
    - markdown string on success (or empty string on failure)
    - optional verifier result payload
    """
    try:
        from backend.llm_config import create_llm

        _synth_temp = float(os.getenv("LANGGRAPH_SYNTHESIZE_TEMPERATURE", "0.3"))
        llm = create_llm(temperature=_synth_temp)
        llm_factory = lambda: create_llm(temperature=_synth_temp)  # noqa: E731
    except Exception as exc:
        logger.warning("[Synthesize/narrative] LLM init failed: %s", exc)
        return "", None

    artifacts = state.get("artifacts") or {}
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else None
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts, dict) else None
    debate = artifacts.get("debate") if isinstance(artifacts, dict) else None
    query = (state.get("query") or "").strip()
    subject = state.get("subject") or {}
    tickers = subject.get("tickers") if isinstance(subject, dict) else []
    tickers = tickers if isinstance(tickers, list) else []
    ticker_label = ", ".join(str(t) for t in tickers) if tickers else "标的"

    # -- Collect agent summaries and evidence for the prompt context --
    agent_sections: list[str] = []
    if isinstance(step_results, dict):
        plan_ir = state.get("plan_ir") or {}
        steps = plan_ir.get("steps") if isinstance(plan_ir, dict) else None
        step_index = {s.get("id"): s for s in (steps or []) if isinstance(s, dict) and s.get("id")}

        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            output = item.get("output")
            if isinstance(output, dict) and output.get("skipped"):
                continue
            step_meta = step_index.get(step_id) or {}
            agent_name = step_meta.get("name") or step_id
            kind = step_meta.get("kind") or "unknown"

            section_lines = [f"### {agent_name} ({kind})"]
            if isinstance(output, dict):
                summary = output.get("summary")
                if summary:
                    section_lines.append(f"摘要: {str(summary).strip()[:2000]}")
                evidence = output.get("evidence")
                if isinstance(evidence, list):
                    for ev in evidence[:15]:
                        if isinstance(ev, dict):
                            ev_text = str(ev.get("text") or "").strip()
                            if ev_text:
                                section_lines.append(f"- {ev_text[:400]}")
                        elif isinstance(ev, str) and ev.strip():
                            section_lines.append(f"- {ev.strip()[:400]}")
                risks = output.get("risks")
                if isinstance(risks, list):
                    for r in risks[:6]:
                        section_lines.append(f"- [风险] {str(r).strip()[:300]}")
            elif output is not None:
                section_lines.append(str(output).strip()[:1500])

            agent_sections.append("\n".join(section_lines))

    # -- Collect cross-agent conflict information for narrative context --
    # Apply same trigger formula: deep_report || (success >= 2 && comparable >= 1)
    _NARRATIVE_COMPARABLE_PAIRS = [
        ("technical_agent", "fundamental_agent"),
        ("technical_agent", "news_agent"),
        ("technical_agent", "price_agent"),
        ("fundamental_agent", "news_agent"),
        ("fundamental_agent", "macro_agent"),
        ("news_agent", "macro_agent"),
        ("price_agent", "news_agent"),
        ("macro_agent", "technical_agent"),
    ]
    narrative_success_agents: set[str] = set()
    if isinstance(step_results, dict):
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            output = item.get("output")
            if not isinstance(output, dict) or output.get("skipped"):
                continue
            a_name = (step_index.get(step_id) or {}).get("name") or ""
            if a_name and isinstance(output.get("summary"), str) and output["summary"].strip():
                narrative_success_agents.add(a_name)

    narrative_comparable_count = sum(
        1 for a, b in _NARRATIVE_COMPARABLE_PAIRS
        if a in narrative_success_agents and b in narrative_success_agents
    )
    output_mode_raw = state.get("output_mode") or ""
    is_narrative_deep = output_mode_raw == "investment_report"
    should_collect_conflicts = is_narrative_deep or (
        len(narrative_success_agents) >= 2 and narrative_comparable_count >= 1
    )

    conflict_context_lines: list[str] = []
    if should_collect_conflicts and isinstance(step_results, dict):
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            output = item.get("output")
            if not isinstance(output, dict):
                continue
            a_name = (step_index.get(step_id) or {}).get("name") or step_id
            flags = output.get("conflict_flags")
            claims = output.get("conflicting_claims")
            if isinstance(flags, list):
                for f in flags:
                    if isinstance(f, str) and f.strip():
                        conflict_context_lines.append(f"- [{a_name}] {f.strip()}")
            if isinstance(claims, list):
                for c in claims:
                    if isinstance(c, dict):
                        claim_text = c.get("claim", "")
                        src_a = c.get("source_a", "?")
                        val_a = c.get("value_a", "?")
                        src_b = c.get("source_b", "?")
                        val_b = c.get("value_b", "?")
                        resolved = c.get("resolved", False)
                        resolution = c.get("resolution", "")
                        status = f"已裁决: {resolution}" if resolved else "未裁决"
                        conflict_context_lines.append(
                            f"- [{a_name}] {claim_text}: {src_a}={val_a} vs {src_b}={val_b} ({status})"
                        )
        # Edge case: deep report with ≤1 agent → add degraded notice to prompt
        if is_narrative_deep and len(narrative_success_agents) <= 1:
            conflict_context_lines.insert(
                0, f"- [系统] 冲突检测降级：仅 {len(narrative_success_agents)} 个智能体成功，无法交叉验证"
            )
    conflict_context = "\n".join(conflict_context_lines) if conflict_context_lines else ""

    evidence_text = ""
    if isinstance(evidence_pool, list) and evidence_pool:
        ev_lines: list[str] = []
        for ev in evidence_pool[:20]:
            if isinstance(ev, dict):
                text = str(ev.get("text") or "").strip()
                source = str(ev.get("source") or "").strip()
                if text:
                    ev_lines.append(f"- [{source}] {text[:400]}" if source else f"- {text[:400]}")
            elif isinstance(ev, str) and ev.strip():
                ev_lines.append(f"- {ev.strip()[:400]}")
        if ev_lines:
            evidence_text = "\n".join(ev_lines)

    debate_context = ""
    if isinstance(debate, dict) and debate.get("status") == "done":
        debate_context = json_dumps_safe(
            {
                "judge_scorecard": debate.get("judge_scorecard") if isinstance(debate.get("judge_scorecard"), dict) else {},
                "consensus": debate.get("consensus"),
                "open_questions": debate.get("open_questions") if isinstance(debate.get("open_questions"), list) else [],
            },
            ensure_ascii=False,
            indent=2,
        )

    conversation_history = _format_conversation_history_for_synth(state)
    memory_context_block = _format_memory_context_for_synth(state)
    current_date = utc_now_iso()[:10]
    narrative_grounding_text = "\n".join(
        part for part in [evidence_text, conflict_context, debate_context, "\n".join(agent_sections)] if part
    )
    perspective_block = _skill_perspective_block(state)

    prompt = f"""<role>FinSight 叙事报告引擎 — 资深卖方分析师视角，将多智能体分析结果合成为专业级投资研究报告</role>

<task>
基于以下多个分析智能体的输出，撰写一份完整、深度的中文 Markdown 投资研究报告。
查询: {query}
标的: {ticker_label}
</task>

{perspective_block}<time_anchor>
当前日期: {current_date}
你的知识可能过时。涉及日期/发布/并购/监管等事件时，仅可使用本提示中明确提供的证据内容。
</time_anchor>

{conversation_history}{memory_context_block}<agent_outputs>
{chr(10).join(agent_sections) if agent_sections else "(无智能体输出)"}
</agent_outputs>

{"<evidence_pool>" + chr(10) + evidence_text + chr(10) + "</evidence_pool>" if evidence_text else ""}

{"<cross_agent_conflicts>" + chr(10) + conflict_context + chr(10) + "</cross_agent_conflicts>" if conflict_context else ""}

{"<debate_scorecard>" + chr(10) + debate_context + chr(10) + "</debate_scorecard>" if debate_context else ""}

<report_structure>
严格按以下结构撰写，使用 Markdown 标题。每个章节必须包含实质性分析段落，禁止仅列出数据点：

## 投资论点
2-3 段话。第一段给出核心判断（偏多/偏空/中性），附置信度和关键驱动因素。第二段阐述投资逻辑链条：事件 → 基本面影响 → 估值变化 → 价格预期。如有分歧信号，需明确说明矛盾点和权衡逻辑。

## 基本面分析
3-4 段话。必须涵盖：
- 盈利能力：营收规模、增速（YoY/QoQ）、利润率趋势
- 财务健康：杠杆率、现金流状况、资本配置
- 增长质量：增长驱动来源（量价/新业务/并购）、可持续性评估
- 与同业或历史水平的对比。每个论点引用具体数字。

## 技术面分析
2-3 段话。必须涵盖：
- 趋势判断：均线系统（MA20/MA50/MA200）排列与价格位置
- 动量指标：RSI 区间判断、MACD 信号方向
- 关键价位：支撑位与阻力位，以及触及后的操作含义
- 技术面与基本面信号的一致性/背离分析

## 催化剂与风险
分别列出催化剂和风险，各 2-4 条。

**催化剂**：每条必须包含：
1. 事件描述（具体事件/日期/来源）
2. 影响路径（事件 → 预期/情绪 → 业绩预期 → 估值/价格）
3. 概率和影响程度评估
此外，每个催化剂必须标注事件状态：【已确认】（有官方公告/明确日期）、【预期】（市场普遍预期但未官宣）、【传言】（未经证实的消息）。
格式：- 【已确认】2026-06-15 财报发布：预期 EPS $1.2 vs 共识 $1.15
禁止列出无法标注状态的模糊催化剂。

**风险**：每条风险必须包含可追踪的触发条件（指标+阈值），禁止"宏观环境波动""市场情绪变化"这类无法验证的空话。
格式：- 毛利率风险：若下季度毛利率跌破 40%（当前 42.3%），估值逻辑需重估
若证据中缺少具体阈值数据，标注"[阈值待补：缺少基线数据]"，但仍需指明应追踪的指标。

## 结论
2 段话。第一段综合研判，给出明确的操作建议框架（观望/逢低关注/逢高减仓等，附前提条件）。第二段必须以"观察点清单"结尾：3-5 个具体观察点，每个包含指标名称、观察窗口、触发阈值、触发后的含义。
格式（Markdown 表格）：
| 观察点 | 窗口 | 阈值 | 触发含义 |
| --- | --- | --- | --- |
| 数据中心收入增速 | Q3 财报 | <50% YoY | 增长叙事弱化 |
禁止"建议持续关注""密切跟踪"这类无行动指引的模糊表述。
</report_structure>

<constraints>
1) 总长度 4000-6000 字符。这是严格要求，不可少于 4000 字符。
2) 每句话必须有数据支撑或逻辑推导，禁止空洞套话和模板化表述。
3) 跨智能体交叉引用：技术面与基本面信号对比、新闻事件与价格走势关联、宏观环境对个股的传导路径。
4) **冲突处理（关键）**：如 <cross_agent_conflicts> 中存在未裁决冲突，必须在相关章节中：(a) 明确说明冲突点和双方数据来源；(b) 给出裁决依据（优先采信哪方、为什么）；(c) 标注剩余不确定性。已裁决冲突也需简要提及裁决结论。
5) 有证据来源时标注引用编号 [1][2]。
6) 数据不足时明确标注"[数据缺失]"，不编造数字。
7) 直接输出 Markdown，禁止 JSON 包装、代码块包裹或开场白。
8) 末尾附一行免责声明："*以上内容仅供参考，不构成投资建议。*"
9) 禁止出现"补充分析"、"核心发现"等附录性标题，所有内容必须融入上述五大章节中。
10) **可选可视化**：当可视化确实有助于读者理解时，可在正文中插入图表标签（每篇报告最多 4 个，按章节需要自适应；不滥用）：
    - 优先使用真实数据引用：`<chart_ref type="price_volume" source="market_chart" fields="ohlcv" title="量价走势"/>`；source 仅限 peers / financials / valuation / market_chart / technicals / news / earnings。
    - 如确需 LLM 概览数据才使用 `<chart>`，示例：`<chart type="bar" title="标题">{{"labels":["A","B"],"values":[10,20]}}</chart>`；inline 数据易失真，禁止编造数字。
    - Chart catalog: bar / line / pie / scatter / gauge / candlestick / price_volume / rs_line / waterfall / heatmap / radar / valuation_band / bubble / drawdown / scenario。
    - 图种选择规则：价格/趋势/技术面优先 candlestick / price_volume / rs_line / drawdown；同行对比优先 bubble / heatmap / bar；财务结构优先 waterfall / 多序列 line / bar；估值优先 valuation_band / bar；风险/情景优先 scenario / drawdown；综合评分优先 radar / gauge。
    - 图表只辅助文字分析，不替代结论、证据解释和风险说明。
11) **严格闭卷原则（高优先级）**：你唯一可用的信息来源仅限本提示中的 <agent_outputs>、<evidence_pool>、<cross_agent_conflicts>、<debate_scorecard>。
12) 禁止引用任何未在上述标签中出现的具体事实（尤其是产品发布时间、并购、监管进展、公司战略计划、竞争对手具体动态）。
13) 如需提及行业背景，仅允许使用泛化表述（如"行业竞争加剧"），禁止输出具体日期+事件断言。
14) 违反闭卷原则视为编造数据，与编造财务数字同级错误。
</constraints>"""

    retry_attempts = 0

    def _on_retry(attempt: int, _exc: BaseException) -> None:
        nonlocal retry_attempts
        retry_attempts = max(retry_attempts, int(attempt))

    try:
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_start",
                "message": "synthesize_narrative",
                "timestamp": utc_now_iso(),
            }
        )
        resp = await ainvoke_with_rate_limit_retry(
            llm,
            [HumanMessage(content=prompt)],
            llm_factory=llm_factory,
            acquire_token=True,
            on_retry=_on_retry,
        )
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_done",
                "message": "synthesize_narrative",
                "timestamp": utc_now_iso(),
            }
        )
        content = resp.content if hasattr(resp, "content") else str(resp)
        draft = str(content).strip()

        # Strip accidental code-fence wrapping
        draft = re.sub(r"^```(?:markdown|md)?\s*", "", draft, flags=re.IGNORECASE)
        draft = re.sub(r"\s*```$", "", draft)
        draft = draft.strip()
        draft = _scrub_unverified_future_claims(draft, narrative_grounding_text)

        verifier_result = await _run_deep_report_verifier(
            state=state,
            generated_text=draft,
            grounding_text=narrative_grounding_text,
        )
        unsupported_claims = (
            verifier_result.get("unsupported_claims")
            if isinstance(verifier_result, dict)
            else []
        )
        if isinstance(unsupported_claims, list) and unsupported_claims:
            draft = _apply_verifier_redactions(draft, unsupported_claims)
        unresolved_claims = (
            _compute_unresolved_unsupported_claims(draft, unsupported_claims)
            if isinstance(unsupported_claims, list)
            else []
        )
        if isinstance(verifier_result, dict):
            verifier_result["unresolved_unsupported_claims"] = unresolved_claims

        if len(draft) < 500:
            logger.warning("[Synthesize/narrative] LLM output too short (%d chars), discarding", len(draft))
            return "", verifier_result

        logger.info("[Synthesize/narrative] Generated %d-char narrative draft (retries=%d)", len(draft), retry_attempts)
        return draft, verifier_result

    except Exception as exc:
        retryable = is_rate_limit_error(exc)
        logger.warning(
            "[Synthesize/narrative] LLM call FAILED (retryable=%s, attempts=%d): %s — will use template fallback",
            retryable, retry_attempts, exc,
        )
        append_failure(
            trace,
            node="synthesize",
            stage="narrative_llm_call",
            error=str(exc),
            fallback="template_draft",
            retryable=retryable,
            retry_attempts=retry_attempts,
        )
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_error",
                "message": "synthesize_narrative failed; fallback to template",
                "timestamp": utc_now_iso(),
            }
        )
        return "", None


def _extract_brief_headline(news_raw: Any) -> str:
    """Extract first headline from news tool output for morning brief."""
    if news_raw is None:
        return "暂无重大事件"
    if isinstance(news_raw, list):
        for item in news_raw[:5]:
            if isinstance(item, dict):
                title = item.get("headline") or item.get("title") or ""
                if title:
                    return str(title).strip()[:120]
            elif isinstance(item, str) and item.strip():
                return item.strip()[:120]
    elif isinstance(news_raw, str):
        for line in news_raw.split("\n"):
            clean = line.strip().lstrip("-•*0-9. ")
            if clean and len(clean) > 10:
                return clean[:120]
    return "暂无重大事件"


def _synthesize_morning_brief_data(state: GraphState) -> dict[str, Any]:
    """Deterministic morning brief synthesis — zero LLM cost (ADR-P1-001).

    Extracts price + news data from Graph step_results and produces
    structured brief data + formatted markdown.  Reuses the same response
    schema as ``morning_brief_router`` so the frontend needs no changes.
    """
    from datetime import datetime, timezone

    from backend.utils.quote import parse_quote_payload, safe_float

    artifacts = state.get("artifacts") or {}
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else {}
    plan_ir = state.get("plan_ir") or {}
    raw_steps = plan_ir.get("steps") if isinstance(plan_ir, dict) else []
    step_index = {s.get("id"): s for s in (raw_steps or []) if isinstance(s, dict) and s.get("id")}

    subject = state.get("subject") or {}
    tickers = subject.get("tickers") if isinstance(subject, dict) else []
    all_tickers = [t for t in (tickers if isinstance(tickers, list) else []) if isinstance(t, str) and t.strip()]

    # Collect per-ticker price and news from step_results
    ticker_prices: dict[str, dict] = {}
    ticker_news: dict[str, str] = {}

    for step_id, item in (step_results if isinstance(step_results, dict) else {}).items():
        if not isinstance(item, dict):
            continue
        output = item.get("output")
        step_def = step_index.get(step_id) or {}
        tool_name = step_def.get("name") or ""
        inputs = step_def.get("inputs") or {}
        ticker = str(inputs.get("ticker") or "").strip()

        if tool_name == "get_stock_price" and ticker:
            parsed = parse_quote_payload(output) if output else None
            if parsed:
                ticker_prices[ticker] = parsed
        elif tool_name == "get_company_news" and ticker:
            ticker_news[ticker] = _extract_brief_headline(output)

    # Build highlights
    highlights: list[dict[str, Any]] = []
    for ticker in all_tickers:
        price_data = ticker_prices.get(ticker, {})
        price = safe_float(price_data.get("price"))
        change = safe_float(price_data.get("change"))
        change_pct = safe_float(price_data.get("change_percent"))
        headline = ticker_news.get(ticker, "暂无重大事件")

        trend = "neutral"
        if change_pct is not None:
            if change_pct >= 3.0:
                trend = "strong_up"
            elif change_pct >= 1.0:
                trend = "up"
            elif change_pct > -1.0:
                trend = "neutral"
            elif change_pct > -3.0:
                trend = "down"
            else:
                trend = "strong_down"

        highlights.append({
            "ticker": ticker,
            "price": round(price, 2) if price is not None else None,
            "price_change": round(change, 4) if change is not None else None,
            "price_change_pct": round(change_pct, 2) if change_pct is not None else None,
            "trend": trend,
            "key_event": headline,
        })

    highlights.sort(key=lambda h: abs(safe_float(h.get("price_change_pct")) or 0), reverse=True)

    # Market mood
    _MOOD_CN: dict[str, str] = {
        "bullish": "看涨", "cautiously_optimistic": "谨慎乐观", "neutral": "中性",
        "cautiously_pessimistic": "谨慎悲观", "bearish": "看跌",
    }
    priced = [h for h in highlights if h.get("price") is not None]
    if priced:
        avg = sum(safe_float(h.get("price_change_pct")) or 0 for h in priced) / len(priced)
        if avg >= 1.5:
            mood = "bullish"
        elif avg >= 0.3:
            mood = "cautiously_optimistic"
        elif avg > -0.3:
            mood = "neutral"
        elif avg > -1.5:
            mood = "cautiously_pessimistic"
        else:
            mood = "bearish"
    else:
        mood = "neutral"

    # Summary text
    up_cnt = sum(1 for h in priced if (safe_float(h.get("price_change_pct")) or 0) > 0)
    down_cnt = sum(1 for h in priced if (safe_float(h.get("price_change_pct")) or 0) < 0)
    flat_cnt = len(priced) - up_cnt - down_cnt
    summary = f"今日跟踪 {len(all_tickers)} 只标的，其中 {len(priced)} 只获取到实时报价。"
    if priced:
        summary += f"上涨 {up_cnt} 只，下跌 {down_cnt} 只，横盘 {flat_cnt} 只。"
    summary += f"整体情绪：{_MOOD_CN.get(mood, '中性')}。"

    # Action items
    action_items: list[str] = []
    big_up = [h for h in highlights if (safe_float(h.get("price_change_pct")) or 0) >= 3.0]
    big_down = [h for h in highlights if (safe_float(h.get("price_change_pct")) or 0) <= -3.0]
    if big_up:
        action_items.append(f"关注强势标的 {', '.join(h['ticker'] for h in big_up[:3])} 的持续动能，考虑止盈策略")
    if big_down:
        action_items.append(f"警惕 {', '.join(h['ticker'] for h in big_down[:3])} 的下行风险，检查止损位")
    news_hits = [h for h in highlights if h.get("key_event") and h["key_event"] != "暂无重大事件"]
    if news_hits:
        action_items.append(f"阅读 {', '.join(h['ticker'] for h in news_hits[:3])} 的最新新闻，评估事件影响")
    if not action_items:
        action_items.append("今日持仓波动平稳，建议维持当前仓位")

    brief_data: dict[str, Any] = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "summary": summary,
        "highlights": highlights,
        "market_mood": mood,
        "market_mood_cn": _MOOD_CN.get(mood, "中性"),
        "action_items": action_items,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ticker_count": len(all_tickers),
        "priced_count": len(priced),
    }

    # Draft markdown
    md_lines = [
        f"# 📊 每日晨报 — {brief_data['date']}", "",
        f"**{summary}**", "",
        "## 持仓概览", "",
    ]
    for h in highlights:
        p = f"${h['price']:.2f}" if h.get("price") is not None else "N/A"
        c = f"{h['price_change_pct']:+.2f}%" if h.get("price_change_pct") is not None else ""
        md_lines.append(f"- **{h['ticker']}** {p} {c} — {h['key_event']}")
    md_lines += ["", "## 操作建议", ""]
    for item in action_items:
        md_lines.append(f"- {item}")
    md_lines += [
        "",
        f"> 整体情绪：**{_MOOD_CN.get(mood, '中性')}** | 本报告由 FinSight Pipeline 自动生成，不构成投资建议。",
    ]

    return {"brief_data": brief_data, "draft_markdown": "\n".join(md_lines)}


async def synthesize(state: GraphState) -> dict:
    """
    Phase 4.4 Synthesize node.

    Modes:
    - LANGGRAPH_SYNTHESIZE_MODE=llm (default): LLM fills render_vars JSON; validate; fallback to stub
    - LANGGRAPH_SYNTHESIZE_MODE=stub: deterministic render_vars
    - LANGGRAPH_SYNTHESIZE_MODE=llm: LLM fills render_vars JSON; validate; fallback to stub
    - LANGGRAPH_SYNTHESIZE_MODE=narrative: LLM writes full markdown report; render_vars kept for cards

    Mode resolution (2026-05-03 fix for "答非所问"):
    - The ``narrative`` mode (LLM writes a 5-section markdown report) only
      applies when ``output_mode == 'investment_report'`` (user explicitly
      asked for a report, e.g. clicked 「生成研报」or said 「研报」).
    - For ``brief`` / ``chat`` output modes (the default for casual Q&A like
      「今天微软什么价格」), narrative is downgraded to ``llm`` so the answer
      remains natural without triggering a full report.
    - ``stub`` and ``llm`` modes are NOT downgraded — both already produce
      compact ``render_vars`` for the brief template, no length explosion.
    - Multi-task chat/brief plans stay in compact LLM synthesis unless the
      caller explicitly sets ``LANGGRAPH_SYNTHESIZE_MODE=stub``. Report mode
      can still choose narrative for explicit reports.
    """
    env_mode = _env_str("LANGGRAPH_SYNTHESIZE_MODE", "llm").lower()
    output_mode = state.get("output_mode") or "brief"
    _ready_tasks_raw = state.get("tasks")
    _ready_tasks = _ready_tasks_raw if isinstance(_ready_tasks_raw, list) else []
    _op_dict = state.get("operation") if isinstance(state.get("operation"), dict) else {}
    _op_name_for_mode = str(_op_dict.get("name") or "").strip().lower()
    _is_pure_compare = _op_name_for_mode == "compare" and len(_ready_tasks) <= 2
    _multi_task_force_stub = (
        output_mode == "investment_report"
        and env_mode == "narrative"
        and len(_ready_tasks) >= 2
        and not _is_pure_compare
    )
    _brief_router_task_graph = (
        output_mode == "brief"
        and env_mode == "llm"
        and bool(_ready_tasks)
        and all(
            isinstance(task, dict)
            and str(task.get("reason") or "").strip()
            in {
                "conversation_router_task_hint",
                "conversation_router_task_hint_support",
                "multi_ticker_compare",
                "compare_subtask",
                "ticker_or_alias",
                "representative_basket_qa",
            }
            for task in _ready_tasks
        )
    )

    if _multi_task_force_stub:
        mode = "stub"
        logger.info(
            "[Synthesize] Multi-task plan detected (%d tasks); forcing stub mode "
            "so render_stub._build_multitask_markdown can render per-task sections "
            "(env_mode=%s, output_mode=%s)",
            len(_ready_tasks),
            env_mode,
            output_mode,
        )
    elif _brief_router_task_graph:
        mode = "stub"
        logger.info(
            "[Synthesize] brief router task graph detected; using deterministic render_vars for latency"
        )
    elif env_mode == "narrative" and output_mode != "investment_report":
        mode = "llm"
        logger.info(
            "[Synthesize] narrative downgraded to llm (output_mode=%s ≠ investment_report); "
            "narrative reserved for explicit deep-report requests only",
            output_mode,
        )
    else:
        mode = env_mode
    trace = state.get("trace") or {}
    synth_started_at = time.perf_counter()

    if os.getenv("QUERY_COVERAGE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        try:
            from backend.research.query_coverage import build_answer_targets, evaluate_coverage

            current_artifacts = dict(state.get("artifacts") or {})
            if not isinstance(current_artifacts.get("query_coverage"), dict):
                targets = build_answer_targets(state)
                current_artifacts["query_coverage"] = evaluate_coverage(
                    current_artifacts.get("evidence_ledger") or {},
                    targets,
                )
                state = {**state, "artifacts": current_artifacts}  # type: ignore[assignment]
                trace.setdefault("query_coverage", {})["target_count"] = len(targets)
        except Exception as exc:
            logger.info("[Synthesize] query coverage skipped: %s", exc)

    await emit_event(
        {
            "type": "pipeline_stage",
            "stage": "synthesizing",
            "status": "start",
            "message": "Synthesize started",
            "timestamp": utc_now_iso(),
        }
    )

    async def _emit_synth_stage_done(*, status: str, message: str, error: str | None = None) -> None:
        payload: dict[str, Any] = {
            "type": "pipeline_stage",
            "stage": "synthesizing",
            "status": status,
            "message": message,
            "duration_ms": int((time.perf_counter() - synth_started_at) * 1000),
            "timestamp": utc_now_iso(),
        }
        if error:
            payload["error"] = str(error)[:300]
        await emit_event(payload)

    # ── Morning brief: deterministic structured synthesis (ADR-P1-001, zero LLM) ──
    _op_raw = state.get("operation") or {}
    _op_name = _op_raw.get("name") if isinstance(_op_raw, dict) else None
    if _op_name == "morning_brief":
        brief_result = _synthesize_morning_brief_data(state)
        trace.update({
            "synthesize_runtime": {
                **build_runtime(mode="morning_brief_deterministic", fallback=False),
                "keys": ["brief_data", "draft_markdown"],
            }
        })
        merged_artifacts = {
            **(state.get("artifacts") or {}),
            "brief_data": brief_result["brief_data"],
            "draft_markdown": brief_result["draft_markdown"],
            "render_vars": {},
        }
        await _emit_synth_stage_done(status="done", message="Morning brief synthesized (deterministic)")
        return {"artifacts": merged_artifacts, "trace": trace}

    # ── Emit decision_note when compare intent has no evidence ──
    # should_render_compare() now requires BOTH operation=compare AND valid
    # tool evidence.  When evidence is absent, the downstream _stub_render_vars
    # / LLM path will naturally degrade to multi-asset QA.  We emit a note
    # here so the frontend can surface the reason once, before mode branching.
    research_compare_contract = is_research_compare_contract(state.get("intent_contract") if isinstance(state.get("intent_contract"), dict) else None)
    if is_compare_operation(state) and not should_render_compare(state) and not research_compare_contract:
        await emit_event(
            {
                "type": "decision_note",
                "scope": "synthesize",
                "title": "Compare evidence missing — degraded to QA",
                "reason": "operation=compare but get_performance_comparison returned no valid data",
                "code": "compare_evidence_missing",
                "impact": "Using standard multi-asset QA template instead of comparison template",
                "timestamp": utc_now_iso(),
            }
        )

    # ── narrative mode: LLM writes full markdown report; render_vars kept for cards ──
    if mode == "narrative":
        logger.info("[Synthesize] Running in NARRATIVE mode — LLM writes full report draft")
        render_vars = _stub_render_vars(state)

        draft_markdown, verifier_result = await _generate_narrative_draft(state, render_vars, trace)
        verifier_claims = (
            verifier_result.get("unsupported_claims")
            if isinstance(verifier_result, dict)
            else []
        )
        unresolved_verifier_claims = (
            verifier_result.get("unresolved_unsupported_claims")
            if isinstance(verifier_result, dict)
            else []
        )
        synth_runtime: dict[str, Any] = {
            **build_runtime(mode="narrative", fallback=not bool(draft_markdown)),
            "keys": sorted(render_vars.keys()),
        }
        if isinstance(verifier_result, dict):
            synth_runtime["verifier_enabled"] = bool(verifier_result.get("enabled"))
            synth_runtime["verifier_checked"] = bool(verifier_result.get("checked"))
            synth_runtime["verifier_unsupported_count"] = (
                len(verifier_claims) if isinstance(verifier_claims, list) else 0
            )
            synth_runtime["verifier_unresolved_unsupported_count"] = (
                len(unresolved_verifier_claims) if isinstance(unresolved_verifier_claims, list) else 0
            )

        trace.update({"synthesize_runtime": synth_runtime})
        artifacts = {**(state.get("artifacts") or {}), "render_vars": render_vars}
        if draft_markdown:
            draft_markdown = _sanitize_user_facing_markdown(draft_markdown)
            artifacts["draft_markdown"] = draft_markdown
        if isinstance(verifier_result, dict):
            artifacts["verifier_result"] = verifier_result
        if isinstance(verifier_claims, list) and verifier_claims:
            await emit_event(
                {
                    "type": "decision_note",
                    "scope": "verifier",
                    "title": "Deep report verifier redactions",
                    "reason": "Detected unsupported factual claims and redacted them.",
                    "impact": f"unsupported_claims={len(verifier_claims)}",
                    "timestamp": utc_now_iso(),
                }
            )
        await _emit_synth_stage_done(status="done", message="Synthesize completed")
        return {"artifacts": artifacts, "trace": trace}

    # ── stub mode (default): deterministic render_vars ──
    raw_tasks = state.get("tasks")
    ready_tasks = [
        task for task in (raw_tasks if isinstance(raw_tasks, list) else [])
        if isinstance(task, dict) and str(task.get("status") or "ready").strip().lower() != "blocked"
    ]
    ready_task_operations = {
        str((task.get("operation") or {}).get("name") or "").strip().lower()
        for task in ready_tasks
        if isinstance(task.get("operation"), dict)
    }
    chat_brief_low_latency_ops = bool(ready_task_operations) and ready_task_operations.issubset({"price", "technical"}) and all(
        str(task.get("subject_type") or "").strip().lower() in {"company", "index", "crypto", "fund"}
        for task in ready_tasks
    )
    if mode == "llm" and output_mode in {"chat", "brief"} and ready_tasks and chat_brief_low_latency_ops:
        render_vars = _stub_render_vars(state)
        trace.update(
            {
                "synthesize_runtime": {
                    **build_runtime(mode="task_graph_stub", fallback=False),
                    "reason": "quote_or_technical_uses_short_task_graph_renderer",
                    "keys": sorted(render_vars.keys()),
                }
            }
        )
        await _emit_synth_stage_done(status="done", message="Synthesize completed in task-graph mode")
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}

    if mode != "llm":
        logger.info("[Synthesize] Running in STUB mode (set LANGGRAPH_SYNTHESIZE_MODE=llm for LLM synthesis)")
        render_vars = _stub_render_vars(state)
        trace.update(
            {
                "synthesize_runtime": {
                    **build_runtime(mode="stub", fallback=False),
                    "keys": sorted(render_vars.keys()),
                }
            }
        )
        await _emit_synth_stage_done(status="done", message="Synthesize completed in stub mode")
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}

    # ── llm mode: LLM fills render_vars JSON ──
    llm_limits = {
        "request_timeout": _env_int("LANGGRAPH_SYNTHESIZE_TIMEOUT_SEC", 150),
        "max_tokens": _env_int("LANGGRAPH_SYNTHESIZE_MAX_TOKENS", 3000),
        "max_attempts": _env_int("LANGGRAPH_SYNTHESIZE_MAX_ATTEMPTS", 2),
        "acquire_timeout": _env_int("LANGGRAPH_SYNTHESIZE_ACQUIRE_TIMEOUT_SEC", 120),
    }
    if output_mode == "investment_report":
        llm_limits = {
            "request_timeout": _env_int("LANGGRAPH_SYNTHESIZE_REPORT_TIMEOUT_SEC", 180),
            "max_tokens": _env_int("LANGGRAPH_SYNTHESIZE_REPORT_MAX_TOKENS", 6000),
            "max_attempts": _env_int("LANGGRAPH_SYNTHESIZE_REPORT_MAX_ATTEMPTS", 1),
            "acquire_timeout": _env_int("LANGGRAPH_SYNTHESIZE_REPORT_ACQUIRE_TIMEOUT_SEC", 60),
        }
    preferred_timeout = timeout_seconds_from_state(state)
    if preferred_timeout is not None:
        llm_limits["request_timeout"] = int(preferred_timeout)
        llm_limits["acquire_timeout"] = int(min(float(llm_limits["acquire_timeout"]), preferred_timeout))
    llm_create_extra: dict[str, Any] = {}
    if output_mode == "investment_report":
        llm_limits["request_timeout"] = _clamp_int(
            int(llm_limits["request_timeout"]),
            minimum=1,
            maximum=_REPORT_SYNTHESIS_MAX_REQUEST_TIMEOUT_SEC,
        )
        llm_limits["max_attempts"] = _clamp_int(
            int(llm_limits["max_attempts"]),
            minimum=1,
            maximum=_REPORT_SYNTHESIS_MAX_ATTEMPTS,
        )
        llm_limits["acquire_timeout"] = _clamp_int(
            int(llm_limits["acquire_timeout"]),
            minimum=1,
            maximum=_REPORT_SYNTHESIS_MAX_ACQUIRE_TIMEOUT_SEC,
        )
        llm_limits["sdk_max_retries"] = _REPORT_SYNTHESIS_SDK_MAX_RETRIES
        llm_create_extra["max_retries"] = _REPORT_SYNTHESIS_SDK_MAX_RETRIES
    try:
        from backend.llm_config import create_llm

        _synth_temp = float(os.getenv("LANGGRAPH_SYNTHESIZE_TEMPERATURE", "0.2"))
        llm = create_llm(
            temperature=_synth_temp,
            max_tokens=int(llm_limits["max_tokens"]),
            request_timeout=int(llm_limits["request_timeout"]),
            **llm_create_extra,
        )
        llm_factory = lambda: create_llm(  # noqa: E731
            temperature=_synth_temp,
            max_tokens=int(llm_limits["max_tokens"]),
            request_timeout=int(llm_limits["request_timeout"]),
            **llm_create_extra,
        )
    except Exception as exc:
        render_vars = _stub_render_vars(state)
        append_failure(
            trace,
            node="synthesize",
            stage="llm_init",
            error=str(exc),
            fallback="synthesize_stub",
            retryable=False,
        )
        trace.update(
            {
                "synthesize_runtime": build_runtime(
                    mode="llm",
                    fallback=True,
                    reason=f"llm_unavailable: {exc}",
                    retry_attempts=0,
                )
                | {"llm_limits": llm_limits}
            }
        )
        await _emit_synth_stage_done(
            status="error",
            message="Synthesize LLM unavailable, fallback emitted",
            error=str(exc),
        )
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}

    subject = state.get("subject") or {}
    operation = state.get("operation") or {}
    output_mode = state.get("output_mode") or "brief"
    artifacts = state.get("artifacts") or {}
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts, dict) else None
    rag_context = artifacts.get("rag_context") if isinstance(artifacts, dict) else None
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else None
    evidence_ledger = artifacts.get("evidence_ledger") if isinstance(artifacts, dict) else None
    query_coverage = artifacts.get("query_coverage") if isinstance(artifacts, dict) else None
    debate = artifacts.get("debate") if isinstance(artifacts, dict) else None

    # Build separated evidence sections for structured prompt
    evidence_pool_list = evidence_pool if isinstance(evidence_pool, list) else []
    rag_context_list = rag_context if isinstance(rag_context, list) else []

    inputs = {
        "query": state.get("query") or "",
        "subject": subject,
        "operation": operation,
        "output_mode": output_mode,
        "conversation_router": (state.get("trace") or {}).get("conversation_router") if isinstance(state.get("trace"), dict) else {},
        "step_results": step_results if isinstance(step_results, dict) else {},
        "evidence_ledger": evidence_ledger if isinstance(evidence_ledger, dict) else {},
        "query_coverage": query_coverage if isinstance(query_coverage, dict) else {},
        "debate": debate if isinstance(debate, dict) else {},
    }

    # Format evidence sections with XML tags
    realtime_section = ""
    if evidence_pool_list:
        realtime_section = "<realtime_evidence>\n" + json_dumps_safe(evidence_pool_list[:20], ensure_ascii=False, indent=2) + "\n</realtime_evidence>\n"

    historical_section = ""
    if rag_context_list:
        historical_section = "<historical_knowledge>\n" + json_dumps_safe(rag_context_list[:20], ensure_ascii=False, indent=2) + "\n</historical_knowledge>\n"

    evidence_rules = ""
    if realtime_section or historical_section:
        evidence_rules = """<evidence_priority_rules>
1. 实时数据与历史数据冲突时，以实时数据为准
2. 引用历史数据时必须标注数据时间（如"根据 2025 Q3 财报..."）
3. 无法确认时效性的数据需注明"截至某日期"
</evidence_priority_rules>
"""

    synth_conversation_history = _format_conversation_history_for_synth(state)
    synth_memory_context = _format_memory_context_for_synth(state)
    current_date = utc_now_iso()[:10]
    llm_grounding_text = "\n".join(
        part for part in [
            json_dumps_safe(evidence_pool_list[:20], ensure_ascii=False),
            json_dumps_safe(rag_context_list[:20], ensure_ascii=False),
            json_dumps_safe(step_results if isinstance(step_results, dict) else {}, ensure_ascii=False),
            json_dumps_safe(debate if isinstance(debate, dict) else {}, ensure_ascii=False),
        ] if part
    )

    prompt = f"""<role>FinSight 对话/报告合成引擎 — 将原始数据转化为自然、可引用的中文分析内容</role>

<task>
根据输入数据填充报告模板变量。仅返回 JSON 对象，禁止 markdown 或注释。
所有文本值必须为简体中文。
如果 output_mode 是 chat 或 brief，字段内容要像正常对话里的分析段落：简洁、直接、有上下文感，不要套“问题/后续关注/分析对象/本轮包含”模板。
如果 inputs.conversation_router.reply_guidance 提到多个子需求或最后的收束问题，必须覆盖完整；需要一句话收束时放入 next_watch 或 conclusion。
</task>

<time_anchor>
当前日期: {current_date}
你的知识可能过时。涉及日期/发布/并购/监管等事件时，仅可使用本提示中明确提供的证据内容。
</time_anchor>

{synth_conversation_history}{synth_memory_context}<inputs>
{json_dumps_safe(inputs, ensure_ascii=False, indent=2)}
</inputs>

{realtime_section}{historical_section}{evidence_rules}<output_format>
返回 JSON 对象，键为以下模板变量的子集：
news_summary, impact_analysis, next_watch, risks,
conclusion, investment_summary, company_overview, catalysts, valuation,
price_snapshot, technical_snapshot,
comparison_conclusion, comparison_metrics,
summary, highlights, analysis.
</output_format>

<field_quality_guidelines>
每个字段的质量要求：
- company_overview: 2-3 句话概括公司主营、市场地位、核心竞争力
- catalysts: 列出 3-5 个近期催化剂，每条含事件+潜在影响；并标注事件状态【已确认】（有官方公告/日期）/【预期】（市场普遍预期未官宣）/【传言】（未经证实），如"- 【已确认】2026-06-15 财报：预期 EPS $1.2 vs 共识 $1.15"
- valuation: 包含关键估值指标（PE/PB/PS）及与历史/同业对比
- risks: 3-5 条风险要点，区分系统性风险和个股风险；每条须带可追踪触发条件（指标+阈值），禁止"宏观环境波动"类空话，如"- 毛利率风险：若毛利率跌破 40%（当前 42.3%）需重估"；缺阈值数据时标注"[阈值待补]"
- conclusion: 综合各维度给出明确的方向性判断，附条件和置信度；末尾给出具体观察点清单（指标名称+观察窗口+触发阈值+触发含义），禁止"建议持续关注"类无行动指引表述
- news_summary: 提炼核心新闻事件，侧重影响而非事件本身
- investment_summary: 一段话浓缩投资核心逻辑（多/空/中性 + 理由）
- investment_thesis: 投资主线需包含判断、依据、触发条件、证伪条件与执行建议
</field_quality_guidelines>

<constraints>
1) 严格闭卷：仅可使用 <realtime_evidence>、<historical_knowledge>、<inputs.step_results>、<inputs.evidence_ledger>、<inputs.debate> 中已出现的信息。
2) 禁止引用任何未在上述标签中出现的具体事实（尤其是产品发布时间、并购、监管进展、公司战略计划、竞争对手具体动态）。
3) 如需提及行业背景，仅允许泛化表述，禁止输出具体日期+事件断言。
4) 数据不足时明确标注"[数据缺失]"或"数据有限"，禁止补写训练知识中的细节。
5) 禁止输出原始工具数据、搜索日志、trace 信息。
6) 免责声明最多在 risks 字段末尾出现 1 次，其他字段禁止重复。
7) 每个字段控制在 6 条要点以内，追求信息密度而非长度。
8) 禁止使用"待实现"、"暂无数据"等占位短语；无数据时输出"[数据缺失]"。
9) 输出必须为合法 JSON 对象。
10) 禁止开场白、寒暄。直接输出 JSON。
11) chat/brief 模式下必须产出 conclusion 和 impact_analysis；用 2-5 条自然要点回答用户真正问的问题，报告结构只用于 investment_report。
12) chat/brief 模式下不要漏掉用户的最后一个明确请求；如果用户要求“最后/一句话/关注什么/怎么做”，用 next_watch 给出自然收束句。
13) 如 inputs.query_coverage.unanswered_targets 非空，第一段先回答已覆盖目标，并明确披露尚未覆盖的目标。
</constraints>
"""

    retry_attempts = 0

    def _on_retry(attempt: int, _exc: BaseException) -> None:
        nonlocal retry_attempts
        retry_attempts = max(retry_attempts, int(attempt))

    raw_content = ""
    try:
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_start",
                "message": "synthesize",
                "timestamp": utc_now_iso(),
            }
        )
        resp = await ainvoke_with_rate_limit_retry(
            llm,
            [HumanMessage(content=prompt)],
            llm_factory=llm_factory,
            acquire_token=True,
            max_attempts=int(llm_limits["max_attempts"]),
            acquire_timeout_seconds=float(llm_limits["acquire_timeout"]),
            on_retry=_on_retry,
        )
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_done",
                "message": "synthesize",
                "timestamp": utc_now_iso(),
            }
        )
        content = resp.content if hasattr(resp, "content") else str(resp)
        raw_content = str(content or "").strip()
        try:
            payload = json.loads(_extract_json_object(raw_content))
        except Exception:
            if output_mode in {"chat", "brief"} and raw_content and "{" not in raw_content[:120]:
                natural_text = re.sub(r"^```(?:markdown)?\s*", "", raw_content, flags=re.IGNORECASE)
                natural_text = re.sub(r"\s*```$", "", natural_text).strip()
                render_vars = _stub_render_vars(state)
                render_vars["conclusion"] = natural_text
                render_vars.setdefault("impact_analysis", natural_text)
                trace.update(
                    {
                        "synthesize": {
                            "mode": "llm",
                            "fallback": False,
                            "natural_text": True,
                            "keys": sorted(render_vars.keys()),
                            "chat_brief": True,
                            "retry_attempts": retry_attempts,
                        }
                    }
                )
                return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}
            raise
        if not isinstance(payload, dict):
            raise ValueError("render_vars payload must be a JSON object")

        payload = _coerce_payload_to_strings(payload)
        llm_render_vars = RenderVars.model_validate(payload).model_dump()
        # Merge with deterministic stub defaults so omitted keys never fall back
        # to template placeholders. Some keys are "data sections" that must stay
        # evidence-driven; keep the stub version to avoid hallucinated metrics.
        stub_render_vars = _stub_render_vars(state)
        base_risks = str(stub_render_vars.get("risks") or "- 注：以上仅供参考，不构成投资建议。").strip()
        protected_keys = {"news_summary", "comparison_metrics", "price_snapshot", "technical_snapshot"}
        render_vars: dict[str, str] = {}
        for key, stub_value in stub_render_vars.items():
            if key in protected_keys:
                render_vars[key] = stub_value
                continue
            candidate = llm_render_vars.get(key)
            if key == "risks":
                formatted_risks = _format_risks(candidate, base_risks=base_risks)
                render_vars[key] = _scrub_unverified_future_claims(formatted_risks, llm_grounding_text)
                continue
            if key in (
                "comparison_conclusion",
                "conclusion",
                "impact_analysis",
                "next_watch",
                "investment_summary",
                "investment_thesis",
                "company_overview",
                "catalysts",
                "valuation",
                "summary",
                "highlights",
                "analysis",
            ):
                if isinstance(candidate, str) and candidate.strip():
                    candidate = _scrub_unverified_future_claims(candidate, llm_grounding_text)
                    max_lines, max_chars = _section_limits(output_mode, key)
                    sanitized = _sanitize_llm_section(candidate, max_lines=max_lines, max_chars=max_chars)
                    render_vars[key] = sanitized if sanitized else stub_value
                else:
                    render_vars[key] = stub_value
                continue

            if isinstance(candidate, str) and candidate.strip():
                candidate = _scrub_unverified_future_claims(candidate, llm_grounding_text)
                render_vars[key] = candidate
            else:
                render_vars[key] = stub_value
        for key, candidate in llm_render_vars.items():
            if key not in render_vars:
                render_vars[key] = candidate
        if any("待实现" in str(v) for v in render_vars.values()):
            raise ValueError("render_vars contains placeholder tokens")

        verifier_result: dict[str, Any]
        if output_mode == "investment_report":
            verifier_result = await _run_deep_report_verifier(
                state=state,
                generated_text="\n".join(
                    [
                        section
                        for section in (
                            str(render_vars.get("summary") or ""),
                            str(render_vars.get("highlights") or ""),
                            str(render_vars.get("analysis") or ""),
                            str(render_vars.get("investment_summary") or ""),
                            str(render_vars.get("investment_thesis") or ""),
                            str(render_vars.get("valuation") or ""),
                            str(render_vars.get("conclusion") or ""),
                            str(render_vars.get("impact_analysis") or ""),
                            str(render_vars.get("next_watch") or ""),
                            str(render_vars.get("risks") or ""),
                        )
                        if section.strip()
                    ]
                ),
                grounding_text=llm_grounding_text,
            )
        else:
            verifier_result = {
                "enabled": False,
                "checked": False,
                "reason": "chat_brief_synthesis_skips_deep_report_verifier",
                "unsupported_claims": [],
            }
        verifier_claims = (
            verifier_result.get("unsupported_claims")
            if isinstance(verifier_result, dict)
            else []
        )
        if isinstance(verifier_claims, list) and verifier_claims:
            redact_keys = (
                "summary",
                "highlights",
                "analysis",
                "investment_summary",
                "investment_thesis",
                "valuation",
                "conclusion",
                "impact_analysis",
                "next_watch",
                "risks",
            )
            for key in redact_keys:
                value = render_vars.get(key)
                if isinstance(value, str) and value.strip():
                    render_vars[key] = _apply_verifier_redactions(value, verifier_claims)
        verifier_text_after_redaction = "\n".join(
            [
                str(render_vars.get("summary") or ""),
                str(render_vars.get("highlights") or ""),
                str(render_vars.get("analysis") or ""),
                str(render_vars.get("investment_summary") or ""),
                str(render_vars.get("investment_thesis") or ""),
                str(render_vars.get("valuation") or ""),
                str(render_vars.get("conclusion") or ""),
                str(render_vars.get("impact_analysis") or ""),
                str(render_vars.get("next_watch") or ""),
                str(render_vars.get("risks") or ""),
            ]
        )
        unresolved_verifier_claims = (
            _compute_unresolved_unsupported_claims(verifier_text_after_redaction, verifier_claims)
            if isinstance(verifier_claims, list)
            else []
        )
        if isinstance(verifier_result, dict):
            verifier_result["unresolved_unsupported_claims"] = unresolved_verifier_claims

        synth_runtime: dict[str, Any] = {
            **build_runtime(mode="llm", fallback=False, retry_attempts=retry_attempts),
            "keys": sorted(render_vars.keys()),
            "llm_limits": llm_limits,
        }
        if isinstance(verifier_result, dict):
            synth_runtime["verifier_enabled"] = bool(verifier_result.get("enabled"))
            synth_runtime["verifier_checked"] = bool(verifier_result.get("checked"))
            synth_runtime["verifier_unsupported_count"] = (
                len(verifier_claims) if isinstance(verifier_claims, list) else 0
            )
            synth_runtime["verifier_unresolved_unsupported_count"] = (
                len(unresolved_verifier_claims) if isinstance(unresolved_verifier_claims, list) else 0
            )

        trace.update({"synthesize_runtime": synth_runtime})
        merged_artifacts = {**(state.get("artifacts") or {}), "render_vars": render_vars}
        if isinstance(verifier_result, dict):
            merged_artifacts["verifier_result"] = verifier_result
        if isinstance(verifier_claims, list) and verifier_claims:
            await emit_event(
                {
                    "type": "decision_note",
                    "scope": "verifier",
                    "title": "Verifier unsupported claims",
                    "reason": "Unsupported factual claims were identified in synthesis output.",
                    "impact": f"unsupported_claims={len(verifier_claims)}",
                    "timestamp": utc_now_iso(),
                }
            )
        await _emit_synth_stage_done(status="done", message="Synthesize completed")
        return {"artifacts": merged_artifacts, "trace": trace}
    except Exception as exc:
        retryable = is_rate_limit_error(exc)
        logger.warning(
            "[Synthesize] LLM call FAILED (retryable=%s, attempts=%d): %s — falling back to stub",
            retryable, retry_attempts, exc,
        )
        append_failure(
            trace,
            node="synthesize",
            stage="llm_call",
            error=str(exc),
            fallback="synthesize_stub",
            retryable=retryable,
            retry_attempts=retry_attempts,
        )
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_error",
                "message": "synthesize failed; fallback to stub",
                "timestamp": utc_now_iso(),
            }
        )
        render_vars = _stub_render_vars(state)
        fallback_reason = "llm_empty_output" if not str(raw_content or "").strip() else "llm_output_invalid"
        trace.update(
            {
                "synthesize_runtime": build_runtime(
                    mode="llm",
                    fallback=True,
                    reason=fallback_reason,
                    retry_attempts=retry_attempts,
                )
            }
        )
        await _emit_synth_stage_done(
            status="error",
            message="Synthesize failed, fallback to stub",
            error=str(exc),
        )
        return {"artifacts": {**(state.get("artifacts") or {}), "render_vars": render_vars}, "trace": trace}


__all__ = ["synthesize", "RenderVars"]
