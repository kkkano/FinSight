# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.report.validator import ReportValidator


_AGENT_TITLE_MAP: dict[str, str] = {
    "price_agent": "价格分析",
    "news_agent": "新闻分析",
    "technical_agent": "技术分析",
    "fundamental_agent": "基本面分析",
    "macro_agent": "宏观分析",
    "deep_search_agent": "深度搜索",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


@dataclass
class _CitationBuild:
    citations: list[dict[str, Any]]
    id_by_url: dict[str, str]


_FILING_SECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bItem\s+(\d+[A-Za-z]?)\b", flags=re.IGNORECASE),
    re.compile(r"\bNote\s+(\d+[A-Za-z]?)\b", flags=re.IGNORECASE),
    re.compile(r"\bPart\s+([IVX]+)\b", flags=re.IGNORECASE),
]


def _detect_filing_section_ref(item: dict[str, Any]) -> str | None:
    text = " ".join(
        [
            _safe_str(item.get("title") or ""),
            _safe_str(item.get("snippet") or ""),
            _safe_str((item.get("metadata") or {}).get("section") if isinstance(item.get("metadata"), dict) else ""),
        ]
    )
    if not text:
        return None
    for pattern in _FILING_SECTION_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        key = pattern.pattern.lower()
        value = m.group(1).upper()
        if "item" in key:
            return f"Item {value}"
        if "note" in key:
            return f"Note {value}"
        if "part" in key:
            return f"Part {value}"
    return None


def _build_filing_section_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    section_map: dict[str, list[str]] = {}
    for item in citations:
        if not isinstance(item, dict):
            continue
        section = _safe_str(item.get("section_ref") or "").strip()
        source_id = _safe_str(item.get("source_id") or "").strip()
        if not section or not source_id:
            continue
        section_map.setdefault(section, [])
        if source_id not in section_map[section]:
            section_map[section].append(source_id)

    ordered = sorted(section_map.items(), key=lambda kv: kv[0])
    return [{"section": section, "source_ids": source_ids} for section, source_ids in ordered]


