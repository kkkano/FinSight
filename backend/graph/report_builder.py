# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from backend.report.validator import ReportValidator


logger = logging.getLogger(__name__)


_AGENT_TITLE_MAP: dict[str, str] = {
    "price_agent": "价格分析",
    "news_agent": "新闻分析",
    "technical_agent": "技术分析",
    "fundamental_agent": "基本面分析",
    "macro_agent": "宏观分析",
    "deep_search_agent": "深度搜索",
}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


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


def _is_suspicious_citation_item(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return True
    url = _safe_str(item.get("url") or "").strip().lower()
    title = _safe_str(item.get("title") or "").strip().lower()
    snippet = _safe_str(item.get("snippet") or "").strip().lower()
    if not url.startswith(("http://", "https://")):
        return True
    parsed = urlparse(url)
    domain = (parsed.netloc or "").lower().lstrip("www.")
    path = (parsed.path or "").lower()

    if domain == "finnhub.io" and path.startswith("/api/news"):
        return True

    blocked_domains = (
        "tangxin93.com",
        "hinrijv.cc",
        "xqdyzgc.com",
        "yumiok.com",
        "playfulsoul.net",
        "mtevfryb.cc",
        "ewfvsve.cc",
        "maoyanqing.com",
    )
    blocked_tlds = (".cc", ".xyz", ".top", ".vip", ".club", ".porn", ".sex")
    blocked_terms = (
        "成人视频",
        "乱伦",
        "群p",
        "porn",
        "xxx",
        "casino",
        "betting",
    )
    text = " ".join((url, title, snippet))
    if any(domain in url for domain in blocked_domains):
        return True
    if domain and any(domain.endswith(suffix) for suffix in blocked_tlds):
        return True
    if "/tag/" in path and any(token in path for token in ("群", "porn", "xxx", "sex")):
        return True
    if any(term in text for term in blocked_terms):
        return True
    return False


def _build_citations(evidence_pool: list[dict[str, Any]] | None) -> _CitationBuild:
    citations: list[dict[str, Any]] = []
    id_by_url: dict[str, str] = {}
    if not isinstance(evidence_pool, list):
        return _CitationBuild(citations=citations, id_by_url=id_by_url)

    for item in evidence_pool:
        if not isinstance(item, dict):
            continue
        if _is_suspicious_citation_item(item):
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
    q = _safe_str(query).strip().lower()
    if not q:
        return False
    keywords = (
        "deep report",
        "longform",
        "filing",
        "10-k",
        "10-q",
        "earnings call",
        "transcript",
        "深度",
        "研报",
        "财报",
        "电话会",
    )
    return any(token in q for token in keywords)


def _build_report_quality_hints(
    *,
    query: str,
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    authoritative_media_domains = (
        "reuters.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",
        "cnbc.com",
        "finance.yahoo.com",
    )
    deep_required = _is_deep_report_query(query)

    has_10k = False
    has_10q = False
    has_earnings_transcript = False
    authoritative_media_count = 0
    sec_filing_count = 0
    rich_snippet_count = 0

    for item in citations:
        if not isinstance(item, dict):
            continue
        url = _safe_str(item.get("url") or "").strip().lower()
        title = _safe_str(item.get("title") or "").strip().lower()
        snippet = _safe_str(item.get("snippet") or "").strip()
        parsed = urlparse(url)
        domain = (parsed.netloc or "").lower().lstrip("www.")
        joined = f"{url} {title} {snippet.lower()}"

        if domain.endswith("sec.gov") or "sec.gov/" in url:
            sec_filing_count += 1
            if re.search(r"\b10-k\b|annual report|form\s*10k", joined, flags=re.I):
                has_10k = True
            if re.search(r"\b10-q\b|quarterly report|form\s*10q", joined, flags=re.I):
                has_10q = True

        if re.search(r"earnings|conference call|transcript|电话会|业绩会", joined, flags=re.I):
            has_earnings_transcript = True

        if any(domain.endswith(d) for d in authoritative_media_domains):
            authoritative_media_count += 1

        normalized_snippet = snippet.strip().lower()
        if (
            len(snippet) >= 40
            and normalized_snippet
            and normalized_snippet != url
            and not normalized_snippet.startswith("http://")
            and not normalized_snippet.startswith("https://")
        ):
            rich_snippet_count += 1

    missing: list[str] = []
    if deep_required:
        if not has_10k:
            missing.append("缺少可识别 10-K 引用")
        if not has_10q:
            missing.append("缺少可识别 10-Q 引用")
        if not has_earnings_transcript:
            missing.append("缺少业绩电话会/业绩会纪要引用")
        if authoritative_media_count <= 0:
            missing.append("缺少权威媒体交叉引用（Reuters/Bloomberg/WSJ/FT/CNBC/Yahoo）")
        if rich_snippet_count < 2:
            missing.append("证据摘录质量不足（大多仅URL，缺少正文摘录）")

    return {
        "deep_report_required": deep_required,
        "qualified": not missing,
        "missing_requirements": missing,
        "stats": {
            "citation_count": len(citations),
            "sec_filing_count": sec_filing_count,
            "authoritative_media_count": authoritative_media_count,
            "rich_snippet_count": rich_snippet_count,
            "has_10k": has_10k,
            "has_10q": has_10q,
            "has_earnings_transcript": has_earnings_transcript,
        },
    }


def build_report_payload(*, state: dict[str, Any], query: str, thread_id: str) -> dict[str, Any] | None:
    """
    Build a frontend-friendly ReportIR payload (used by ReportView cards) from LangGraph state.
    This is intentionally deterministic: it never requires an LLM call to be useful.
    """
    output_mode = state.get("output_mode")
    if output_mode != "investment_report":
        return None

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
    quality_hints = _build_report_quality_hints(query=query, citations=citations)
    report_hints["quality"] = quality_hints

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
    if (
        isinstance(quality_missing, list)
        and quality_missing
        and quality_hints.get("deep_report_required") is True
    ):
        gap = "；".join([_safe_str(x).strip() for x in quality_missing if _safe_str(x).strip()][:6])
        quality_warning = f"深度报告质量门槛未满足：{gap}"
        if quality_warning not in risks:
            risks.insert(0, quality_warning)
        confidence_score = min(confidence_score, 0.62)
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
        validated["meta"] = meta
        return _harden_report_payload(validated)
    return None
