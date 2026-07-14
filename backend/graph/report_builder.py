# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.utils.env import env_int as _env_int

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from backend.research.query_coverage import coverage_warning_text
from backend.report.quality_engine import evaluate_runtime_report_quality
from backend.report.validator import ReportValidator


logger = logging.getLogger(__name__)

from backend.report.agent_formatters import (  # WP3-T5 拆分回接
    AGENT_REPORT_SUMMARY_FORMATTERS,
    _extract_price_behavior_snapshot,
    _format_price_agent_claims,
    _format_price_agent_report_summary,
    _format_price_behavior_snapshot,
    format_agent_report_summary,
)
from backend.report.citations import (  # WP3-T5 拆分回接
    _CitationBuild,
    _build_citations,
    _build_filing_section_citations,
    _build_internal_citation_key,
    _build_internal_citation_url,
    _canonicalize_url_for_citation_match,
    _detect_filing_section_ref,
    _is_suspicious_citation_item,
    _normalize_internal_citation_text,
)
from backend.report.grounding import (  # WP3-T5 拆分回接
    _build_grounding_corpus,
    _compute_grounding_stats,
    _extract_grounding_claims,
    _is_claim_grounded,
    _normalize_for_grounding,
)
from backend.report.quality_hints import _build_report_quality_hints  # WP3-T5 拆分回接
from backend.report.util import (  # WP3-T5 拆分回接
    _classify_report_type,
    _flatten_json_like_line,
    _freshness_hours,
    _parse_iso_datetime,
    _safe_confidence,
    _safe_str,
    _sanitize_report_text_block,
)
from backend.agents.profiles import AGENT_PROFILES, profile



_AGENT_TITLE_MAP: dict[str, str] = {
    key: f"{item.short_zh} · {item.name_zh}"
    for key, item in AGENT_PROFILES.items()
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _archive_report_predictions(
    *,
    report_id: str,
    user_id: str,
    plan_steps: list[dict[str, Any]],
    step_results: dict[str, Any],
) -> dict[str, Any]:
    """只关联 Agent step 已通过服务端校验并持久化的 prediction。"""
    eligible_step_ids = {
        str(step.get("id") or "")
        for step in plan_steps
        if isinstance(step, dict)
        and str(step.get("kind") or "") == "agent"
        and isinstance(step.get("inputs"), dict)
        and step["inputs"].get("prediction_eligible") is True
    }
    eligible_step_ids.update(
        str(step_id)
        for step_id, result in step_results.items()
        if isinstance(result, dict)
        and isinstance(result.get("output"), dict)
        and result["output"].get("prediction_eligible") is True
    )
    prediction_ids: list[str] = []
    for step_id in eligible_step_ids:
        result = step_results.get(step_id)
        output = result.get("output") if isinstance(result, dict) else None
        prediction = output.get("prediction") if isinstance(output, dict) else None
        prediction_id = str(prediction.get("id") or "").strip() if isinstance(prediction, dict) else ""
        if prediction_id and prediction_id not in prediction_ids:
            prediction_ids.append(prediction_id)

    diagnostics = {
        "eligible_steps": len(eligible_step_ids),
        "archived": 0,
        "prediction_ids": [],
        "status": "not_eligible" if not eligible_step_ids else "prediction_missing",
    }
    normalized_user = str(user_id or "").strip()
    if not prediction_ids or not normalized_user or normalized_user == "public":
        return diagnostics
    try:
        from backend.services.agent_prediction_store import get_agent_prediction_store

        store = get_agent_prediction_store()
        for prediction_id in prediction_ids:
            if store.attach_report(prediction_id, user_id=normalized_user, report_id=report_id):
                diagnostics["archived"] += 1
                diagnostics["prediction_ids"].append(prediction_id)
    except Exception:
        logger.warning("prediction report archive unavailable", exc_info=True)
        diagnostics["status"] = "archive_unavailable"
        return diagnostics
    diagnostics["status"] = "archived" if diagnostics["archived"] else "prediction_missing"
    return diagnostics


# P2-1 护城河前置：幻觉洗涤可见化最大展示条数
_FACT_CHECK_MAX_CLAIMS = 20


def _build_fact_check_payload(
    verifier_result: dict[str, Any] | None,
    verifier_claims: list[Any],
) -> dict[str, Any]:
    """把验证器结果转成前端可消费的 fact_check 结构。

    数据来源是 synthesize 节点真实的二次事实核查输出（verifier_result），
    不允许编造演示数据。验证器未运行 / 未发现问题时，返回
    redaction_count==0 的「全部通过」状态，让前端始终能展示核查行为，
    这是护城河「可解释性」可见化的核心。

    Args:
        verifier_result: state.artifacts["verifier_result"]，含 enabled/checked 等标志。
        verifier_claims: 验证器检测到的不可信声明列表 [{"claim","reason"}, ...]，
            这些声明已在正文中被替换为「[不可信声明]」占位符。

    Returns:
        {"verifier_claims": [...], "redaction_count": int, "verified_at": ISO 时间戳,
         "enabled": bool, "checked": bool}
    """
    claims: list[dict[str, str]] = []
    if isinstance(verifier_claims, list):
        for item in verifier_claims:
            if len(claims) >= _FACT_CHECK_MAX_CLAIMS:
                break
            if not isinstance(item, dict):
                continue
            claim_text = _safe_str(item.get("claim")).strip()
            if not claim_text:
                continue
            reason_text = _safe_str(item.get("reason")).strip()
            claims.append(
                {
                    "claim": claim_text[:240],
                    "reason": reason_text[:240] if reason_text else "证据池中未找到明确支撑",
                }
            )

    result_dict = verifier_result if isinstance(verifier_result, dict) else {}
    return {
        "verifier_claims": claims,
        "redaction_count": len(claims),
        "verified_at": _now_iso(),
        "enabled": bool(result_dict.get("enabled")),
        "checked": bool(result_dict.get("checked")),
    }




def _to_json_compatible(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return [_to_json_compatible(item) for item in value]
        if isinstance(value, dict):
            return {str(k): _to_json_compatible(v) for k, v in value.items()}
        return _safe_str(value)


def _sanitize_deep_search_summary(summary: str, agent_name: str) -> str:
    if agent_name != "deep_search_agent":
        return summary
    text = _safe_str(summary)
    if not text.strip():
        return text

    noise_markers = (
        "SummaryRatingsFinancialsTechnicals",
        "MarketWatch",
        "Privacy Policy",
        "Terms of Use",
    )
    noisy = any(marker in text for marker in noise_markers)
    if not noisy:
        loop_heading = re.compile(r"^\s*深度补充说明（第\d+轮）\s*$", flags=re.M)
        if loop_heading.search(text):
            seen_loop_bodies: set[str] = set()
            out_lines: list[str] = []
            lines = text.splitlines()
            i = 0
            while i < len(lines):
                line = _safe_str(lines[i]).strip()
                if not line:
                    out_lines.append("")
                    i += 1
                    continue
                if loop_heading.match(line):
                    i += 1
                    body: list[str] = []
                    while i < len(lines):
                        nxt = _safe_str(lines[i]).strip()
                        if loop_heading.match(nxt):
                            break
                        body.append(_safe_str(lines[i]))
                        i += 1
                    body_text = "\n".join(body).strip()
                    body_key = re.sub(r"\s+", " ", body_text)
                    if body_key and body_key not in seen_loop_bodies:
                        seen_loop_bodies.add(body_key)
                        out_lines.append("## 深度补充说明")
                        out_lines.extend(body)
                    continue
                out_lines.append(_safe_str(lines[i]))
                i += 1
            return "\n".join(out_lines).strip()

        return text

    cleaned = re.sub(r"https?://\S+", "", text)
    for marker in noise_markers:
        cleaned = cleaned.replace(marker, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 500:
        cleaned = cleaned[:500].rstrip(" ,.;，。；") + "…"

    return (
        f"深度研究摘要（质量保护模式）：{cleaned}\n\n"
        "注意：建议结合财报、公告或权威媒体原文复核关键结论。"
    )






def _harden_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload

    sections = payload.get("sections")
    if not isinstance(sections, list):
        sections = []

    repaired_sections: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        contents = section.get("contents")
        if not isinstance(contents, list):
            contents = []

        repaired_contents: list[dict[str, Any]] = []
        for content in contents:
            if not isinstance(content, dict):
                continue
            content_type = _safe_str(content.get("type") or "text").strip() or "text"
            text = _safe_str(content.get("content") or "")
            if content_type == "text" and text:
                if re.search(r"^\s*-?\s*\{[^\n]*\}\s*$", text, flags=re.M):
                    text = _sanitize_report_text_block(text, max_lines=20, max_chars=2200) or text
            if content_type == "text" and not text.strip():
                text = "（该部分暂无结构化内容）"

            repaired_contents.append(
                {
                    "type": content_type,
                    "content": text,
                    "citation_refs": content.get("citation_refs") if isinstance(content.get("citation_refs"), list) else [],
                    "metadata": content.get("metadata") if isinstance(content.get("metadata"), dict) else {},
                }
            )

        if not repaired_contents:
            repaired_contents = [{"type": "text", "content": "（该部分暂无结构化内容）", "citation_refs": [], "metadata": {}}]

        repaired = dict(section)
        repaired["contents"] = repaired_contents
        repaired_sections.append(repaired)

    payload["sections"] = repaired_sections

    summary = _safe_str(payload.get("summary") or "")
    if re.search(r"^\s*\{[^\n]*\}\s*$", summary):
        summary = _sanitize_report_text_block(summary, max_lines=2, max_chars=420)
    if not summary.strip():
        for section in repaired_sections:
            for content in section.get("contents") or []:
                if not isinstance(content, dict):
                    continue
                if _safe_str(content.get("type") or "") != "text":
                    continue
                candidate = _safe_str(content.get("content") or "").strip()
                if candidate:
                    summary = candidate[:400]
                    break
            if summary:
                break
    payload["summary"] = summary or "（暂无摘要）"

    synthesis_report = _safe_str(payload.get("synthesis_report") or "")
    if not synthesis_report.strip():
        lines = ["## 投资摘要", f"- {payload['summary']}"]
        for section in repaired_sections[:6]:
            section_title = _safe_str(section.get("title") or "")
            if not section_title:
                continue
            lines.append(f"## {section_title}")
            first_text = ""
            for content in section.get("contents") or []:
                if isinstance(content, dict) and _safe_str(content.get("type") or "") == "text":
                    first_text = _safe_str(content.get("content") or "").strip()
                    if first_text:
                        break
            lines.append(f"- {first_text[:240] or '（暂无内容）'}")
        synthesis_report = "\n".join(lines)
    elif re.search(r"^\s*-?\s*\{[^\n]*\}\s*$", synthesis_report, flags=re.M):
        synthesis_report = _sanitize_report_text_block(synthesis_report, max_lines=120, max_chars=12000) or synthesis_report
    payload["synthesis_report"] = synthesis_report

    risks = payload.get("risks")
    if isinstance(risks, list):
        cleaned_risks = [_safe_str(item).strip() for item in risks if _safe_str(item).strip()]
        payload["risks"] = cleaned_risks or ["报告已自动降级生成，建议结合原始数据复核。"]
    else:
        payload["risks"] = ["报告已自动降级生成，建议结合原始数据复核。"]

    return payload






def _count_content_chars(markdown: str) -> int:
    """
    Roughly align with frontend `countContentChars()`:
    Chinese chars + English words/numbers, after stripping common markdown syntax.
    """
    if not markdown:
        return 0
    text = str(markdown)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # links → keep link text
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"(\*{1,3}|_{1,3})(.*?)\1", r"\2", text)
    text = re.sub(r"~~.*?~~", "", text)
    text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s]*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>+\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"---+|===+|\*\*\*+", "", text)
    text = text.replace("|", " ")
    # Ignore raw URLs (they should not count towards "content length").
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[:\-]+", " ", text)
    chinese = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    words = len(re.findall(r"[a-zA-Z0-9]+", text))
    return chinese + words