def _safe_confidence(value: Any, default: float = 0.7) -> float:
    """Convert confidence to float safely — handles 'high'/'medium'/'low' strings."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _build_citations(evidence_pool: list[dict[str, Any]] | None) -> _CitationBuild:
    citations: list[dict[str, Any]] = []
    id_by_url: dict[str, str] = {}
    if not isinstance(evidence_pool, list):
        return _CitationBuild(citations=citations, id_by_url=id_by_url)

    for item in evidence_pool:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        url = url.strip()
        if url in id_by_url:
            continue
        source_id = str(len(citations) + 1)
        id_by_url[url] = source_id
        citations.append(
            {
                "source_id": source_id,
                "title": _safe_str(item.get("title") or item.get("source") or url)[:180] or url,
                "url": url,
                "snippet": _safe_str(item.get("snippet") or "")[:400],
                "published_date": _safe_str(item.get("published_date") or ""),
                "confidence": _safe_confidence(item.get("confidence", 0.7)),
                "freshness_hours": _freshness_hours(item.get("published_date")),
                "section_ref": _detect_filing_section_ref(item),
            }
        )
        if len(citations) >= 24:
            break

    return _CitationBuild(citations=citations, id_by_url=id_by_url)


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

    summaries: list[dict[str, Any]] = []
    order = 1
    for agent_name in allowed_agents:
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
                }
            )
            order += 1
            continue

        summary = _safe_str(output.get("summary") if isinstance(output, dict) else "")[:4000]
        confidence = output.get("confidence") if isinstance(output, dict) else None
        try:
            confidence_value = float(confidence) if confidence is not None else 0.6
        except Exception:
            confidence_value = 0.6
        data_sources = output.get("data_sources") if isinstance(output, dict) else None
        if not isinstance(data_sources, list):
            data_sources = []

        summaries.append(
            {
                "title": title,
                "order": order,
                "agent_name": agent_name,
                "status": "success",
                "summary": summary or "（无输出）",
                "confidence": max(0.0, min(1.0, confidence_value)),
                "data_sources": [str(x) for x in data_sources if str(x).strip()][:8],
                "evidence_quality": output.get("evidence_quality") if isinstance(output.get("evidence_quality"), dict) else {},
            }
        )
        order += 1

    return summaries


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


def _build_long_synthesis_report(
    *,
    ticker_label: str,
    query: str,
    agent_summaries: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    base_markdown: str,
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

    # 2) Citation references (only when citations exist — real data, not filler).
    if citations:
        parts.append("## 引用来源")
        for c in citations[:12]:
            if not isinstance(c, dict):
                continue
            cid = _safe_str(c.get("source_id") or "")
            title = _safe_str(c.get("title") or c.get("url") or "")[:120]
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

    return "\n".join([p for p in parts if p is not None]).strip() + "\n"


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


def build_report_payload(*, state: dict[str, Any], query: str, thread_id: str) -> dict[str, Any] | None:
    """
    Build a frontend-friendly ReportIR payload (used by ReportView cards) from LangGraph state.
    This is intentionally deterministic: it never requires an LLM call to be useful.
    """
    output_mode = state.get("output_mode")
    if output_mode != "investment_report":
        return None

    subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
    subject_type = subject.get("subject_type") if isinstance(subject, dict) else "unknown"

    tickers = subject.get("tickers") if isinstance(subject, dict) else None
    tickers = tickers if isinstance(tickers, list) else []
    tickers = [str(t).strip().upper() for t in tickers if isinstance(t, str) and t.strip()]
    ticker_label = " vs ".join(tickers[:4]) if len(tickers) > 1 else (tickers[0] if tickers else "N/A")

    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    render_vars = artifacts.get("render_vars") if isinstance(artifacts.get("render_vars"), dict) else {}
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts.get("evidence_pool"), list) else []
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    errors = artifacts.get("errors") if isinstance(artifacts.get("errors"), list) else []
    draft_markdown = _safe_str(artifacts.get("draft_markdown") or "")

    plan_ir = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
    plan_steps = plan_ir.get("steps") if isinstance(plan_ir.get("steps"), list) else []

    policy = state.get("policy") if isinstance(state.get("policy"), dict) else {}
    allowed_agents = policy.get("allowed_agents") if isinstance(policy.get("allowed_agents"), list) else []
    allowed_agents = [str(a) for a in allowed_agents if isinstance(a, str) and a.strip()]

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

    # Section list: show each agent summary as its own section for rendering.
    # Build agent_name → evidence URLs mapping for citation bridging.
    steps_by_agent: dict[str, str] = {}
    for step in plan_steps:
        if not isinstance(step, dict):
            continue
        if step.get("kind") == "agent" and isinstance(step.get("name"), str) and isinstance(step.get("id"), str):
            steps_by_agent[step["name"].strip()] = step["id"].strip()

    def _get_agent_citation_refs(agent_name: str) -> list[str]:
        """Match agent evidence URLs against citation id_by_url."""
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
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            url = ev.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            source_id = citation_build.id_by_url.get(url.strip())
            if source_id and source_id not in refs:
                refs.append(source_id)
        return refs

    sections: list[dict[str, Any]] = []
    section_order = 1
    for item in agent_summaries:
        title = _safe_str(item.get("title") or "")
        if not title:
            continue
        agent_name = item.get("agent_name") or ""
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
                        "content": _safe_str(item.get("summary") or ""),
                        "citation_refs": refs,
                        "metadata": {},
                    }
                ],
            }
        )
        section_order += 1

    if filing_section_citations:
        lines = []
        for item in filing_section_citations[:24]:
            section = _safe_str(item.get("section") or "").strip()
            source_ids = item.get("source_ids") if isinstance(item.get("source_ids"), list) else []
            source_ids = [f"[{_safe_str(x).strip()}]" for x in source_ids if _safe_str(x).strip()]
            if not section:
                continue
            if source_ids:
                lines.append(f"- {section}: {', '.join(source_ids)}")
            else:
                lines.append(f"- {section}")
        sections.append(
            {
                "title": "Section-level Citations",
                "order": section_order,
                "agent_name": "filing_citation_mapper",
                "confidence": 0.9,
                "data_sources": ["evidence_pool"],
                "contents": [{"type": "text", "content": "\n".join(lines) if lines else "- N/A"}],
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
    )

    # Title by subject type
    if subject_type in ("news_item", "news_set"):
        title = f"{ticker_label} 新闻事件研报"
    elif subject_type in ("filing", "research_doc"):
        title = "文档研读报告"
    elif subject_type == "company" and len(tickers) > 1:
        title = f"{ticker_label} 对比研报"
    else:
        title = f"{ticker_label} 分析报告"

    base_report_dict: dict[str, Any] = {
        "report_id": f"lg_{uuid.uuid4().hex[:10]}",
        "ticker": ticker_label,
        "company_name": ticker_label,
        "title": title,
        "summary": summary,
        "sentiment": "neutral",
        "confidence_score": confidence_score,
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
            "graph_trace": state.get("trace") if isinstance(state.get("trace"), dict) else {},
        },
    }

    validated = ReportValidator.validate_and_fix(base_report_dict, as_dict=True)
    # Preserve frontend-only extensions (ReportView reads these at the top level).
    if isinstance(validated, dict):
        validated["synthesis_report"] = synthesis_report
        validated["agent_status"] = agent_status
        validated["report_hints"] = report_hints
        if report_tags:
            validated["tags"] = report_tags

        meta = validated.get("meta") if isinstance(validated.get("meta"), dict) else {}
        meta["report_hints"] = report_hints
        validated["meta"] = meta
        return validated
    return None
