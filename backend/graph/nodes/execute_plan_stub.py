# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.graph.adapters import (
    build_agent_invokers as _build_agent_invokers,
    build_tool_invokers as _build_tool_invokers,
)
from backend.graph.executor import execute_plan
from backend.graph.failure import FAILURE_STRATEGY_VERSION
from backend.graph.json_utils import json_dumps_safe
from backend.graph.state import GraphState


def build_tool_invokers(allowed_tools: list[str]) -> dict[str, Any]:
    return _build_tool_invokers(allowed_tools=allowed_tools or [])


def build_agent_invokers(allowed_agents: list[str], state: GraphState) -> dict[str, Any]:
    # Backward-compatible wrapper for tests that monkeypatch this symbol.
    return _build_agent_invokers(allowed_agents=allowed_agents or [], state=state)


def _env_int(name: str, default: int, *, min_value: int = 0, max_value: int = 10_000) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(str(raw).strip())
    except Exception:
        return default
    return max(min_value, min(max_value, parsed))


def _ttl_hours_for_evidence(*, subject_type: str, evidence_type: str, source: str, confidence: float = 0.0, source_reliability: float = 0.0) -> int:
    """
    RAG v2 TTL policy:
    - filing/research_doc: persistent (no TTL)
    - DeepSearch high-quality (confidence >= 0.7 AND source_reliability >= 0.75): persistent
    - news/selection/search-derived: short-term TTL
    - others: session-ephemeral TTL
    """
    if subject_type in ("filing", "research_doc"):
        return 0

    # E4: DeepSearch high-quality results 鈫?persistent
    if confidence >= 0.7 and source_reliability >= 0.75:
        return 0

    news_ttl = _env_int("RAG_V2_NEWS_TTL_HOURS", 24 * 7, min_value=1, max_value=24 * 180)
    ephemeral_ttl = _env_int("RAG_V2_EPHEMERAL_TTL_HOURS", 12, min_value=1, max_value=24 * 30)

    source_norm = (source or "").strip().lower()
    evidence_type_norm = (evidence_type or "").strip().lower()
    if evidence_type_norm in ("news", "selection"):
        return news_ttl
    if source_norm in ("news", "selection", "search", "tavily", "exa", "google_news"):
        return news_ttl
    return ephemeral_ttl


# E4: High-reliability source domains (strict whitelist from deep_search_agent)
_HIGH_RELIABILITY_SOURCE_HINTS = frozenset({
    "sec.gov", "reuters.com", "bloomberg.com", "wsj.com", "ft.com",
})


def _estimate_source_reliability(url: str) -> float:
    """Estimate source reliability from URL domain (0.0 - 1.0)."""
    if not url:
        return 0.5
    url_lower = url.lower()
    # Check high-reliability domains
    for domain in _HIGH_RELIABILITY_SOURCE_HINTS:
        if domain in url_lower:
            return 0.9
    # Investor relations pages
    if "investor" in url_lower:
        return 0.85
    # Known finance sources
    finance_hints = ("yahoo.com/finance", "cnbc.com", "marketwatch.com", "seekingalpha.com")
    for hint in finance_hints:
        if hint in url_lower:
            return 0.75
    return 0.6


def _build_rag_doc_id(*, thread_id: str, evidence: dict[str, Any], index: int) -> str:
    explicit = str(evidence.get("id") or "").strip()
    if explicit:
        return explicit
    title = str(evidence.get("title") or "").strip()
    url = str(evidence.get("url") or "").strip()
    snippet = str(evidence.get("snippet") or "").strip()
    material = f"{thread_id}|{index}|{title}|{url}|{snippet}".encode("utf-8")
    return hashlib.sha1(material).hexdigest()[:24]


def _sanitize_collection_segment(value: str) -> str:
    import re

    text = (value or "").strip()
    if not text:
        return "unknown"
    normalized = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "unknown"


def _collection_from_thread_id(thread_id: str) -> str:
    raw = str(thread_id or "").strip()
    parts = raw.split(":")
    if len(parts) == 3:
        tenant, user, thread = (_sanitize_collection_segment(p) for p in parts)
        return f"session:{tenant}:{user}:{thread}"
    return f"session:{_sanitize_collection_segment(raw)}"



logger = logging.getLogger(__name__)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _stable_id(prefix: str, *parts: Any, length: int = 24) -> str:
    material = "|".join(str(part or "") for part in parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha1(material).hexdigest()[:length]}"


def _resolve_session_id(state: GraphState) -> str:
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    for candidate in (
        state.get("session_id"),
        ui_context.get("session_id"),
        state.get("thread_id"),
    ):
        value = str(candidate or "").strip()
        if value:
            return value
    return "unknown"


def _resolve_rag_user_id(state: GraphState, *, session_id: str) -> str:
    candidate = session_id or str(state.get("thread_id") or "").strip()
    try:
        from backend.graph.store import resolve_user_id

        value = str(resolve_user_id(candidate) or "").strip()
        if value:
            return value
    except Exception:
        pass

    parts = candidate.split(":")
    if len(parts) >= 2 and str(parts[1]).strip():
        return str(parts[1]).strip()
    return "anonymous"


def _build_rag_run_id(*, state: GraphState, session_id: str, query_text: str, started_at: datetime) -> str:
    direct = str(state.get("run_id") or "").strip()
    if direct:
        return direct
    trace = state.get("trace") if isinstance(state.get("trace"), dict) else {}
    runtime = trace.get("runtime") if isinstance(trace.get("runtime"), dict) else {}
    for candidate in (trace.get("run_id"), runtime.get("run_id")):
        value = str(candidate or "").strip()
        if value:
            return value
    return _stable_id("ragrun", session_id, query_text, started_at.isoformat())


def _build_source_doc_obs_id(*, run_id: str, source_id: str, title: str, url: str, index: int) -> str:
    return _stable_id("srcdoc", run_id, source_id, title, url, index)