def _to_bullets(text: str, *, limit: int = 8) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    lines: list[str] = []
    for raw in text.splitlines():
        line = _safe_str(raw).strip()
        if not line:
            continue
        line = line.lstrip("-").strip()
        if not line:
            continue
        lines.append(line[:220])
        if len(lines) >= limit:
            break
    return lines


def _normalize_line_for_dedupe(line: str) -> str:
    normalized = _safe_str(line)
    normalized = re.sub(r"\[[0-9]+\]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    normalized = normalized.lstrip("- ")
    return normalized


def _dedupe_markdown_lines(text: str, *, keep_heading_repeats: bool = False) -> str:
    if not isinstance(text, str) or not text.strip():
        return ""

    seen: set[str] = set()
    output: list[str] = []
    for raw in text.splitlines():
        line = _safe_str(raw)
        stripped = line.strip()
        if not stripped:
            if output and output[-1] == "":
                continue
            output.append("")
            continue

        if stripped.startswith("##") and keep_heading_repeats:
            output.append(stripped)
            continue

        key = _normalize_line_for_dedupe(stripped)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        output.append(stripped)

    return "\n".join(output).strip()


def _extract_deep_research_points(summary: str, *, limit: int = 6) -> list[str]:
    text = _safe_str(summary).strip()
    if not text:
        return []

    cleaned = _sanitize_deep_search_summary(text, "deep_search_agent")
    points: list[str] = []
    for raw in cleaned.splitlines():
        line = _safe_str(raw).strip()
        if not line:
            continue
        if line.startswith("##"):
            continue
        line = line.lstrip("- ").strip()
        if not line:
            continue
        if len(line) > 220:
            line = line[:220].rstrip(" ,.;，。；") + "..."
        points.append(line)
        if len(points) >= limit:
            break
    return points


def _extend_synthesis_report_if_short(
    *,
    synthesis_report: str,
    ticker_label: str,
    query: str,
    render_vars: dict[str, Any] | None,
    agent_summaries: list[dict[str, Any]] | None,
    citations: list[dict[str, Any]] | None,
) -> str:
    """Extend a thin report by weaving agent data into the narrative.

    No ugly "## 补充分析" section — agent data is appended as natural
    continuation paragraphs under existing headings when the draft is short.
    """
    min_chars = max(400, _env_int("REPORT_SYNTHESIS_MIN_CHARS", 2500))

    text = _safe_str(synthesis_report).strip()
    if not text:
        text = f"## {ticker_label} 综合研究报告\n"

    agent_summaries = agent_summaries if isinstance(agent_summaries, list) else []
    citations = citations if isinstance(citations, list) else []

    has_source_section = any(
        f"## {heading}" in text
        for heading in ("引用来源", "数据可信度与来源说明", "来源复核清单")
    )

    # If draft already has enough real content, just dedupe and return.
    if _count_content_chars(text) >= min_chars:
        return _dedupe_markdown_lines(text).strip() + "\n"

    # --- Weave successful agent summaries into the report as continuation ---
    success_agents = [
        a for a in agent_summaries if isinstance(a, dict) and a.get("status") == "success"
    ]
    supplement: list[str] = []
    existing_keys: set[str] = set()
    for line in text.splitlines():
        key = _normalize_line_for_dedupe(line)
        if key:
            existing_keys.add(key)

    for item in success_agents:
        name = _safe_str(item.get("agent_name") or "").strip()
        summary = _safe_str(item.get("summary") or "").strip()
        if not name or not summary:
            continue
        if name == "deep_search_agent":
            summary = _sanitize_deep_search_summary(summary, name)
        # Use concise headline instead of appending full summary block
        headline = _extract_headline(summary)
        if not headline or headline == "（无摘要）":
            continue
        agent_title = _AGENT_TITLE_MAP.get(name, name)
        line = f"- {agent_title}：{headline}"
        key = _normalize_line_for_dedupe(line)
        if not key or key in existing_keys:
            continue
        supplement.append(line)
        existing_keys.add(key)

    if supplement:
        text = (text + "\n\n## 关键执行观点\n" + "\n".join(supplement)).strip()

    # --- Append citation list only if no source section exists ---
    if citations and not has_source_section:
        cite_lines: list[str] = ["", "## 引用来源"]
        for item in citations[:12]:
            if not isinstance(item, dict):
                continue
            sid = _safe_str(item.get("source_id") or "").strip()
            title = _safe_str(item.get("title") or item.get("url") or "").strip()[:180]
            url = _safe_str(item.get("url") or "").strip()
            if not sid:
                continue
            if url:
                cite_lines.append(f"[{sid}] [{title}]({url})")
            elif title:
                cite_lines.append(f"[{sid}] {title}")
        if len(cite_lines) > 2:
            text = text + "\n" + "\n".join(cite_lines)

    return _dedupe_markdown_lines(text).strip() + "\n"




































def _agent_status_from_steps(
    *,
    allowed_agents: list[str],
    plan_steps: list[dict[str, Any]],
    step_results: dict[str, Any],
    errors: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    status: dict[str, dict[str, Any]] = {}
    steps_by_agent: dict[str, str] = {}
    for step in plan_steps:
        if not isinstance(step, dict):
            continue
        if step.get("kind") != "agent":
            continue
        name = step.get("name")
        step_id = step.get("id")
        if isinstance(name, str) and isinstance(step_id, str) and name.strip() and step_id.strip():
            steps_by_agent[name.strip()] = step_id.strip()

    errors_by_step: dict[str, str] = {}
    for err in errors:
        if not isinstance(err, dict):
            continue
        sid = err.get("step_id")
        msg = err.get("error")
        if isinstance(sid, str) and sid and isinstance(msg, str) and msg:
            errors_by_step[sid] = msg

    for agent_name in allowed_agents:
        step_id = steps_by_agent.get(agent_name)
        if not step_id:
            status[agent_name] = {"status": "not_run", "confidence": 0.0}
            continue

        if step_id in errors_by_step:
            status[agent_name] = {"status": "error", "confidence": 0.0, "error": errors_by_step[step_id]}
            continue

        raw = step_results.get(step_id) if isinstance(step_results, dict) else None
        output = raw.get("output") if isinstance(raw, dict) else None
        if isinstance(output, dict) and output.get("skipped") is True:
            reason = _safe_str(output.get("reason") or "skipped") or "skipped"
            skipped_payload: dict[str, Any] = {
                "status": "not_run",
                "confidence": 0.0,
                "skipped_reason": reason,
                "escalation_not_needed": reason == "escalation_not_needed",
            }
            evidence_quality = output.get("evidence_quality")
            if isinstance(evidence_quality, dict):
                skipped_payload["evidence_quality"] = evidence_quality
            status[agent_name] = skipped_payload
            continue

        confidence = None
        if isinstance(output, dict):
            confidence = output.get("confidence")
        try:
            conf = float(confidence) if confidence is not None else 0.6
        except Exception:
            conf = 0.6

        success_payload: dict[str, Any] = {"status": "success", "confidence": max(0.0, min(1.0, conf))}
        if isinstance(output, dict):
            evidence_quality = output.get("evidence_quality")
            if isinstance(evidence_quality, dict):
                success_payload["evidence_quality"] = evidence_quality
            data_sources = output.get("data_sources")
            if isinstance(data_sources, list):
                success_payload["data_sources"] = [str(x) for x in data_sources if str(x).strip()][:8]
            # P0-3d: structured fallback diagnostics
            if output.get("fallback_used"):
                success_payload["status"] = "fallback"
                success_payload["fallback_reason"] = output.get("fallback_reason")
                success_payload["retryable"] = bool(output.get("retryable", False))
                success_payload["error_stage"] = output.get("error_stage")
            # Conflict tracking
            conflict_flags = output.get("conflict_flags")
            if isinstance(conflict_flags, list) and conflict_flags:
                success_payload["conflict_flags"] = [str(f) for f in conflict_flags[:10]]
                success_payload["has_conflicts"] = True
        status[agent_name] = success_payload

    return status


def _agent_summaries_from_steps(
    *,
    allowed_agents: list[str],
    plan_steps: list[dict[str, Any]],
    step_results: dict[str, Any],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    steps_by_agent: dict[str, str] = {}
    for step in plan_steps:
        if not isinstance(step, dict):
            continue
        if step.get("kind") != "agent":
            continue
        name = step.get("name")
        step_id = step.get("id")
        if isinstance(name, str) and isinstance(step_id, str) and name.strip() and step_id.strip():
            steps_by_agent[name.strip()] = step_id.strip()

    errors_by_step: dict[str, str] = {}
    for err in errors:
        if not isinstance(err, dict):
            continue
        sid = err.get("step_id")
        msg = err.get("error")
        if isinstance(sid, str) and sid and isinstance(msg, str) and msg:
            errors_by_step[sid] = msg

    role_by_agent: dict[str, str] = {}
    for step in plan_steps:
        if not isinstance(step, dict) or step.get("kind") != "agent":
            continue
        name = _safe_str(step.get("name") or "").strip()
        inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
        role = _safe_str(inputs.get("role") or "support").strip().lower()
        if name:
            role_by_agent[name] = "lead" if role == "lead" else "support"

    indexed_agents = list(enumerate(allowed_agents))
    ordered_agents = [
        agent_name
        for _, agent_name in sorted(
            indexed_agents,
            key=lambda item: (0 if role_by_agent.get(item[1]) == "lead" else 1, item[0]),
        )
    ]

    summaries: list[dict[str, Any]] = []
    order = 1
    for agent_name in ordered_agents:
        step_id = steps_by_agent.get(agent_name)
        title = _AGENT_TITLE_MAP.get(agent_name, agent_name)
        if not step_id:
            summaries.append(
                {
                    "title": title,
                    "order": order,
                    "agent_name": agent_name,
                    "status": "not_run",
                    "summary": "未运行（本轮未触发或无匹配意图）",
                    "confidence": 0.0,
                    "data_sources": [],
                    "raw_output": {},
                    "evidence_full": [],
                    "trace_full": [],
                }
            )
            order += 1
            continue

        if step_id in errors_by_step:
            summaries.append(
                {
                    "title": title,
                    "order": order,
                    "agent_name": agent_name,
                    "status": "error",
                    "error": True,
                    "error_message": errors_by_step[step_id],
                    "summary": f"⚠️ 执行失败：{errors_by_step[step_id]}",
                    "confidence": 0.0,
                    "data_sources": [],
                    "raw_output": {"error": errors_by_step[step_id], "step_id": step_id},
                    "evidence_full": [],
                    "trace_full": [],
                }
            )
            order += 1
            continue

        raw = step_results.get(step_id) if isinstance(step_results, dict) else None
        output = raw.get("output") if isinstance(raw, dict) else None
        if isinstance(output, dict) and output.get("skipped") is True:
            reason = _safe_str(output.get("reason") or "skipped") or "skipped"
            summary_text = "Not run."
            if reason == "dry_run":
                summary_text = "Not run (dry_run)."
            elif reason == "escalation_not_needed":
                summary_text = "Not run (escalation not needed)."
            elif reason:
                summary_text = f"Not run ({reason})."
            summaries.append(
                {
                    "title": title,
                    "order": order,
                    "agent_name": agent_name,
                    "status": "not_run",
                    "summary": summary_text,
                    "confidence": 0.0,
                    "data_sources": [],
                    "skipped_reason": reason,
                    "escalation_not_needed": reason == "escalation_not_needed",
                    "raw_output": _to_json_compatible(output),
                    "evidence_full": [],
                    "trace_full": _to_json_compatible(output.get("trace")) if isinstance(output.get("trace"), list) else [],
                }
            )
            order += 1
            continue

        summary_max_chars = max(4000, _env_int("REPORT_AGENT_SUMMARY_MAX_CHARS", 12000))
        registry_summary = format_agent_report_summary(agent_name, output)
        if registry_summary is not None:
            summary = registry_summary[:summary_max_chars]
        else:
            summary = _safe_str(output.get("summary") if isinstance(output, dict) else "")[:summary_max_chars]
            summary = _sanitize_deep_search_summary(summary, agent_name)
        confidence = output.get("confidence") if isinstance(output, dict) else None
        try:
            confidence_value = float(confidence) if confidence is not None else 0.6
        except Exception:
            confidence_value = 0.6
        data_sources = output.get("data_sources") if isinstance(output, dict) else None
        if not isinstance(data_sources, list):
            data_sources = []
        raw_output = _to_json_compatible(output if isinstance(output, dict) else {"output": output})
        evidence_full = []
        if isinstance(output, dict) and isinstance(output.get("evidence"), list):
            evidence_full = _to_json_compatible(output.get("evidence"))
        trace_full = []
        if isinstance(output, dict) and isinstance(output.get("trace"), list):
            trace_full = _to_json_compatible(output.get("trace"))

        summaries.append(
            {
                "title": title,
                "order": order,
                "agent_name": agent_name,
                "status": "success",
                "summary": summary or "（无输出）",
                "confidence": max(0.0, min(1.0, confidence_value)),
                "data_sources": [str(x) for x in data_sources if str(x).strip()][:8],
                "evidence_quality": (output.get("evidence_quality") if isinstance(output, dict) and isinstance(output.get("evidence_quality"), dict) else {}),
                "raw_output": raw_output,
                "evidence_full": evidence_full if isinstance(evidence_full, list) else [],
                "trace_full": trace_full if isinstance(trace_full, list) else [],
            }
        )
        order += 1

    return summaries


def _normalize_report_chart_spec(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    chart_type = _safe_str(item.get("type")).strip()
    title = _safe_str(item.get("title")).strip()
    data = item.get("data")
    if not chart_type or not title or not isinstance(data, dict):
        return None
    return {
        "type": chart_type,
        "title": title,
        "data": _to_json_compatible(data),
    }


def _agent_step_ids(plan_steps: list[dict[str, Any]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for step in plan_steps:
        if not isinstance(step, dict) or step.get("kind") != "agent":
            continue
        agent_name = _safe_str(step.get("name")).strip()
        step_id = _safe_str(step.get("id")).strip()
        if not agent_name or not step_id:
            continue
        pair = (agent_name, step_id)
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
    return pairs


def _collect_agent_run_result(
    *,
    run_id: str,
    session_id: str,
    plan_steps: list[dict[str, Any]],
    step_results: dict[str, Any],
) -> dict[str, Any]:
    evidence_items: list[dict[str, Any]] = []
    claim_items: list[dict[str, Any]] = []
    chart_specs: list[dict[str, Any]] = []
    chart_specs_by_agent: dict[str, list[dict[str, Any]]] = {}
    agents: list[str] = []

    for agent_name, step_id in _agent_step_ids(plan_steps):
        raw = step_results.get(step_id) if isinstance(step_results, dict) else None
        output = raw.get("output") if isinstance(raw, dict) else None
        if not isinstance(output, dict) or output.get("skipped") is True:
            continue

        agents.append(agent_name)

        evidence = output.get("evidence")
        if isinstance(evidence, list):
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                normalized = _to_json_compatible(item)
                if not isinstance(normalized, dict):
                    continue
                normalized.setdefault("agent_name", agent_name)
                normalized.setdefault("step_id", step_id)
                evidence_items.append(normalized)
                if len(evidence_items) >= 200:
                    break

        claims = output.get("claims")
        if isinstance(claims, list):
            for item in claims:
                if not isinstance(item, dict):
                    continue
                normalized = _to_json_compatible(item)
                if not isinstance(normalized, dict):
                    continue
                normalized.setdefault("agent_name", agent_name)
                normalized.setdefault("step_id", step_id)
                claim_items.append(normalized)
                if len(claim_items) >= 120:
                    break

        agent_specs: list[dict[str, Any]] = []
        raw_specs = output.get("chart_specs")
        if isinstance(raw_specs, list):
            for item in raw_specs:
                spec = _normalize_report_chart_spec(item)
                if not spec:
                    continue
                agent_specs.append(spec)
                chart_specs.append(spec)
                if len(chart_specs) >= 24:
                    break
        if agent_specs:
            chart_specs_by_agent[agent_name] = agent_specs

    return {
        "run_id": run_id,
        "session_id": session_id,
        "agents": agents,
        "evidence": evidence_items,
        "claims": claim_items,
        "chart_specs": chart_specs,
        "chart_specs_by_agent": chart_specs_by_agent,
        "counts": {
            "agents": len(agents),
            "evidence": len(evidence_items),
            "claims": len(claim_items),
            "chart_specs": len(chart_specs),
        },
    }


# ---------------------------------------------------------------------------
#  core_viewpoints — deterministic agent viewpoint extraction (zero LLM)
# ---------------------------------------------------------------------------

import re as _re

_HEADLINE_SPLIT_RE = _re.compile(r"(?<=[。；\n])|(?<=\.)(?=\s|$)")
_HEADLINE_MAX_LEN = 120


def _extract_headline(summary: str) -> str:
    """Extract the first meaningful sentence from agent summary text.

    Split on Chinese period (。), semicolon (；), newline, or English period
    followed by whitespace/end-of-string (avoids splitting on decimals like 5.3%).
    If the first sentence exceeds _HEADLINE_MAX_LEN chars, truncate with '…'.
    """
    if not summary or not summary.strip():
        return "（无摘要）"

    text = summary.strip()
    # Remove leading markdown bullets / numbering (e.g. "- ", "* ", "## ", "1. ")
    text = _re.sub(r"^[\s\-\*#]*(?:\d+\.\s)?", "", text).strip()
    if not text:
        return "（无摘要）"

    parts = _HEADLINE_SPLIT_RE.split(text, maxsplit=1)
    headline = (parts[0] or "").strip()
    if not headline:
        headline = text[:_HEADLINE_MAX_LEN]

    if len(headline) > _HEADLINE_MAX_LEN:
        headline = headline[:_HEADLINE_MAX_LEN] + "…"

    return headline


def _build_core_viewpoints(
    agent_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build structured per-agent viewpoint list from agent_summaries.

    Pure deterministic extraction — zero LLM, zero external calls.
    Only includes agents with status == "success".
    Returns empty list when no successful agents exist (frontend falls back
    to report.summary markdown blob).
    """
    viewpoints: list[dict[str, Any]] = []

    for ag in agent_summaries:
        if not isinstance(ag, dict):
            continue
        if ag.get("status") != "success":
            continue

        summary_text = _safe_str(ag.get("summary") or "")
        headline = _extract_headline(summary_text)

        evidence_full = ag.get("evidence_full")
        evidence_count = len(evidence_full) if isinstance(evidence_full, list) else 0

        data_sources = ag.get("data_sources")
        if not isinstance(data_sources, list):
            data_sources = []

        try:
            confidence = float(ag.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.0

        viewpoints.append({
            "agent_name": ag.get("agent_name", ""),
            "title": ag.get("title", ag.get("agent_name", "")),
            "headline": headline,
            "detail": summary_text,
            "confidence": confidence,
            "data_sources": [str(s) for s in data_sources if str(s).strip()][:8],
            "evidence_count": evidence_count,
            "status": "success",
        })

    # Preserve original agent ordering
    viewpoints.sort(key=lambda v: next(
        (i for i, a in enumerate(agent_summaries)
         if isinstance(a, dict) and a.get("agent_name") == v["agent_name"]),
        999,
    ))

    return viewpoints


def _extract_risks(render_vars: dict[str, Any] | None) -> list[str]:
    if not isinstance(render_vars, dict):
        return []
    raw = render_vars.get("risks")
    if not isinstance(raw, str) or not raw.strip():
        return []
    lines: list[str] = []
    for line in raw.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        cleaned = cleaned.lstrip("-").strip()
        if not cleaned:
            continue
        # Keep only non-disclaimer risk items.
        if "不构成投资建议" in cleaned or "仅供参考" in cleaned:
            continue
        lines.append(cleaned[:120])
        if len(lines) >= 8:
            break
    return lines


def _agent_report_input_snapshot(
    *,
    agent_name: str,
    query: str,
    ticker_label: str,
    render_vars: dict[str, Any],
    draft_markdown: str,
    used_summary: str,
) -> dict[str, Any]:
    key_map: dict[str, list[str]] = {
        "price_agent": ["price_snapshot", "investment_thesis", "conclusion"],
        "technical_agent": ["technical_snapshot", "investment_thesis", "conclusion"],
        "fundamental_agent": ["company_overview", "valuation", "investment_thesis", "conclusion"],
        "news_agent": ["catalysts", "investment_thesis", "conclusion"],
        "macro_agent": ["investment_thesis", "conclusion", "risks"],
        "deep_search_agent": ["analysis", "highlights", "investment_thesis", "conclusion"],
    }
    selected_keys = key_map.get(agent_name, [])
    render_subset: dict[str, Any] = {}
    for key in selected_keys:
        value = render_vars.get(key)
        if isinstance(value, str) and value.strip():
            render_subset[key] = value
    return {
        "agent_name": agent_name,
        "query": query,
        "ticker_label": ticker_label,
        "synthesis_source_priority": ["draft_markdown", "render_vars", "agent_summaries", "citations"],
        "used_summary": used_summary,
        "render_vars_subset": _to_json_compatible(render_subset),
        "draft_markdown_excerpt": _safe_str(draft_markdown).strip()[:2000],
    }


def _build_long_synthesis_report(
    *,
    ticker_label: str,
    query: str,
    agent_summaries: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    base_markdown: str,
    render_vars: dict[str, Any] | None = None,
) -> str:
    parts: list[str] = []
    title = f"{ticker_label} 综合研究报告"
    parts.append(f"## {title}")
    parts.append("")

    # 1) Use the existing rendered markdown (from template) as the core narrative.
    #    The template already contains: 综合投资观点, 公司与业务, 价格快照, 技术面,
    #    催化剂, 财务与估值, 风险, 结论与展望, 免责声明.
    core = (base_markdown or "").strip()
    if core:
        parts.append(core)
        parts.append("")
    elif query:
        parts.append(f"**问题**：{query}")
        parts.append("")

    successful_agents = [
        item
        for item in agent_summaries
        if isinstance(item, dict)
        and item.get("status") == "success"
        and _safe_str(item.get("summary") or "").strip()
    ]
    if successful_agents:
        parts.append("## 分析师观点")
        for item in successful_agents:
            agent_name = _safe_str(item.get("agent_name") or "").strip()
            title = _safe_str(item.get("title") or agent_name).strip()
            if agent_name:
                try:
                    item_profile = profile(agent_name)
                    title = f"{item_profile.short_zh} · {item_profile.name_zh}"
                except KeyError:
                    pass
            parts.append(f"### {title}")
            parts.append(_safe_str(item.get("summary") or "").strip())
            parts.append("")

    # 2) Citation references (only when citations exist — real data, not filler).
    if citations:
        parts.append("## 引用来源")
        for c in citations[:12]:
            if not isinstance(c, dict):
                continue
            cid = _safe_str(c.get("source_id") or "")
            title = _safe_str(c.get("title") or c.get("url") or "")[:180]
            url = _safe_str(c.get("url") or "")
            if url:
                parts.append(f"[{cid}] [{title}]({url})")
            elif title:
                parts.append(f"[{cid}] {title}")
        parts.append("")

    # 3) Brief data coverage note (never generic template filler).
    not_run_agents = [
        item for item in agent_summaries
        if isinstance(item, dict) and item.get("status") in ("not_run", "error")
    ]
    if not_run_agents:
        parts.append("---")
        parts.append(
            "*注：以下模块本轮未触发或执行失败，如需更全面分析可尝试启用 live tools 或调整查询关键词：*"
        )
        names = [_safe_str(a.get("title") or a.get("agent_name") or "") for a in not_run_agents]
        parts.append(f"*{', '.join(n for n in names if n)}*")
        parts.append("")

    initial = "\n".join([p for p in parts if p is not None]).strip() + "\n"
    return _extend_synthesis_report_if_short(
        synthesis_report=initial,
        ticker_label=ticker_label,
        query=query,
        render_vars=render_vars,
        agent_summaries=agent_summaries,
        citations=citations,
    )


def _derive_report_tags_and_hints(
    *,
    subject_type: str,
    tickers: list[str],
    render_vars: dict[str, Any],
    agent_status: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    compare_basis: list[str] = []
    if len(tickers) > 1:
        compare_basis.append("multi_ticker")

    comparison_conclusion = _safe_str(render_vars.get("comparison_conclusion") or "").strip()
    if comparison_conclusion:
        compare_basis.append("comparison_conclusion")

    comparison_metrics = render_vars.get("comparison_metrics")
    if isinstance(comparison_metrics, str) and comparison_metrics.strip():
        compare_basis.append("comparison_metrics")

    is_compare = len(compare_basis) > 0

    conflict_agents: list[str] = []
    for agent_name, payload in agent_status.items():
        if not isinstance(agent_name, str) or not isinstance(payload, dict):
            continue
        evidence_quality = payload.get("evidence_quality")
        has_conflicts = (
            isinstance(evidence_quality, dict)
            and evidence_quality.get("has_conflicts") is True
        )
        if has_conflicts:
            conflict_agents.append(agent_name)

    conflict_agents = sorted(set(conflict_agents))
    has_conflict = len(conflict_agents) > 0

    tags: list[str] = []
    if is_compare:
        tags.append("compare")
    if has_conflict:
        tags.append("conflict")
    if subject_type in ("filing", "research_doc"):
        tags.append("filing")

    hints: dict[str, Any] = {
        "is_compare": is_compare,
        "has_conflict": has_conflict,
        "compare_basis": compare_basis,
        "conflict_agents": conflict_agents,
    }
    return tags, hints


def _is_deep_report_query(query: str) -> bool:
    return _classify_report_type(query) == "deep_financial"






















def _build_structured_report_payload(
    *, state: dict[str, Any], thread_id: str, artifacts: dict[str, Any]
) -> dict[str, Any] | None:
    synthesis = artifacts.get("research_synthesis")
    gate = artifacts.get("research_synthesis_gate")
    markdown = artifacts.get("draft_markdown")
    if not isinstance(synthesis, dict) or not isinstance(gate, dict) or not isinstance(markdown, str):
        return None

    blocked = gate.get("state") == "block"
    subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
    tickers = [
        str(item).strip().upper()
        for item in (subject.get("tickers") if isinstance(subject.get("tickers"), list) else [])
        if str(item).strip()
    ]
    ticker_label = " vs ".join(tickers[:4]) if tickers else "N/A"
    overall = str(synthesis.get("overall_conclusion") or "").strip()
    evidence_index = synthesis.get("evidence_index") if isinstance(synthesis.get("evidence_index"), dict) else {}
    claim_index = synthesis.get("claim_index") if isinstance(synthesis.get("claim_index"), dict) else {}
    citation_ids = synthesis.get("citation_ids") if isinstance(synthesis.get("citation_ids"), list) else []
    citations = [] if blocked else [
        {
            "source_id": source_id,
            "title": str((evidence_index.get(source_id) or {}).get("title") or (evidence_index.get(source_id) or {}).get("source_name") or source_id),
            "url": str((evidence_index.get(source_id) or {}).get("url") or "#"),
            "snippet": str((evidence_index.get(source_id) or {}).get("text") or ""),
            "published_date": str((evidence_index.get(source_id) or {}).get("as_of") or ""),
            "confidence": 0.7,
        }
        for source_id in citation_ids
        if isinstance(source_id, str) and isinstance(evidence_index.get(source_id), dict)
    ]
    public_synthesis = None if blocked else synthesis
    report_quality = {
        "state": "block" if blocked else ("degraded" if gate.get("state") == "degraded" else "pass"),
        "reasons": list(gate.get("reasons") or []),
        "synthesis_gate": gate,
    }
    base = {
        "report_id": f"lg_{uuid.uuid4().hex[:10]}",
        "ticker": ticker_label,
        "company_name": ticker_label,
        "title": "报告暂不可用" if blocked else f"{ticker_label} 分析报告",
        "summary": "本轮结果未通过内部一致性校验。" if blocked else (overall or "证据不足，无法形成总判断。"),
        "sentiment": "neutral",
        "confidence_score": 0.0 if blocked else (0.45 if gate.get("state") == "degraded" else 0.8),
        "generated_at": _now_iso(),
        "sections": [{
            "title": "研究报告",
            "order": 1,
            "agent_name": "research_synthesis",
            "confidence": 0.0 if blocked else 0.7,
            "data_sources": [item["source_id"] for item in citations],
            "contents": [{"type": "text", "content": markdown, "citation_refs": [item["source_id"] for item in citations]}],
        }],
        "citations": citations,
        "risks": [] if blocked else list(synthesis.get("risks") or []),
        "recommendation": None,
        "meta": {
            "source": "langgraph",
            "thread_id": thread_id,
            "subject_type": str(subject.get("subject_type") or "unknown"),
            "report_quality": report_quality,
            **({"research_synthesis": public_synthesis} if public_synthesis is not None else {}),
        },
        "report_quality": report_quality,
    }
    validated = ReportValidator.validate_and_fix(base, as_dict=True)
    payload = validated if isinstance(validated, dict) else base
    payload.update({
        "synthesis_report": markdown,
        "draft_markdown": markdown,
        "report_quality": report_quality,
        "quality_blocked": blocked,
        "publishable": not blocked,
        "agent_claims": [] if blocked else list(claim_index.values()),
        "agent_evidence": [] if blocked else list(evidence_index.values()),
        "chart_specs": [],
    })
    if blocked:
        payload["error_code"] = "synthesis_quality_blocked"
        payload.get("meta", {}).pop("research_synthesis", None)
    else:
        payload.setdefault("meta", {})["research_synthesis"] = synthesis
    payload.setdefault("meta", {})["report_quality"] = report_quality
    return payload


def build_report_payload(*, state: dict[str, Any], query: str, thread_id: str) -> dict[str, Any] | None:
    """
    Build a frontend-friendly ReportIR payload (used by ReportView cards) from LangGraph state.
    This is intentionally deterministic: it never requires an LLM call to be useful.
    """
    output_mode = state.get("output_mode")
    if output_mode != "investment_report":
        return None

    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    structured = _build_structured_report_payload(state=state, thread_id=thread_id, artifacts=artifacts)
    if structured is not None:
        return structured

    try:
        return _build_report_payload_impl(state=state, query=query, thread_id=thread_id)
    except Exception as exc:
        logger.exception("[ReportBuilder] build_report_payload failed: %s", exc)
        fallback = {
            "report_id": f"lg_{uuid.uuid4().hex[:10]}",
            "ticker": "N/A",
            "company_name": "N/A",
            "title": "报告生成降级输出",
            "summary": "报告生成过程中发生异常，已返回最小可用结果。",
            "sentiment": "neutral",
            "confidence_score": 0.2,
            "generated_at": _now_iso(),
            "sections": [
                {
                    "title": "系统降级说明",
                    "order": 1,
                    "agent_name": "report_builder",
                    "confidence": 0.2,
                    "data_sources": ["system"],
                    "contents": [{"type": "text", "content": f"报告构建异常：{_safe_str(exc)[:400]}"}],
                }
            ],
            "citations": [],
            "risks": ["报告已降级，请稍后重试或检查上游数据源与 LLM 通道。"],
            "recommendation": "HOLD",
            "meta": {
                "source": "langgraph",
                "thread_id": thread_id,
                "subject_type": "unknown",
                "builder_fallback": True,
                "builder_error": _safe_str(exc)[:500],
            },
            "synthesis_report": "## 投资摘要\n- 报告生成过程中发生异常，已返回最小可用结果。",
            "agent_status": {},
            "report_hints": {},
        }
        validated_fallback = ReportValidator.validate_and_fix(fallback, as_dict=True)
        if isinstance(validated_fallback, dict):
            validated_fallback["synthesis_report"] = fallback["synthesis_report"]
            validated_fallback["agent_status"] = fallback["agent_status"]
            validated_fallback["report_hints"] = fallback["report_hints"]
            validated_fallback["meta"] = fallback["meta"]
            return validated_fallback
        return fallback


def _build_report_payload_impl(*, state: dict[str, Any], query: str, thread_id: str) -> dict[str, Any] | None:

    subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
    subject_type = subject.get("subject_type") if isinstance(subject, dict) else "unknown"

    tickers = subject.get("tickers") if isinstance(subject, dict) else None
    tickers = tickers if isinstance(tickers, list) else []
    tickers = [str(t).strip().upper() for t in tickers if isinstance(t, str) and t.strip()]
    # 规范化去重：防止 "GOOGL" 与 "GOOGLE" 共存
    try:
        from backend.config.ticker_mapping import dedup_tickers
        tickers = dedup_tickers(tickers)
    except Exception:
        # 兜底去重（不依赖 COMPANY_MAP）
        tickers = list(dict.fromkeys(tickers))
    ticker_label = " vs ".join(tickers[:4]) if len(tickers) > 1 else (tickers[0] if tickers else "N/A")

    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    render_vars = artifacts.get("render_vars") if isinstance(artifacts.get("render_vars"), dict) else {}
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts.get("evidence_pool"), list) else []
    query_coverage = artifacts.get("query_coverage") if isinstance(artifacts.get("query_coverage"), dict) else {}
    debate = artifacts.get("debate") if isinstance(artifacts.get("debate"), dict) else {}
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    errors = artifacts.get("errors") if isinstance(artifacts.get("errors"), list) else []
    draft_markdown = _safe_str(artifacts.get("draft_markdown") or "")
    verifier_result = artifacts.get("verifier_result") if isinstance(artifacts.get("verifier_result"), dict) else {}
    verifier_claims_raw = verifier_result.get("unsupported_claims") if isinstance(verifier_result, dict) else []
    verifier_claims = verifier_claims_raw if isinstance(verifier_claims_raw, list) else []
    verifier_unresolved_raw = (
        verifier_result.get("unresolved_unsupported_claims")
        if isinstance(verifier_result, dict)
        else []
    )
    verifier_unresolved_claims = verifier_unresolved_raw if isinstance(verifier_unresolved_raw, list) else []
    verifier_claims_for_gate = (
        verifier_unresolved_claims
        if isinstance(verifier_unresolved_raw, list)
        else verifier_claims
    )

    plan_ir = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
    plan_steps = plan_ir.get("steps") if isinstance(plan_ir.get("steps"), list) else []

    policy = state.get("policy") if isinstance(state.get("policy"), dict) else {}
    allowed_agents = policy.get("allowed_agents") if isinstance(policy.get("allowed_agents"), list) else []
    allowed_agents = [str(a) for a in allowed_agents if isinstance(a, str) and a.strip()]
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}

    # Evidence pool → citations
    citation_build = _build_citations(evidence_pool)
    citations = citation_build.citations
    filing_section_citations = (
        _build_filing_section_citations(citations)
        if subject_type in ("filing", "research_doc")
        else []
    )

    # Agent summaries/status
    agent_status = _agent_status_from_steps(
        allowed_agents=allowed_agents,
        plan_steps=plan_steps,
        step_results=step_results,
        errors=errors,
    )
    agent_summaries = _agent_summaries_from_steps(
        allowed_agents=allowed_agents,
        plan_steps=plan_steps,
        step_results=step_results,
        errors=errors,
    )
    for item in agent_summaries:
        if not isinstance(item, dict):
            continue
        agent_name = _safe_str(item.get("agent_name") or "").strip()
        item["report_input"] = _agent_report_input_snapshot(
            agent_name=agent_name,
            query=query,
            ticker_label=ticker_label,
            render_vars=render_vars if isinstance(render_vars, dict) else {},
            draft_markdown=draft_markdown,
            used_summary=_safe_str(item.get("summary") or ""),
        )

    # Section list: show each agent summary as its own section for rendering.
    # Build agent_name → evidence URLs mapping for citation bridging.
    steps_by_agent: dict[str, str] = {}
    for step in plan_steps:
        if not isinstance(step, dict):
            continue
        if step.get("kind") == "agent" and isinstance(step.get("name"), str) and isinstance(step.get("id"), str):
            steps_by_agent[step["name"].strip()] = step["id"].strip()

    def _ensure_internal_citation(
        *,
        agent_name: str,
        source: str,
        title: str,
        snippet: str,
        timestamp: str,
        confidence: Any,
    ) -> str | None:
        key = _build_internal_citation_key(
            agent_name=agent_name,
            source=source,
            title=title,
            snippet=snippet,
            timestamp=timestamp,
        )
        if not key:
            return None

        existing = citation_build.id_by_internal_key.get(key)
        if existing:
            return existing

        source_id = str(len(citations) + 1)
        citation_build.id_by_internal_key[key] = source_id
        citations.append(
            {
                "source_id": source_id,
                "title": _safe_str(title or source or f"{agent_name} evidence")[:180] or f"{agent_name} evidence",
                "url": _build_internal_citation_url(
                    agent_name=agent_name,
                    source=source,
                    title=title,
                ),
                "snippet": _safe_str(snippet)[:400],
                "published_date": _safe_str(timestamp),
                "confidence": _safe_confidence(confidence if confidence is not None else 0.55),
                "freshness_hours": _freshness_hours(timestamp),
                "section_ref": None,
                "source_type": "internal_agent_evidence",
            }
        )
        return source_id

    def _get_agent_citation_refs(agent_name: str) -> list[str]:
        """Resolve section citation refs from agent evidence (URL + internal fallback)."""
        sid = steps_by_agent.get(agent_name)
        if not sid:
            return []
        raw = step_results.get(sid) if isinstance(step_results, dict) else None
        output = raw.get("output") if isinstance(raw, dict) else None
        if not isinstance(output, dict):
            return []
        evidence = output.get("evidence")
        if not isinstance(evidence, list):
            return []
        refs: list[str] = []
        for index, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                continue
            url = ev.get("url")
            source_id = None
            if isinstance(url, str) and url.strip():
                raw_url = url.strip()
                normalized_url = _canonicalize_url_for_citation_match(raw_url)
                candidate_keys: list[str] = [raw_url]
                if normalized_url and normalized_url not in candidate_keys:
                    candidate_keys.append(normalized_url)
                if raw_url.endswith("/") and raw_url.rstrip("/") not in candidate_keys:
                    candidate_keys.append(raw_url.rstrip("/"))
                for key in candidate_keys:
                    source_id = citation_build.id_by_url.get(key)
                    if source_id:
                        break

            if not source_id:
                source_text = _safe_str(ev.get("source") or agent_name).strip() or agent_name
                title_text = _safe_str(ev.get("title") or f"{agent_name} evidence {index + 1}").strip()
                snippet_text = _safe_str(
                    ev.get("text")
                    or ev.get("snippet")
                    or ev.get("summary")
                    or "",
                ).strip()
                timestamp_text = _safe_str(ev.get("timestamp") or output.get("as_of") or "").strip()
                confidence_value = ev.get("confidence", output.get("confidence"))
                source_id = _ensure_internal_citation(
                    agent_name=agent_name,
                    source=source_text,
                    title=title_text,
                    snippet=snippet_text,
                    timestamp=timestamp_text,
                    confidence=confidence_value,
                )
            if source_id and source_id not in refs:
                refs.append(source_id)
        return refs

    sections: list[dict[str, Any]] = []
    section_order = 1
    for item in agent_summaries:
        status = _safe_str(item.get("status") or "").strip().lower()
        if status != "success":
            continue
        title = _safe_str(item.get("title") or "")
        if not title:
            continue
        agent_name = item.get("agent_name") or ""
        summary_text = _safe_str(item.get("summary") or "").strip()
        if not summary_text:
            continue
        refs = _get_agent_citation_refs(agent_name)
        sections.append(
            {
                "title": title,
                "order": section_order,
                "agent_name": agent_name,
                "confidence": item.get("confidence"),
                "data_sources": item.get("data_sources", []),
                "contents": [
                    {
                        "type": "text",
                        "content": summary_text,
                        "citation_refs": refs,
                        "metadata": {},
                    }
                ],
            }
        )
        section_order += 1

    if filing_section_citations:
        lines = []
        section_ref_ids: list[str] = []
        for item in filing_section_citations[:24]:
            section = _safe_str(item.get("section") or "").strip()
            source_ids = item.get("source_ids") if isinstance(item.get("source_ids"), list) else []
            normalized_source_ids = [_safe_str(x).strip() for x in source_ids if _safe_str(x).strip()]
            section_ref_ids.extend(normalized_source_ids)
            display_source_ids = [f"[{source_id}]" for source_id in normalized_source_ids]
            if not section:
                continue
            if display_source_ids:
                lines.append(f"- {section}: {', '.join(display_source_ids)}")
            else:
                lines.append(f"- {section}")
        section_ref_ids = sorted(set(section_ref_ids))
        sections.append(
            {
                "title": "Section-level Citations",
                "order": section_order,
                "agent_name": "filing_citation_mapper",
                "confidence": 0.9,
                "data_sources": ["evidence_pool"],
                "contents": [
                    {
                        "type": "text",
                        "content": "\n".join(lines) if lines else "- N/A",
                        "citation_refs": section_ref_ids,
                        "metadata": {"exclude_from_quality_coverage": True},
                    }
                ],
            }
        )
        section_order += 1

    risks = _extract_risks(render_vars)
    report_tags, report_hints = _derive_report_tags_and_hints(
        subject_type=subject_type,
        tickers=tickers,
        render_vars=render_vars,
        agent_status=agent_status,
    )
    market_hint = _safe_str((ui_context or {}).get("market") or "").strip().upper() or None
    quality_hints = _build_report_quality_hints(
        query=query,
        citations=citations,
        tickers=tickers,
        market=market_hint,
    )
    report_hints["quality"] = quality_hints
    if query_coverage:
        report_hints["query_coverage"] = query_coverage
    if debate.get("status") == "done":
        report_hints["has_debate"] = True
        report_hints["debate"] = {
            "judge_scorecard": debate.get("judge_scorecard") if isinstance(debate.get("judge_scorecard"), dict) else {},
            "consensus": debate.get("consensus"),
            "open_questions": debate.get("open_questions") if isinstance(debate.get("open_questions"), list) else [],
        }
        if "debate" not in report_tags:
            report_tags.append("debate")
    if isinstance(verifier_result, dict) and verifier_result:
        report_hints["verifier"] = {
            "enabled": bool(verifier_result.get("enabled")),
            "checked": bool(verifier_result.get("checked")),
            "unsupported_count": len(verifier_claims),
            "unresolved_unsupported_count": len(verifier_claims_for_gate),
            "unsupported_claims": verifier_claims[:6],
            "unresolved_unsupported_claims": verifier_claims_for_gate[:6],
        }

    # Confidence: average of successful agents, else 0.5.
    confidences = []
    for v in agent_status.values():
        if not isinstance(v, dict):
            continue
        if v.get("status") != "success":
            continue
        try:
            confidences.append(float(v.get("confidence", 0.0)))
        except Exception:
            pass
    confidence_score = sum(confidences) / len(confidences) if confidences else 0.55
    confidence_score = max(0.0, min(1.0, confidence_score))

    summary = ""
    if isinstance(render_vars.get("investment_summary"), str) and render_vars.get("investment_summary").strip():
        summary = render_vars.get("investment_summary").strip()
    elif isinstance(render_vars.get("comparison_conclusion"), str) and render_vars.get("comparison_conclusion").strip():
        summary = render_vars.get("comparison_conclusion").strip()
    elif draft_markdown:
        summary = draft_markdown.splitlines()[0][:200]
    else:
        summary = "（暂无摘要）"

    synthesis_report = _build_long_synthesis_report(
        ticker_label=ticker_label,
        query=query,
        agent_summaries=agent_summaries,
        citations=citations,
        base_markdown=draft_markdown,
        render_vars=render_vars,
    )

    quality_missing = quality_hints.get("missing_requirements") if isinstance(quality_hints, dict) else []
    quality_missing_counts = quality_hints.get("missing_counts") if isinstance(quality_hints, dict) else {}
    if (
        isinstance(quality_missing, list)
        and quality_missing
        and quality_hints.get("deep_report_required") is True
    ):
        gap = "；".join([_safe_str(x).strip() for x in quality_missing if _safe_str(x).strip()][:6])
        quality_warning = f"深度报告质量门槛未满足：{gap}"
        if quality_warning not in risks:
            risks.insert(0, quality_warning)
        critical = int((quality_missing_counts or {}).get("critical") or 0)
        important = int((quality_missing_counts or {}).get("important") or 0)
        minor = int((quality_missing_counts or {}).get("minor") or 0)
        penalty = critical * 0.08 + important * 0.05 + minor * 0.03
        confidence_score = max(0.45, confidence_score - penalty)
        if quality_warning not in summary:
            summary = f"{summary}（{quality_warning}）"
        synthesis_report = (
            f"{synthesis_report.rstrip()}\n\n"
            "## 研究完整性校验\n"
            f"- {quality_warning}\n"
            "- 建议补齐 10-K / 10-Q / 业绩电话会纪要 / 权威媒体正文摘录后再执行投资决策。\n"
        )
        if "quality_gap" not in report_tags:
            report_tags.append("quality_gap")

    # --- 数据完整性披露：汇总 optional 步骤的静默失败 ---
    # executor 对 optional 步骤失败只 append 到 artifacts["errors"] 后 continue，不 raise。
    # 这些 errors 仅当 step_id 命中某个 agent 步骤时才会显示为该 agent 的 error 状态；
    # 而非 agent 的 optional 步骤（如数据源拉取）失败会成为"孤儿 error"，对用户完全不可见。
    # 这里把孤儿失败汇总成一条数据完整性风险，让"某数据源静默缺失"可见。
    _agent_step_ids: set[str] = set()
    for _step in plan_steps:
        if not isinstance(_step, dict):
            continue
        if _step.get("kind") == "agent" and isinstance(_step.get("id"), str) and _step.get("id").strip():
            _agent_step_ids.add(_step.get("id").strip())

    orphan_failures: list[str] = []
    for _err in errors:
        if not isinstance(_err, dict):
            continue
        if not bool(_err.get("optional")):
            continue
        _sid = _safe_str(_err.get("step_id") or "").strip()
        if _sid and _sid in _agent_step_ids:
            continue  # 已通过 agent 状态暴露，跳过
        _name = _safe_str(_err.get("name") or _err.get("kind") or _sid or "未知步骤").strip()
        _etype = _safe_str(_err.get("error_type") or "").strip()
        label = f"{_name}（{_etype}）" if _etype else _name
        if label and label not in orphan_failures:
            orphan_failures.append(label)

    if orphan_failures:
        shown = orphan_failures[:6]
        gap_text = "；".join(shown)
        more = f" 等共 {len(orphan_failures)} 项" if len(orphan_failures) > len(shown) else ""
        completeness_risk = (
            f"以下可选数据步骤静默失败、对应数据源缺失：{gap_text}{more}。"
            "相关维度的数据可能不完整，请结合数据完整性谨慎解读结论。"
        )
        if completeness_risk not in risks:
            risks.insert(0, completeness_risk)
        synthesis_report = (
            f"{synthesis_report.rstrip()}\n\n"
            "## 数据完整性说明\n"
            f"- 本轮有 {len(orphan_failures)} 项可选数据步骤未成功获取，相关数据源静默缺失：\n"
            + "\n".join(f"  - {item}" for item in shown)
            + (f"\n  - …等共 {len(orphan_failures)} 项\n" if len(orphan_failures) > len(shown) else "\n")
        )
        if "data_completeness_gap" not in report_tags:
            report_tags.append("data_completeness_gap")

    # --- Conflict disclosure gate: inject conflicts into report ---
    conflict_disclosure = _safe_str(render_vars.get("conflict_disclosure") or "").strip()
    is_degraded_conflict = "冲突检测降级" in conflict_disclosure
    has_active_conflicts = "待进一步验证" in conflict_disclosure

    if conflict_disclosure:
        synthesis_report = (
            f"{synthesis_report.rstrip()}\n\n"
            "## 数据冲突披露\n"
            f"{conflict_disclosure}\n"
        )

        if is_degraded_conflict:
            # Only 1 agent succeeded in deep report mode → severe confidence penalty
            confidence_score = min(confidence_score, 0.45)
            degraded_risk = "冲突检测降级：仅单一维度证据可用，无法交叉验证"
            if degraded_risk not in risks:
                risks.insert(0, degraded_risk)
            if "conflict_degraded" not in report_tags:
                report_tags.append("conflict_degraded")
        elif has_active_conflicts:
            # Count unresolved conflicts to penalize confidence
            unresolved_count = conflict_disclosure.count("待进一步验证")
            confidence_score = min(confidence_score, max(0.45, 0.75 - 0.05 * unresolved_count))
            conflict_risk = f"存在 {unresolved_count} 项跨智能体数据冲突尚未裁决，结论可信度受限"
            if conflict_risk not in risks:
                risks.insert(0, conflict_risk)

        if "conflict" not in report_tags and (has_active_conflicts or is_degraded_conflict):
            report_tags.append("conflict")

    challenges = debate.get("challenges") if isinstance(debate.get("challenges"), list) else []
    if challenges:
        challenge_lines = ["## 风险质询"]
        for item in challenges[:3]:
            if not isinstance(item, dict):
                continue
            target = _safe_str(item.get("target_agent") or "").strip()
            text = _safe_str(item.get("challenge_zh") or "").strip()
            if not target or not text:
                continue
            try:
                target_name = profile(target).name_zh
            except KeyError:
                target_name = target
            challenge_lines.append(f"- ⚠ 对{target_name}: {text}")
        if len(challenge_lines) > 1:
            synthesis_report = f"{synthesis_report.rstrip()}\n\n" + "\n".join(challenge_lines) + "\n"
            if "debate" not in report_tags:
                report_tags.append("debate")

    grounding_stats = _compute_grounding_stats(
        generated_text=synthesis_report,
        citations=citations,
        agent_summaries=agent_summaries,
        render_vars=render_vars,
        step_results=step_results,
    )
    grounding_rate = grounding_stats.get("grounding_rate")
    if isinstance(quality_hints, dict):
        quality_hints["grounding"] = grounding_stats
    if isinstance(report_hints, dict):
        report_hints["grounding"] = grounding_stats

    if isinstance(grounding_rate, float):
        if grounding_rate < 0.6:
            grounding_risk = f"证据溯源率偏低（{grounding_rate:.0%}），部分断言可能缺少直接证据支持"
            if grounding_risk not in risks:
                risks.insert(0, grounding_risk)
            confidence_score = min(confidence_score, 0.6)
            if "grounding_gap" not in report_tags:
                report_tags.append("grounding_gap")
        elif grounding_rate < 0.75:
            confidence_score = min(confidence_score, 0.7)

    if verifier_claims_for_gate:
        verifier_risk = f"二次事实核查发现 {len(verifier_claims_for_gate)} 条断言缺少直接证据，请重点复核引用与摘录。"
        if verifier_risk not in risks:
            risks.insert(0, verifier_risk)
        confidence_score = min(confidence_score, 0.58)
        if "verifier_gap" not in report_tags:
            report_tags.append("verifier_gap")

    query_coverage_warning = coverage_warning_text(query_coverage) if query_coverage else ""
    if query_coverage_warning:
        if query_coverage_warning not in risks:
            risks.insert(0, query_coverage_warning)
        if "query_coverage_gap" not in report_tags:
            report_tags.append("query_coverage_gap")
        if confidence_score > 0.5:
            confidence_score = max(0.5, confidence_score - 0.06)

    # Title by subject type
    if subject_type in ("news_item", "news_set"):
        title = f"{ticker_label} 新闻事件研报"
    elif subject_type in ("filing", "research_doc"):
        title = "文档研读报告"
    elif subject_type == "company" and len(tickers) > 1:
        title = f"{ticker_label} 对比研报"
    else:
        title = f"{ticker_label} 分析报告"

    report_id = f"lg_{uuid.uuid4().hex[:10]}"
    run_id = _safe_str(ui_context.get("run_id") or state.get("run_id") or report_id).strip() or report_id
    prediction_archive = _archive_report_predictions(
        report_id=report_id,
        user_id=_safe_str(ui_context.get("__user_id") or "").strip(),
        plan_steps=plan_steps,
        step_results=step_results,
    )
    run_result = _collect_agent_run_result(
        run_id=run_id,
        session_id=thread_id,
        plan_steps=plan_steps,
        step_results=step_results,
    )

    base_report_dict: dict[str, Any] = {
        "report_id": report_id,
        "ticker": ticker_label,
        "company_name": ticker_label,
        "title": title,
        "summary": summary,
        "sentiment": "neutral",
        "confidence_score": confidence_score,
        "grounding_rate": grounding_rate,
        "query_coverage": query_coverage,
        "generated_at": _now_iso(),
        "sections": sections,
        "citations": citations,
        "risks": risks,
        "recommendation": "HOLD",
        "meta": {
            "source": "langgraph",
            "thread_id": thread_id,
            "subject_type": subject_type,
            "agent_summaries": agent_summaries,
            "filing_section_citations": filing_section_citations,
            "report_hints": report_hints,
            "grounding": grounding_stats,
            "verifier": verifier_result,
            "prediction_archive": prediction_archive,
            "report_builder_input": {
                "query": query,
                "ticker_label": ticker_label,
                "draft_markdown": draft_markdown,
                "render_vars": _to_json_compatible(render_vars),
                "citations_count": len(citations),
                "agent_count": len(agent_summaries),
            },
            "graph_trace": state.get("trace") if isinstance(state.get("trace"), dict) else {},
        },
    }

    validated = ReportValidator.validate_and_fix(base_report_dict, as_dict=True)
    # Preserve frontend-only extensions (ReportView reads these at the top level).
    if isinstance(validated, dict):
        validated["synthesis_report"] = synthesis_report
        validated["agent_status"] = agent_status
        validated["conflict_disclosure"] = conflict_disclosure
        validated["report_hints"] = report_hints
        validated["grounding_rate"] = grounding_rate
        validated["query_coverage"] = query_coverage
        validated["run_id"] = run_id
        validated["run_result"] = run_result
        validated["chart_specs"] = run_result.get("chart_specs", [])
        validated["agent_evidence"] = run_result.get("evidence", [])
        validated["agent_claims"] = run_result.get("claims", [])
        if debate:
            validated["debate"] = debate
        # P2-1 护城河前置：把幻觉洗涤结果暴露到 top-level，前端 FactCheckCard 消费。
        # 数据来自真实验证器输出；零问题时也展示「全部通过」状态以体现核查行为。
        validated["fact_check"] = _build_fact_check_payload(verifier_result, verifier_claims)
        validated["core_viewpoints"] = _build_core_viewpoints(agent_summaries)
        # P0-3d: structured agent diagnostics for frontend observability
        agent_diagnostics: dict[str, dict[str, Any]] = {}
        for ag_name, ag_info in agent_status.items():
            if not isinstance(ag_info, dict):
                continue
            agent_diagnostics[ag_name] = {
                "status": ag_info.get("status", "unknown"),
                "fallback_reason": ag_info.get("fallback_reason"),
                "retryable": ag_info.get("retryable", False),
                "error_stage": ag_info.get("error_stage"),
                "confidence": ag_info.get("confidence", 0.0),
                "has_conflicts": ag_info.get("has_conflicts", False),
                "conflict_flags": ag_info.get("conflict_flags", []),
            }
        validated["agent_diagnostics"] = agent_diagnostics
        if report_tags:
            validated["tags"] = report_tags

        meta = validated.get("meta") if isinstance(validated.get("meta"), dict) else {}
        meta["report_hints"] = report_hints
        meta["grounding"] = grounding_stats
        meta["query_coverage"] = query_coverage
        if debate:
            meta["debate"] = debate
        meta["verifier"] = verifier_result
        meta["prediction_archive"] = prediction_archive
        meta["run_id"] = run_id
        meta["run_result"] = run_result
        meta["chart_specs"] = run_result.get("chart_specs", [])
        existing_quality = (
            validated.get("report_quality")
            if isinstance(validated.get("report_quality"), dict)
            else (meta.get("report_quality") if isinstance(meta.get("report_quality"), dict) else {})
        )
        merged_quality = evaluate_runtime_report_quality(
            existing_quality=existing_quality,
            quality_hints=quality_hints if isinstance(quality_hints, dict) else {},
            grounding_stats=grounding_stats if isinstance(grounding_stats, dict) else {},
            verifier_claims=verifier_claims_for_gate if isinstance(verifier_claims_for_gate, list) else [],
        )
        validated["report_quality"] = merged_quality
        meta["report_quality"] = merged_quality
        report_hints["quality_state"] = merged_quality.get("state", "pass")
        report_hints["quality_reasons"] = merged_quality.get("reasons", [])
        validated["meta"] = meta
        return _harden_report_payload(validated)
    return None