def _build_chunk_record_id(*, run_id: str, source_doc_id: str, chunk_index: int, chunk_text: str) -> str:
    return _stable_id("chunk", run_id, source_doc_id, chunk_index, chunk_text)


def _build_vector_source_id(*, collection: str, source_id: str, chunk_index: int, chunk_text: str) -> str:
    return _stable_id("vec", collection, source_id, chunk_index, chunk_text)


def _infer_chunk_doc_type(*, evidence_type: str, source: str, title: str, subject_type: str) -> str:
    evidence_norm = str(evidence_type or "").strip().lower()
    source_norm = str(source or "").strip().lower()
    title_norm = str(title or "").strip().lower()
    subject_norm = str(subject_type or "").strip().lower()

    if any(token in title_norm for token in ("transcript", "earnings call", "conference call")):
        return "transcript"
    if evidence_norm in {"filing", "sec", "10-k", "10-q", "8-k"} or source_norm in {"sec_edgar", "sec"}:
        return "filing"
    if evidence_norm in {"news", "selection"}:
        return "news"
    if subject_norm == "research_doc" or "research" in evidence_norm or "research" in source_norm:
        return "research"
    return "web_page"


def _chunk_profile(doc_type: str) -> dict[str, int]:
    profiles = {
        "filing": {"max_chunk_size": 1000, "overlap": 200},
        "transcript": {"max_chunk_size": 800, "overlap": 100},
        "news": {"max_chunk_size": 2000, "overlap": 0},
        "research": {"max_chunk_size": 1200, "overlap": 200},
        "web_page": {"max_chunk_size": 1200, "overlap": 200},
        "table": {"max_chunk_size": 8000, "overlap": 0},
    }
    return profiles.get(doc_type, profiles["web_page"])


def _infer_chunk_strategy(*, doc_type: str, chunk_count: int, content: str) -> str:
    if doc_type == "table":
        return "preserve_table"
    if chunk_count <= 1 and doc_type in {"news", "web_page"} and len(content) <= 2000:
        return "preserve_short_doc"
    if doc_type == "filing":
        return "recursive_filing"
    if doc_type == "transcript":
        return "qa_recursive"
    if doc_type == "research":
        return "recursive_research"
    return "recursive_generic"


def _build_source_doc_content(evidence: dict[str, Any]) -> str:
    pieces: list[str] = []
    seen: set[str] = set()

    for raw_value in (
        evidence.get("title"),
        evidence.get("content"),
        evidence.get("body"),
        evidence.get("text"),
        evidence.get("transcript"),
        evidence.get("snippet"),
        evidence.get("summary"),
        evidence.get("description"),
    ):
        value = str(raw_value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        pieces.append(value)
    return "\n\n".join(pieces).strip()


def _safe_event_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        try:
            return json.loads(json_dumps_safe(payload, ensure_ascii=False))
        except Exception:
            return {"raw": str(payload)}
    if isinstance(payload, list):
        try:
            return {"items": json.loads(json_dumps_safe(payload, ensure_ascii=False))}
        except Exception:
            return {"items": [str(item) for item in payload[:20]]}
    return {"value": str(payload)}


def _decorate_rag_hit(hit: dict[str, Any]) -> dict[str, Any]:
    result = dict(hit or {})
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    for key in (
        "run_id",
        "source_doc_id",
        "chunk_id",
        "doc_type",
        "chunk_index",
        "total_chunks",
        "chunk_strategy",
        "chunk_size",
        "chunk_overlap",
    ):
        if key in metadata and key not in result:
            result[key] = metadata.get(key)
    if metadata.get("source_id") and "evidence_source_id" not in result:
        result["evidence_source_id"] = metadata.get("source_id")
    if result.get("source_id") and "vector_source_id" not in result:
        result["vector_source_id"] = result.get("source_id")
    return result


async def execute_plan_stub(state: GraphState) -> dict:
    """
    Phase 3 executor scaffold:
    - Runs the step scheduler (parallel_group + cache + optional failures)
    - Default: dry-run (no live tool calls) to keep behavior deterministic
    """
    trace = state.get("trace") or {}

    plan_ir = state.get("plan_ir") or {}

    live_tools = os.getenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false").lower() in ("true", "1", "yes", "on")

    tool_invokers = None
    agent_invokers = None
    if live_tools:
        policy = state.get("policy") or {}
        allowed_tools = policy.get("allowed_tools") if isinstance(policy, dict) else []
        allowed_agents = policy.get("allowed_agents") if isinstance(policy, dict) else []
        tool_invokers = build_tool_invokers(list(allowed_tools or []))
        agent_invokers = build_agent_invokers(list(allowed_agents or []), state)

    artifacts, exec_events = await execute_plan(
        plan_ir,
        tool_invokers=tool_invokers,
        agent_invokers=agent_invokers,
        dry_run=not live_tools,
    )

    # Phase 4: build a unified evidence_pool from selection (ephemeral, request-scoped).
    subject = state.get("subject") or {}
    selection_payload = subject.get("selection_payload") if isinstance(subject, dict) else None
    evidence_pool: list[dict[str, Any]] = []
    if isinstance(selection_payload, list) and selection_payload:
        for item in selection_payload:
            if not isinstance(item, dict):
                continue
            evidence_pool.append(
                {
                    "title": item.get("title") or item.get("headline") or "",
                    "url": item.get("url"),
                    "snippet": item.get("snippet") or item.get("summary"),
                    "source": item.get("source") or "selection",
                    "published_date": item.get("ts") or item.get("datetime") or item.get("published_at"),
                    "confidence": item.get("confidence", 0.7),
                    "type": item.get("type") or "selection",
                    "id": item.get("id"),
                }
            )

    # Phase 4.2+: merge tool outputs into evidence_pool (best-effort normalization).
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else None
    steps = plan_ir.get("steps") if isinstance(plan_ir, dict) else None
    step_index = {s.get("id"): s for s in (steps or []) if isinstance(s, dict) and s.get("id")}

    def _append_tool_evidence(tool_name: str, step_id: str, output: Any) -> None:
        if output is None:
            return
        if isinstance(output, dict) and output.get("skipped"):
            return

        # Some tools return JSON text (e.g. get_company_news). Try to parse.
        if isinstance(output, str):
            try:
                parsed = json.loads(output)
                output = parsed
            except Exception:
                pass

        # Special-case: make technical snapshot readable in evidence list.
        if tool_name == "get_technical_snapshot" and isinstance(output, dict):
            if output.get("error"):
                evidence_pool.append(
                    {
                        "title": f"Technical snapshot ({output.get('ticker','N/A')})",
                        "url": None,
                        "snippet": f"error={output.get('error')} points={output.get('points','N/A')}",
                        "source": tool_name,
                        "published_date": output.get("as_of"),
                        "confidence": 0.7,
                        "type": "tool",
                        "id": output.get("id") or f"{tool_name}:{step_id}",
                    }
                )
                return

            parts = []
            if output.get("close") is not None:
                parts.append(f"close={output.get('close')}")
            if output.get("ma20") is not None:
                parts.append(f"MA20={output.get('ma20')}")
            if output.get("ma50") is not None:
                parts.append(f"MA50={output.get('ma50')}")
            if output.get("rsi14") is not None:
                parts.append(f"RSI14={output.get('rsi14')}({output.get('rsi_state')})")
            if output.get("macd") is not None and output.get("macd_signal") is not None:
                parts.append(f"MACD={output.get('macd')} vs {output.get('macd_signal')}({output.get('momentum')})")
            if output.get("trend"):
                parts.append(f"trend={output.get('trend')}")

            evidence_pool.append(
                {
                    "title": f"Technical snapshot ({output.get('ticker','N/A')})",
                    "url": None,
                    "snippet": " | ".join(parts) if parts else None,
                    "source": output.get("source") or tool_name,
                    "published_date": output.get("as_of"),
                    "confidence": 0.75,
                    "type": "tool",
                    "id": output.get("id") or f"{tool_name}:{step_id}",
                }
            )
            return

        if tool_name in ("get_sec_filings", "get_sec_material_events", "get_sec_risk_factors") and isinstance(output, dict):
            filings = output.get("filings") or output.get("events") or []
            company_name = output.get("company_name") or output.get("ticker") or ""
            for i, filing in enumerate(filings[:10]):
                if not isinstance(filing, dict):
                    continue
                form_type = str(filing.get("form") or "SEC").strip() or "SEC"
                filing_url = str(filing.get("filing_url") or "").strip()
                filing_date = str(filing.get("filing_date") or "").strip() or None
                description = str(filing.get("primary_doc_description") or form_type).strip()
                evidence_pool.append(
                    {
                        "title": f"{company_name} {form_type} ({filing_date or 'N/A'})".strip(),
                        "url": filing_url or None,
                        "snippet": f"SEC EDGAR {form_type} filing. Filed: {filing_date or 'N/A'}. {description}",
                        "source": "sec_edgar",
                        "published_date": filing_date,
                        "confidence": 0.85,
                        "type": "filing",
                        "id": f"{tool_name}:{step_id}:{i+1}",
                    }
                )

            risk_excerpt = str(output.get("risk_factors_excerpt") or "").strip()
            if risk_excerpt:
                selected = output.get("selected_filing") if isinstance(output.get("selected_filing"), dict) else {}
                evidence_pool.append(
                    {
                        "title": f"{company_name} Risk Factors (Item 1A)".strip(),
                        "url": str(selected.get("filing_url") or "").strip() or None,
                        "snippet": risk_excerpt[:800],
                        "source": "sec_edgar",
                        "published_date": selected.get("filing_date"),
                        "confidence": 0.9,
                        "type": "filing",
                        "id": f"{tool_name}:{step_id}:risk",
                    }
                )
            return

        if tool_name == "get_local_market_filings" and isinstance(output, dict):
            filings = output.get("filings") or []
            ticker = str(output.get("ticker") or "").strip()
            market = str(output.get("market") or "").strip().upper()
            for i, filing in enumerate(filings[:10]):
                if not isinstance(filing, dict):
                    continue
                form_type = str(filing.get("form") or "filing").strip() or "filing"
                filing_url = str(filing.get("filing_url") or filing.get("url") or "").strip()
                filing_date = str(filing.get("filing_date") or filing.get("published_date") or "").strip() or None
                title = str(filing.get("title") or "").strip()
                description = str(
                    filing.get("primary_doc_description") or filing.get("snippet") or title or form_type
                ).strip()
                evidence_pool.append(
                    {
                        "title": title or f"{ticker} {form_type} ({filing_date or 'N/A'})".strip(),
                        "url": filing_url or None,
                        "snippet": f"{market} local disclosure {form_type}. Filed: {filing_date or 'N/A'}. {description}",
                        "source": filing.get("source") or "local_disclosure",
                        "published_date": filing_date,
                        "confidence": filing.get("confidence", 0.8),
                        "type": "filing",
                        "id": f"{tool_name}:{step_id}:{i+1}",
                    }
                )
            return

        if tool_name == "get_authoritative_media_news" and isinstance(output, dict):
            articles = output.get("articles") or []
            for i, article in enumerate(articles[:10]):
                if not isinstance(article, dict):
                    continue
                title = str(article.get("title") or "").strip()
                url = str(article.get("url") or "").strip()
                snippet = str(article.get("snippet") or title).strip()
                if not title and not url:
                    continue
                evidence_pool.append(
                    {
                        "title": title or f"authoritative media {i+1}",
                        "url": url or None,
                        "snippet": snippet[:800],
                        "source": article.get("source") or "authoritative_feed",
                        "published_date": article.get("published_date"),
                        "confidence": article.get("confidence", 0.78),
                        "type": "news",
                        "id": article.get("id") or f"{tool_name}:{step_id}:{i+1}",
                    }
                )
            return

        if tool_name == "get_earnings_call_transcripts" and isinstance(output, dict):
            transcripts = output.get("transcripts") or output.get("articles") or []
            for i, item in enumerate(transcripts[:10]):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                url = str(item.get("url") or "").strip()
                snippet = str(item.get("snippet") or title).strip()
                if not title and not url:
                    continue
                evidence_pool.append(
                    {
                        "title": title or f"earnings transcript {i+1}",
                        "url": url or None,
                        "snippet": snippet[:800],
                        "source": item.get("source") or "earnings_transcript",
                        "published_date": item.get("published_date"),
                        "confidence": item.get("confidence", 0.8),
                        "type": "transcript",
                        "id": item.get("id") or f"{tool_name}:{step_id}:{i+1}",
                    }
                )
            return

        if isinstance(output, list):
            for i, item in enumerate(output[:10]):
                if not isinstance(item, dict):
                    continue
                evidence_pool.append(
                    {
                        "title": item.get("title") or item.get("headline") or f"{tool_name} result {i+1}",
                        "url": item.get("url"),
                        "snippet": item.get("snippet") or item.get("summary") or item.get("content"),
                        "source": item.get("source") or tool_name,
                        "published_date": item.get("published_date") or item.get("published_at") or item.get("datetime"),
                        "confidence": item.get("confidence", 0.6),
                        "type": item.get("type") or "tool",
                        "id": item.get("id") or f"{tool_name}:{step_id}:{i+1}",
                    }
                )
            return

        snippet = json_dumps_safe(output, ensure_ascii=False) if isinstance(output, dict) else str(output)
        evidence_pool.append(
            {
                "title": f"{tool_name} output",
                "url": None,
                "snippet": snippet[:800],
                "source": tool_name,
                "published_date": None,
                "confidence": 0.6,
                "type": "tool",
                "id": f"{tool_name}:{step_id}",
                }
            )

    jina_enrich_enabled = str(os.getenv("JINA_ENRICH_EVIDENCE", "true")).strip().lower() in {"1", "true", "yes", "on"}

    def _maybe_enrich_snippet_from_jina(url: str | None, snippet: Any) -> Any:
        if not jina_enrich_enabled:
            return snippet
        target = str(url or "").strip()
        snippet_text = str(snippet or "").strip()
        if not target.startswith(("http://", "https://")):
            return snippet
        if len(snippet_text) >= 80:
            return snippet
        if "news.google.com" in target:
            return snippet
        try:
            from backend.tools.jina_reader import fetch_via_jina
        except Exception:
            return snippet
        try:
            jina_text = fetch_via_jina(target)
            if jina_text and len(jina_text) > len(snippet_text):
                return jina_text[:800]
        except Exception:
            return snippet
        return snippet

    def _append_agent_evidence(agent_name: str, step_id: str, output: Any) -> None:
        if output is None:
            return
        if isinstance(output, dict) and output.get("skipped"):
            return

        if isinstance(output, str):
            try:
                output = json.loads(output)
            except Exception:
                output = {"summary": output}

        if not isinstance(output, dict):
            evidence_pool.append(
                {
                    "title": f"{agent_name} output",
                    "url": None,
                    "snippet": str(output)[:800],
                    "source": agent_name,
                    "published_date": None,
                    "confidence": 0.5,
                    "type": "agent",
                    "id": f"{agent_name}:{step_id}",
                }
            )
            return

        summary = output.get("summary")
        confidence_base = output.get("confidence", 0.6)
        as_of = output.get("as_of")

        if isinstance(summary, str) and summary.strip():
            evidence_pool.append(
                {
                    "title": f"{agent_name} summary",
                    "url": None,
                    "snippet": summary.strip()[:800],
                    "source": agent_name,
                    "published_date": as_of,
                    "confidence": confidence_base if isinstance(confidence_base, (int, float)) else 0.6,
                    "type": "agent",
                    "id": f"{agent_name}:{step_id}:summary",
                }
            )

        evidence = output.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            return

        for i, item in enumerate(evidence[:10]):
            if isinstance(item, str):
                item = {"text": item}
            if not isinstance(item, dict):
                continue
            snippet = item.get("text") or item.get("snippet") or item.get("summary")
            if not snippet:
                continue
            url = item.get("url")
            snippet = _maybe_enrich_snippet_from_jina(url, snippet)
            source = item.get("source") or agent_name
            evidence_pool.append(
                {
                    "title": item.get("title") or f"{agent_name} evidence {i+1}",
                    "url": url,
                    "snippet": str(snippet).strip()[:800],
                    "source": source,
                    "published_date": item.get("timestamp") or as_of,
                    "confidence": item.get("confidence", confidence_base if isinstance(confidence_base, (int, float)) else 0.6),
                    "type": "agent",
                    "id": item.get("id") or f"{agent_name}:{step_id}:{i+1}",
                }
            )

    if isinstance(step_results, dict) and step_results:
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            step = step_index.get(step_id) or {}
            if step.get("kind") != "tool":
                if step.get("kind") == "agent":
                    agent_name = step.get("name") or ""
                    if agent_name:
                        _append_agent_evidence(str(agent_name), str(step_id), item.get("output"))
                continue
            tool_name = step.get("name") or ""
            if not tool_name:
                continue
            _append_tool_evidence(str(tool_name), str(step_id), item.get("output"))

    # Dedupe by url or title+source
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for e in evidence_pool:
        if not isinstance(e, dict):
            continue
        key = e.get("url") or f"{e.get('title')}|{e.get('source')}"
        if not key or key in seen:
            continue
        seen.add(str(key))
        deduped.append(e)
    artifacts["evidence_pool"] = deduped

    # Phase P0-3c: collect per-agent fallback diagnostics into artifacts
    # so synthesize/render can surface degradation info to the user.
    agent_diagnostics: dict[str, dict[str, Any]] = {}
    if isinstance(step_results, dict):
        for step_id, item in step_results.items():
            if not isinstance(item, dict):
                continue
            step = step_index.get(step_id) or {}
            if step.get("kind") != "agent":
                continue
            agent_name = step.get("name") or step_id
            output = item.get("output")
            if not isinstance(output, dict):
                continue
            diag: dict[str, Any] = {
                "status": output.get("status", "unknown"),
                "duration_ms": output.get("duration_ms"),
            }
            fallback_reason = output.get("fallback_reason")
            if fallback_reason:
                diag["fallback_reason"] = fallback_reason
                diag["retryable"] = output.get("retryable", False)
                diag["error_stage"] = output.get("error_stage", "unknown")
            agent_diagnostics[str(agent_name)] = diag
    if agent_diagnostics:
        artifacts["agent_diagnostics"] = agent_diagnostics

    # Phase 11.11.2: RAG v2 pipeline with routing
    rag_trace: dict[str, Any] = {"enabled": False}
    rag_run_id: str | None = None
    rag_started_at: datetime | None = None
    rag_obs_store: Any = None
    rag_event_records: list[Any] = []
    rag_fallback_records: list[Any] = []
    rag_final_update: dict[str, Any] | None = None

    def _store_call(*_args: Any, **_kwargs: Any) -> Any:
        return None

    try:
        from backend.rag.chunker import chunk_document
        from backend.rag.hybrid_service import RAGDocument, get_rag_service
        from backend.rag.observability_models import (
            ChunkRecord,
            FallbackEventRecord,
            QueryEventRecord,
            QueryRunRecord,
            RerankHitRecord,
            RetrievalHitRecord,
            SourceDocRecord,
        )
        from backend.rag.observability_runtime import get_rag_observability_store
        from backend.rag.rag_router import RAGPriority, decide_rag_priority

        query_text = str(state.get("query") or "").strip()
        thread_id = str(state.get("thread_id") or "").strip() or "unknown"
        session_id = _resolve_session_id(state)
        user_id = _resolve_rag_user_id(state, session_id=session_id)
        output_mode = str(state.get("output_mode") or "").strip()
        operation_name = str((state.get("operation") or {}).get("name", "")).strip() if isinstance(state.get("operation"), dict) else ""
        backend_requested = str(os.getenv("RAG_V2_BACKEND", "auto") or "auto").strip().lower() or "auto"
        query_hash = hashlib.sha256(query_text.encode("utf-8")).hexdigest() if query_text else ""

        rag_priority = decide_rag_priority(
            query=query_text,
            output_mode=output_mode,
            operation=operation_name,
            subject_type=str((subject or {}).get("subject_type") or ""),
        )

        if query_text and deduped:
            rag_started_at = datetime.now(timezone.utc)
            rag_run_id = _build_rag_run_id(
                state=state,
                session_id=session_id,
                query_text=query_text,
                started_at=rag_started_at,
            )
            rag_obs_store = get_rag_observability_store()

            def _store_call(method_name: str, *args: Any, **kwargs: Any) -> Any:
                if rag_obs_store is None:
                    return None
                method = getattr(rag_obs_store, method_name, None)
                if not callable(method):
                    return None
                try:
                    return method(*args, **kwargs)
                except Exception as exc:
                    logger.warning("RAG 鍙娴嬪啓鍏ュけ璐?method=%s error=%s", method_name, exc)
                    return None

            _store_call("ensure_schema")

            def _append_rag_event(event_type: str, stage: str, payload: dict[str, Any] | list[Any] | str) -> None:
                if not rag_run_id:
                    return
                seq_no = len(rag_event_records) + 1
                rag_event_records.append(
                    QueryEventRecord(
                        id=_stable_id("qevent", rag_run_id, seq_no, event_type, stage),
                        run_id=rag_run_id,
                        seq_no=seq_no,
                        event_type=event_type,
                        stage=stage,
                        payload_json=_safe_event_payload(payload),
                    )
                )

            _store_call(
                "start_query_run",
                QueryRunRecord(
                    id=rag_run_id,
                    user_id=user_id,
                    session_id=session_id,
                    thread_id=thread_id,
                    query_text=query_text,
                    query_hash=query_hash,
                    route_name="execute_plan_stub",
                    router_decision=rag_priority.value,
                    backend_requested=backend_requested,
                    backend_actual="memory",
                    status="running",
                    started_at=rag_started_at,
                ),
            )
            _append_rag_event(
                "query_received",
                "query",
                {
                    "query_hash": query_hash,
                    "thread_id": thread_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "deduped_candidate_count": len(deduped),
                },
            )
            if step_index:
                _append_rag_event(
                    "plan_steps_selected",
                    "planner",
                    {
                        "steps": [
                            {
                                "id": step.get("id"),
                                "kind": step.get("kind"),
                                "name": step.get("name"),
                                "inputs": step.get("inputs"),
                            }
                            for step in list(step_index.values())[:20]
                            if isinstance(step, dict)
                        ]
                    },
                )
            _append_rag_event(
                "router_decided",
                "routing",
                {
                    "router_decision": rag_priority.value,
                    "backend_requested": backend_requested,
                },
            )

        if rag_priority == RAGPriority.SKIP:
            rag_trace = {
                "enabled": False,
                "reason": "router_skip",
                "router_decision": rag_priority.value,
                "run_id": rag_run_id,
            }
            if rag_run_id and rag_started_at is not None:
                finished_at = datetime.now(timezone.utc)
                rag_final_update = {
                    "router_decision": rag_priority.value,
                    "backend_requested": backend_requested,
                    "backend_actual": "memory",
                    "fallback_reason": "router_skip",
                    "status": "partial",
                    "finished_at": finished_at,
                    "latency_ms": (finished_at - rag_started_at).total_seconds() * 1000.0,
                }
        elif query_text and deduped:
            rag = get_rag_service()
            subject_type = str((subject or {}).get("subject_type") or "unknown")
            collection = _collection_from_thread_id(thread_id)
            now = datetime.now(timezone.utc)
            rag_docs: list[RAGDocument] = []
            source_doc_records: list[Any] = []
            chunk_records: list[Any] = []

            _append_rag_event(
                "evidence_deduped",
                "source_docs",
                {
                    "input_count": len(evidence_pool),
                    "deduped_count": len(deduped),
                    "ingest_limit": min(len(deduped), 80),
                },
            )

            for idx, evidence in enumerate(deduped[:80]):
                title = str(evidence.get("title") or "").strip()
                raw_content = _build_source_doc_content(evidence)
                if not raw_content:
                    continue
                evidence_type = str(evidence.get("type") or "selection").strip()
                source = str(evidence.get("source") or "selection").strip() or "selection"
                evidence_url = str(evidence.get("url") or "").strip()
                evidence_confidence = float(evidence.get("confidence") or 0.0)
                evidence_reliability = _estimate_source_reliability(evidence_url)
                ttl_hours = _ttl_hours_for_evidence(
                    subject_type=subject_type,
                    evidence_type=evidence_type,
                    source=source,
                    confidence=evidence_confidence,
                    source_reliability=evidence_reliability,
                )
                expires_at = None if ttl_hours <= 0 else now + timedelta(hours=ttl_hours)
                scope = "persistent" if ttl_hours <= 0 else "ephemeral"
                source_id = _build_rag_doc_id(thread_id=thread_id, evidence=evidence, index=idx)
                source_doc_id = _build_source_doc_obs_id(
                    run_id=rag_run_id or "unknown",
                    source_id=source_id,
                    title=title,
                    url=evidence_url,
                    index=idx,
                )
                published_at = _parse_datetime(
                    evidence.get("published_date")
                    or evidence.get("published_at")
                    or evidence.get("datetime")
                    or evidence.get("timestamp")
                )
                doc_type = _infer_chunk_doc_type(
                    evidence_type=evidence_type,
                    source=source,
                    title=title,
                    subject_type=subject_type,
                )
                chunk_profile = _chunk_profile(doc_type)
                chunk_result = chunk_document(raw_content, doc_type, title=title or None)
                chunk_total = len(chunk_result.chunks)
                chunk_strategy = _infer_chunk_strategy(doc_type=doc_type, chunk_count=chunk_total, content=raw_content)

                source_doc_records.append(
                    SourceDocRecord(
                        id=source_doc_id,
                        run_id=rag_run_id or "unknown",
                        collection=collection,
                        source_id=source_id,
                        source_type=evidence_type or "selection",
                        source_name=source,
                        url=evidence_url or None,
                        title=title or None,
                        published_at=published_at,
                        content_raw=raw_content,
                        content_preview=raw_content[:800],
                        content_length=len(raw_content),
                        metadata_json={
                            "collection": collection,
                            "scope": scope,
                            "confidence": evidence.get("confidence"),
                            "published_date": evidence.get("published_date"),
                            "type": evidence_type,
                            "source": source,
                        },
                    )
                )

                for chunk_index, chunk_text in enumerate(chunk_result.chunks):
                    chunk_body = str(chunk_text or "").strip()
                    if not chunk_body:
                        continue
                    chunk_meta = chunk_result.metadata[chunk_index] if chunk_index < len(chunk_result.metadata) else {}
                    chunk_record_id = _build_chunk_record_id(
                        run_id=rag_run_id or "unknown",
                        source_doc_id=source_doc_id,
                        chunk_index=chunk_index,
                        chunk_text=chunk_body,
                    )
                    vector_source_id = _build_vector_source_id(
                        collection=collection,
                        source_id=source_id,
                        chunk_index=chunk_index,
                        chunk_text=chunk_body,
                    )
                    chunk_records.append(
                        ChunkRecord(
                            id=chunk_record_id,
                            run_id=rag_run_id or "unknown",
                            collection=collection,
                            source_id=source_id,
                            source_doc_id=source_doc_id,
                            chunk_index=chunk_index,
                            total_chunks=max(1, int(chunk_meta.get("total_chunks") or chunk_total or 1)),
                            chunk_text=chunk_body,
                            chunk_length=len(chunk_body),
                            doc_type=str(chunk_meta.get("doc_type") or doc_type),
                            chunk_strategy=chunk_strategy,
                            chunk_size=int(chunk_profile.get("max_chunk_size") or len(chunk_body)),
                            chunk_overlap=int(chunk_profile.get("overlap") or 0),
                            metadata_json={
                                "collection": collection,
                                "scope": scope,
                                "source_id": source_id,
                                "source_name": source,
                                "url": evidence_url or None,
                                "title": title or None,
                                "vector_source_id": vector_source_id,
                            },
                        )
                    )
                    rag_docs.append(
                        RAGDocument(
                            collection=collection,
                            scope=scope,
                            source_id=vector_source_id,
                            content=chunk_body,
                            title=title or None,
                            url=evidence_url or None,
                            source=source,
                            metadata={
                                "published_date": evidence.get("published_date"),
                                "confidence": evidence.get("confidence"),
                                "type": evidence_type,
                                "run_id": rag_run_id,
                                "source_id": source_id,
                                "source_doc_id": source_doc_id,
                                "chunk_id": chunk_record_id,
                                "doc_type": str(chunk_meta.get("doc_type") or doc_type),
                                "chunk_index": chunk_index,
                                "total_chunks": max(1, int(chunk_meta.get("total_chunks") or chunk_total or 1)),
                                "chunk_strategy": chunk_strategy,
                                "chunk_size": int(chunk_profile.get("max_chunk_size") or len(chunk_body)),
                                "chunk_overlap": int(chunk_profile.get("overlap") or 0),
                            },
                            expires_at=expires_at,
                        )
                    )

            _store_call("append_source_docs", source_doc_records)
            _store_call("append_chunks", chunk_records)
            _append_rag_event("source_doc_created", "source_docs", {"source_doc_count": len(source_doc_records)})
            _append_rag_event("chunk_created", "chunking", {"chunk_count": len(chunk_records)})

            if getattr(rag, "fallback_reason", None):
                rag_fallback_records.append(
                    FallbackEventRecord(
                        id=_stable_id("fallback", rag_run_id or "global", "backend", rag.fallback_reason),
                        run_id=rag_run_id,
                        reason_code="backend_fallback",
                        reason_text=str(rag.fallback_reason),
                        backend_before=backend_requested,
                        backend_after=str(getattr(rag, "backend_name", "memory") or "memory"),
                        payload_json={"collection": collection},
                    )
                )
                _append_rag_event(
                    "fallback_triggered",
                    "backend",
                    {
                        "reason": str(rag.fallback_reason),
                        "backend_before": backend_requested,
                        "backend_after": str(getattr(rag, "backend_name", "memory") or "memory"),
                    },
                )

            if rag_docs:
                ingest_stats = await asyncio.to_thread(rag.ingest_documents, rag_docs)
                rerank_top_n = _env_int("RAG_V2_RERANK_TOP_N", 8, min_value=1, max_value=20)
                retrieval_k = _env_int("RAG_V2_TOP_K", max(rerank_top_n * 3, 18), min_value=1, max_value=60)
                retrieved_hits = await asyncio.to_thread(
                    rag.hybrid_search,
                    query_text,
                    collection=collection,
                    top_k=retrieval_k,
                )
                pre_rerank_hits = [_decorate_rag_hit(hit) for hit in (retrieved_hits or [])]
                rag_hits = pre_rerank_hits[:rerank_top_n]
                reranker_used = False
                try:
                    rerank_enabled = str(os.getenv("RAG_ENABLE_RERANKER", "false")).strip().lower() in {
                        "1",
                        "true",
                        "yes",
                        "on",
                    }
                    if rerank_enabled:
                        from backend.rag.reranker import get_reranker_service

                        reranker = get_reranker_service()
                        if reranker.is_enabled and pre_rerank_hits:
                            rag_hits = [_decorate_rag_hit(hit) for hit in await asyncio.to_thread(
                                reranker.rerank,
                                query_text,
                                pre_rerank_hits,
                                top_n=rerank_top_n,
                            )]
                            reranker_used = True
                except Exception as rerank_exc:
                    logger.debug("Reranker unavailable, using RRF order: %s", rerank_exc)
                    rag_hits = pre_rerank_hits[:rerank_top_n]

                cleaned = await asyncio.to_thread(rag.cleanup_expired)
                retrieval_records: list[Any] = []
                input_rank_by_chunk_id: dict[str, int] = {}
                for index, hit in enumerate(pre_rerank_hits, start=1):
                    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
                    chunk_id = str(hit.get("chunk_id") or metadata.get("chunk_id") or "").strip() or None
                    if chunk_id:
                        input_rank_by_chunk_id[chunk_id] = index
                    retrieval_records.append(
                        RetrievalHitRecord(
                            id=_stable_id("rhit", rag_run_id or "unknown", index, chunk_id or hit.get("source_id")),
                            run_id=rag_run_id or "unknown",
                            chunk_id=chunk_id,
                            collection=hit.get("collection"),
                            source_id=str(hit.get("evidence_source_id") or metadata.get("source_id") or hit.get("source_id") or "").strip() or None,
                            source_doc_id=str(hit.get("source_doc_id") or metadata.get("source_doc_id") or "").strip() or None,
                            scope=hit.get("scope"),
                            dense_rank=hit.get("dense_rank"),
                            dense_score=float(hit.get("dense_score") or 0.0),
                            sparse_rank=hit.get("sparse_rank"),
                            sparse_score=float(hit.get("sparse_score") or 0.0),
                            rrf_score=float(hit.get("rrf_score") or 0.0),
                            selected_for_rerank=index <= rerank_top_n,
                            metadata_json={
                                "title": hit.get("title"),
                                "url": hit.get("url"),
                                "source": hit.get("source"),
                                "doc_type": hit.get("doc_type") or metadata.get("doc_type"),
                                "chunk_index": hit.get("chunk_index") or metadata.get("chunk_index"),
                                "total_chunks": hit.get("total_chunks") or metadata.get("total_chunks"),
                                "vector_source_id": hit.get("vector_source_id") or hit.get("source_id"),
                            },
                        )
                    )
                _store_call("append_retrieval_hits", retrieval_records)
                _append_rag_event(
                    "retrieval_done",
                    "retrieval",
                    {
                        "retrieval_k": retrieval_k,
                        "hit_count": len(pre_rerank_hits),
                        "top_chunk_ids": [hit.get("chunk_id") for hit in pre_rerank_hits[:10]],
                    },
                )

                rerank_records: list[Any] = []
                for output_rank, hit in enumerate(rag_hits, start=1):
                    metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
                    chunk_id = str(hit.get("chunk_id") or metadata.get("chunk_id") or "").strip() or None
                    rerank_records.append(
                        RerankHitRecord(
                            id=_stable_id("rrhit", rag_run_id or "unknown", output_rank, chunk_id or hit.get("source_id")),
                            run_id=rag_run_id or "unknown",
                            chunk_id=chunk_id,
                            input_rank=int(input_rank_by_chunk_id.get(chunk_id or "") or output_rank),
                            output_rank=output_rank,
                            rerank_score=float(hit.get("rerank_score")) if hit.get("rerank_score") is not None else None,
                            selected_for_answer=True,
                            metadata_json={
                                "title": hit.get("title"),
                                "url": hit.get("url"),
                                "source": hit.get("source"),
                                "doc_type": hit.get("doc_type") or metadata.get("doc_type"),
                            },
                        )
                    )
                _store_call("append_rerank_hits", rerank_records)
                _append_rag_event(
                    "rerank_done",
                    "rerank",
                    {
                        "reranker_used": reranker_used,
                        "input_count": len(pre_rerank_hits),
                        "output_count": len(rag_hits),
                    },
                )

                if not pre_rerank_hits:
                    rag_fallback_records.append(
                        FallbackEventRecord(
                            id=_stable_id("fallback", rag_run_id or "unknown", "empty_retrieval_hits"),
                            run_id=rag_run_id,
                            reason_code="empty_retrieval_hits",
                            reason_text="hybrid_search returned no hits",
                            backend_before=str(getattr(rag, "backend_name", "memory") or "memory"),
                            backend_after=str(getattr(rag, "backend_name", "memory") or "memory"),
                            payload_json={"collection": collection, "query_hash": query_hash},
                        )
                    )

                artifacts["rag_context"] = rag_hits
                artifacts["rag_stats"] = {
                    "backend": rag.backend_name,
                    "embedding_model": getattr(rag, "embedding_model", "unknown"),
                    "reranker_used": reranker_used,
                    "router_decision": rag_priority.value,
                    "collection": collection,
                    "indexed": int(ingest_stats.get("indexed", 0)),
                    "skipped": int(ingest_stats.get("skipped", 0)),
                    "hits": len(rag_hits),
                    "retrieval_k": retrieval_k,
                    "rerank_top_n": rerank_top_n,
                    "expired_cleaned": int(cleaned),
                    "run_id": rag_run_id,
                    "user_id": user_id,
                    "source_doc_count": len(source_doc_records),
                    "chunk_count": len(chunk_records),
                }
                rag_trace = {
                    "enabled": True,
                    "backend": rag.backend_name,
                    "embedding_model": getattr(rag, "embedding_model", "unknown"),
                    "reranker_used": reranker_used,
                    "router_decision": rag_priority.value,
                    "collection": collection,
                    "indexed": int(ingest_stats.get("indexed", 0)),
                    "hits": len(rag_hits),
                    "retrieval_k": retrieval_k,
                    "rerank_top_n": rerank_top_n,
                    "run_id": rag_run_id,
                    "user_id": user_id,
                    "source_doc_count": len(source_doc_records),
                    "chunk_count": len(chunk_records),
                }
                finished_at = datetime.now(timezone.utc)
                rag_final_update = {
                    "router_decision": rag_priority.value,
                    "backend_requested": backend_requested,
                    "backend_actual": str(getattr(rag, "backend_name", "memory") or "memory"),
                    "collection": collection,
                    "retrieval_k": retrieval_k,
                    "rerank_top_n": rerank_top_n,
                    "source_doc_count": len(source_doc_records),
                    "chunk_count": len(chunk_records),
                    "retrieval_hit_count": len(pre_rerank_hits),
                    "rerank_hit_count": len(rerank_records),
                    "fallback_reason": str(getattr(rag, "fallback_reason", "") or "") or None,
                    "status": "success" if rag_hits else "partial",
                    "finished_at": finished_at,
                    "latency_ms": (finished_at - (rag_started_at or finished_at)).total_seconds() * 1000.0,
                }
                _append_rag_event(
                    "run_completed",
                    "complete",
                    {
                        "status": rag_final_update.get("status"),
                        "hit_count": len(rag_hits),
                        "source_doc_count": len(source_doc_records),
                        "chunk_count": len(chunk_records),
                    },
                )
            else:
                rag_trace = {
                    "enabled": False,
                    "reason": "no_rag_documents",
                    "router_decision": rag_priority.value,
                    "run_id": rag_run_id,
                }
                rag_fallback_records.append(
                    FallbackEventRecord(
                        id=_stable_id("fallback", rag_run_id or "unknown", "no_rag_documents"),
                        run_id=rag_run_id,
                        reason_code="no_rag_documents",
                        reason_text="deduped evidence did not produce chunkable content",
                        backend_before=backend_requested,
                        backend_after=backend_requested if backend_requested in {"memory", "postgres"} else "memory",
                        payload_json={"deduped_count": len(deduped)},
                    )
                )
                finished_at = datetime.now(timezone.utc)
                rag_final_update = {
                    "router_decision": rag_priority.value,
                    "backend_requested": backend_requested,
                    "backend_actual": backend_requested if backend_requested in {"memory", "postgres"} else "memory",
                    "collection": _collection_from_thread_id(thread_id),
                    "source_doc_count": len(source_doc_records),
                    "chunk_count": len(chunk_records),
                    "retrieval_hit_count": 0,
                    "rerank_hit_count": 0,
                    "fallback_reason": "no_rag_documents",
                    "status": "partial",
                    "finished_at": finished_at,
                    "latency_ms": (finished_at - (rag_started_at or finished_at)).total_seconds() * 1000.0,
                }
        elif not deduped:
            rag_trace = {"enabled": False, "reason": "empty_evidence_pool", "router_decision": rag_priority.value}
        else:
            rag_trace = {"enabled": False, "reason": "empty_query", "router_decision": rag_priority.value}
    except Exception as exc:
        rag_trace = {"enabled": False, "error": str(exc), "run_id": rag_run_id}
        if rag_run_id:
            rag_fallback_records.append(
                FallbackEventRecord(
                    id=_stable_id("fallback", rag_run_id, "rag_pipeline_error", str(exc)),
                    run_id=rag_run_id,
                    reason_code="rag_pipeline_error",
                    reason_text=str(exc),
                    backend_before=None,
                    backend_after="memory",
                    payload_json={"thread_id": str(state.get("thread_id") or "")},
                )
            )
            finished_at = datetime.now(timezone.utc)
            rag_final_update = {
                "status": "failed",
                "error_message": str(exc),
                "finished_at": finished_at,
                "latency_ms": (finished_at - (rag_started_at or finished_at)).total_seconds() * 1000.0,
            }
    finally:
        if rag_run_id:
            if rag_event_records:
                _store_call("append_query_events", rag_event_records)
            for fallback_record in rag_fallback_records:
                _store_call("append_fallback_event", fallback_record)
            if rag_final_update:
                _store_call("update_query_run", rag_run_id, **rag_final_update)
    trace.update(
        {
            "executor": {
                "type": "dry_run" if not live_tools else "live_tools",
                "ran_steps": len((plan_ir.get("steps") or []) if isinstance(plan_ir, dict) else []),
                "error_count": len((artifacts.get("errors") or []) if isinstance(artifacts, dict) else []),
                "failure_strategy_version": FAILURE_STRATEGY_VERSION,
                "events": exec_events,
            }
        }
    )
    trace["rag"] = rag_trace
    return {"artifacts": artifacts, "trace": trace}

