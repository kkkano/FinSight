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
from backend.graph.memory_scope import current_thread_focus, user_profile_memory
from backend.graph.request_task_contract import build_tool_diagnostic, output_is_error_like
from backend.graph.state import GraphState
from backend.rag.layering import (
    build_kb_vector_source_id,
    build_subject_kb_collection,
    build_thread_memory_collection,
    build_thread_working_set_collection,
    collection_details,
    compute_doc_fingerprint,
    enrich_metadata,
    is_long_term_candidate,
    preferred_retrieval_collections,
)


def build_tool_invokers(allowed_tools: list[str]) -> dict[str, Any]:
    return _build_tool_invokers(allowed_tools=allowed_tools or [])


def build_agent_invokers(allowed_agents: list[str], state: GraphState) -> dict[str, Any]:
    # Backward-compatible wrapper for tests that monkeypatch this symbol.
    return _build_agent_invokers(allowed_agents=allowed_agents or [], state=state)


_EXECUTION_OWNED_ARTIFACT_KEYS = {
    "agent_diagnostics",
    "brief_data",
    "draft_markdown",
    "errors",
    "evidence_by_task",
    "evidence_ledger",
    "evidence_pool",
    "rag_context",
    "rag_stats",
    "render_vars",
    "response",
    "signals",
    "step_results",
    "task_results",
    "tool_diagnostics",
    "verifier_result",
}


def _merge_prior_artifacts(prior: Any, current: Any) -> dict[str, Any]:
    if not isinstance(prior, dict):
        prior = {}
    if not isinstance(current, dict):
        current = {}
    preserved = {key: value for key, value in prior.items() if key not in _EXECUTION_OWNED_ARTIFACT_KEYS}
    return {**preserved, **current}


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
    return build_thread_working_set_collection(thread_id)


def _kb_collection_from_subject(subject: dict[str, Any] | None) -> str | None:
    return build_subject_kb_collection(subject if isinstance(subject, dict) else None)


def _memory_collection_from_thread(*, thread_id: str, user_id: str | None = None) -> str:
    return build_thread_memory_collection(thread_id=thread_id, user_id=user_id)


def _normalize_watchlist_items(value: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        symbol = str(item or '').strip().upper()
        if not symbol or symbol in result:
            continue
        result.append(symbol)
        if len(result) >= limit:
            break
    return result


def _normalize_memory_focus_list(value: Any, *, limit: int = 3) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = {
            'ticker': str(item.get('ticker') or '').strip().upper(),
            'query': str(item.get('query') or '').strip(),
            'summary': str(item.get('summary') or '').strip(),
            'sentiment': str(item.get('sentiment') or '').strip(),
            'updated_at': str(item.get('updated_at') or '').strip(),
        }
        if not any(normalized.values()):
            continue
        result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _build_memory_context_specs(*, memory_context: dict[str, Any], user_id: str) -> list[dict[str, Any]]:
    if not isinstance(memory_context, dict) or not memory_context:
        return []

    profile = user_profile_memory(memory_context)
    risk_tolerance = str(profile.get("risk_tolerance") or "").strip().lower()
    investment_style = str(profile.get("investment_style") or "").strip().lower()
    watchlist = _normalize_watchlist_items(profile.get("watchlist"))
    last_focus_raw = current_thread_focus(memory_context)
    last_focus_list = _normalize_memory_focus_list([last_focus_raw] if last_focus_raw else [], limit=1)
    last_focus = last_focus_list[0] if last_focus_list else None
    recent_focuses: list[dict[str, Any]] = []

    specs: list[dict[str, Any]] = []
    if watchlist or risk_tolerance not in {"", "medium"} or investment_style not in {"", "balanced"}:
        profile_lines = [
            "memory_kind: profile",
            f"user_id: {user_id}",
            f"risk_tolerance: {risk_tolerance or 'medium'}",
            f"investment_style: {investment_style or 'balanced'}",
        ]
        if watchlist:
            profile_lines.append(f"watchlist: {', '.join(watchlist)}")
        specs.append({
            "source_id": "memdoc:profile",
            "title": "Memory Profile",
            "content": "\n".join(profile_lines),
            "metadata": {
                "memory_kind": "profile",
                "watchlist": watchlist,
            },
        })

    if watchlist:
        specs.append({
            "source_id": "memdoc:watchlist",
            "title": "Memory Watchlist",
            "content": "\n".join([
                "memory_kind: watchlist",
                f"user_id: {user_id}",
                f"watchlist: {', '.join(watchlist)}",
            ]),
            "metadata": {
                "memory_kind": "watchlist",
                "watchlist": watchlist,
            },
        })

    if last_focus:
        ticker = str(last_focus.get("ticker") or "").strip().upper()
        focus_lines = [
            "memory_kind: last_focus",
            f"user_id: {user_id}",
        ]
        if ticker:
            focus_lines.append(f"ticker: {ticker}")
        if last_focus.get("query"):
            focus_lines.append(f"query: {last_focus['query']}")
        if last_focus.get("summary"):
            focus_lines.append(f"summary: {last_focus['summary']}")
        if last_focus.get("sentiment"):
            focus_lines.append(f"sentiment: {last_focus['sentiment']}")
        if last_focus.get("updated_at"):
            focus_lines.append(f"updated_at: {last_focus['updated_at']}")
        specs.append({
            "source_id": "memdoc:last_focus",
            "title": f"Memory Last Focus {ticker or user_id}",
            "content": "\n".join(focus_lines),
            "metadata": {
                "memory_kind": "last_focus",
                "ticker": ticker or None,
                "query": last_focus.get("query") or None,
                "sentiment": last_focus.get("sentiment") or None,
                "updated_at": last_focus.get("updated_at") or None,
            },
        })

    seen_recent_keys: set[tuple[str, str]] = set()
    if last_focus:
        seen_recent_keys.add((str(last_focus.get("ticker") or "").strip().upper(), str(last_focus.get("query") or "").strip()))

    for index, focus in enumerate(recent_focuses, start=1):
        ticker = str(focus.get("ticker") or "").strip().upper()
        query = str(focus.get("query") or "").strip()
        focus_key = (ticker, query)
        if focus_key in seen_recent_keys:
            continue
        seen_recent_keys.add(focus_key)
        recent_lines = [
            "memory_kind: recent_focus",
            f"user_id: {user_id}",
            f"recent_focus_rank: {index}",
        ]
        if ticker:
            recent_lines.append(f"ticker: {ticker}")
        if query:
            recent_lines.append(f"query: {query}")
        if focus.get("summary"):
            recent_lines.append(f"summary: {focus['summary']}")
        if focus.get("sentiment"):
            recent_lines.append(f"sentiment: {focus['sentiment']}")
        if focus.get("updated_at"):
            recent_lines.append(f"updated_at: {focus['updated_at']}")
        specs.append({
            "source_id": f"memdoc:recent_focus:{index}",
            "title": f"Memory Recent Focus {index} {ticker or user_id}",
            "content": "\n".join(recent_lines),
            "metadata": {
                "memory_kind": "recent_focus",
                "memory_rank": index,
                "ticker": ticker or None,
                "query": query or None,
                "sentiment": focus.get("sentiment") or None,
                "updated_at": focus.get("updated_at") or None,
            },
        })

    return [spec for spec in specs if str(spec.get("content") or "").strip()]
    return [spec for spec in specs if str(spec.get("content") or "").strip()]


def _resolve_hit_layer(hit: dict[str, Any]) -> str:
    metadata = hit.get('metadata') if isinstance(hit.get('metadata'), dict) else {}
    collection = str(hit.get('collection') or metadata.get('collection') or '').strip()
    details = collection_details(collection)
    return str(hit.get('layer') or metadata.get('layer') or details.get('layer') or 'unknown').strip().lower() or 'unknown'


def _summarize_layer_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    total_matches = 0

    for hit in hits or []:
        metadata = hit.get('metadata') if isinstance(hit.get('metadata'), dict) else {}
        matched_collections_raw = hit.get('matched_collections') or metadata.get('matched_collections')
        collection_pairs: list[tuple[str, str]] = []
        if isinstance(matched_collections_raw, list):
            for item in matched_collections_raw:
                collection = str(item or '').strip()
                if not collection:
                    continue
                details = collection_details(collection)
                layer = str(details.get('layer') or 'unknown').strip().lower() or 'unknown'
                collection_pairs.append((layer, collection))

        if not collection_pairs:
            collection = str(hit.get('collection') or metadata.get('collection') or '').strip()
            collection_pairs.append((_resolve_hit_layer(hit), collection))

        title = str(hit.get('title') or hit.get('source_id') or '').strip()
        seen_layers_for_hit: set[str] = set()
        for layer, collection in collection_pairs:
            normalized_layer = str(layer or 'unknown').strip().lower() or 'unknown'
            bucket = buckets.setdefault(normalized_layer, {
                'layer': normalized_layer,
                'count': 0,
                'collections': [],
                'sample_titles': [],
            })
            if normalized_layer not in seen_layers_for_hit:
                bucket['count'] += 1
                total_matches += 1
                seen_layers_for_hit.add(normalized_layer)
            if collection and collection not in bucket['collections']:
                bucket['collections'].append(collection)
            if title and title not in bucket['sample_titles'] and len(bucket['sample_titles']) < 3:
                bucket['sample_titles'].append(title)

    total = max(1, total_matches)
    items = []
    for layer, bucket in buckets.items():
        items.append({
            'layer': layer,
            'count': int(bucket['count']),
            'share': float(bucket['count']) / float(total),
            'collections': bucket['collections'],
            'sample_titles': bucket['sample_titles'],
        })
    return sorted(items, key=lambda item: (-int(item['count']), str(item['layer'])))

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
        "layer",
        "entity_scope",
        "entity_key",
        "ingest_source",
        "promotion_status",
        "doc_fingerprint",
        "parent_collection",
        "parent_run_id",
        "matched_layers",
        "matched_collections",
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
    artifacts = _merge_prior_artifacts(state.get("artifacts"), artifacts)

    # Phase 4: build a unified evidence_pool from selection (ephemeral, request-scoped).
    subject = state.get("subject") or {}
    selection_payload = subject.get("selection_payload") if isinstance(subject, dict) else None
    evidence_pool: list[dict[str, Any]] = []
    existing_evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts, dict) else None
    if isinstance(existing_evidence_pool, list):
        evidence_pool.extend([item for item in existing_evidence_pool if isinstance(item, dict)])
    tool_diagnostics: list[dict[str, Any]] = []
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

    def _step_task_ids(step: dict[str, Any]) -> list[str]:
        raw = step.get("task_ids")
        values = raw if isinstance(raw, list) else []
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            task_id = str(value or "").strip()
            if task_id and task_id not in seen:
                seen.add(task_id)
                result.append(task_id)
        single = str(step.get("task_id") or "").strip()
        if single and single not in seen:
            result.insert(0, single)
        return result

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
        if output_is_error_like(output):
            return

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
                article_text = f"{title} {snippet} {url}".lower()
                if "cpi" in article_text and (
                    "london stock exchange:cpi" in article_text
                    or "lse:cpi" in article_text
                    or "capita" in article_text
                ):
                    continue
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

        if tool_name == "get_official_macro_releases" and isinstance(output, dict):
            releases = output.get("releases") or []
            for i, release in enumerate(releases[:10]):
                if not isinstance(release, dict):
                    continue
                title = str(release.get("title") or "").strip()
                url = str(release.get("url") or "").strip()
                snippet = str(release.get("snippet") or title).strip()
                if not title and not url:
                    continue
                evidence_pool.append(
                    {
                        "title": title or f"macro release {i+1}",
                        "url": url or None,
                        "snippet": snippet[:800],
                        "source": release.get("source") or "macro_official_feeds",
                        "published_date": release.get("published_date"),
                        "confidence": release.get("confidence", 0.82 if release.get("is_official") else 0.65),
                        "type": release.get("type") or "macro_release",
                        "id": release.get("id") or f"{tool_name}:{step_id}:{i+1}",
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

        if tool_name == "fetch_url_content" and isinstance(output, dict):
            title = str(output.get("title") or output.get("url") or "URL content").strip()
            url = str(output.get("final_url") or output.get("url") or "").strip()
            snippet = str(output.get("description") or output.get("content") or output.get("error") or "").strip()
            evidence_pool.append(
                {
                    "title": title,
                    "url": url or None,
                    "snippet": snippet[:1200],
                    "source": output.get("source") or "url",
                    "published_date": None,
                    "confidence": 0.75 if output.get("content") else 0.45,
                    "type": "url",
                    "id": output.get("id") or f"{tool_name}:{step_id}",
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
                        before_count = len(evidence_pool)
                        _append_agent_evidence(str(agent_name), str(step_id), item.get("output"))
                        for evidence in evidence_pool[before_count:]:
                            if isinstance(evidence, dict):
                                evidence["step_id"] = str(step_id)
                                evidence["task_ids"] = _step_task_ids(step)
                continue
            tool_name = step.get("name") or ""
            if not tool_name:
                continue
            output = item.get("output")
            if output_is_error_like(output):
                tool_diagnostics.append(
                    build_tool_diagnostic(
                        tool_name=str(tool_name),
                        step_id=str(step_id),
                        task_ids=_step_task_ids(step),
                        output=output,
                    )
                )
                continue
            before_count = len(evidence_pool)
            _append_tool_evidence(str(tool_name), str(step_id), output)
            for evidence in evidence_pool[before_count:]:
                if isinstance(evidence, dict):
                    evidence["step_id"] = str(step_id)
                    evidence["task_ids"] = _step_task_ids(step)

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
    evidence_by_task: dict[str, list[dict[str, Any]]] = {}
    for evidence in deduped:
        task_ids = evidence.get("task_ids") if isinstance(evidence, dict) else None
        for task_id in [str(value or "").strip() for value in (task_ids if isinstance(task_ids, list) else [])]:
            if not task_id:
                continue
            evidence_by_task.setdefault(task_id, []).append(evidence)
    artifacts["evidence_by_task"] = evidence_by_task
    if tool_diagnostics:
        artifacts["tool_diagnostics"] = tool_diagnostics

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
        from backend.rag.observability_store import (
            get_rag_observability_store,
            redact_query_text,
            suppress_rag_observability_hooks,
        )
        from backend.rag.rag_router import RAGPriority, decide_rag_priority

        query_text = str(state.get("query") or "").strip()
        thread_id = str(state.get("thread_id") or "").strip() or "unknown"
        session_id = _resolve_session_id(state)
        user_id = _resolve_rag_user_id(state, session_id=session_id)
        memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
        if not memory_context:
            try:
                from backend.graph.store import load_memory_context

                memory_context = load_memory_context(thread_id=thread_id)
            except Exception as exc:
                logger.debug("load_memory_context for RAG failed: %s", exc)
                memory_context = {}
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
                    query_text_redacted=redact_query_text(query_text),
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
        elif query_text:
            rag = get_rag_service()
            subject_type = str((subject or {}).get("subject_type") or "unknown")
            collection = _collection_from_thread_id(thread_id)
            kb_collection = _kb_collection_from_subject(subject)
            memory_specs = _build_memory_context_specs(memory_context=memory_context, user_id=user_id)
            memory_collection = _memory_collection_from_thread(thread_id=thread_id, user_id=user_id) if memory_specs else None
            working_set_details = collection_details(collection)
            memory_details = collection_details(memory_collection) if memory_collection else {}
            kb_details = collection_details(kb_collection) if kb_collection else {}
            search_collections = preferred_retrieval_collections(memory_collection=memory_collection, working_set_collection=collection, kb_collection=kb_collection)
            now = datetime.now(timezone.utc)
            rag_docs: list[RAGDocument] = []
            source_doc_records: list[Any] = []
            chunk_records: list[Any] = []
            promoted_chunk_count = 0
            memory_doc_count = 0
            layer_hit_breakdown: list[dict[str, Any]] = []

            _append_rag_event(
                "retrieval_scope_planned",
                "retrieval",
                {
                    "memory_collection": memory_collection,
                    "working_set_collection": collection,
                    "kb_collection": kb_collection,
                    "memory_doc_count": len(memory_specs),
                    "search_collections": search_collections,
                },
            )

            if memory_specs and memory_collection:
                for memory_index, memory_spec in enumerate(memory_specs):
                    memory_title = str(memory_spec.get("title") or "Memory Context").strip()
                    memory_content = str(memory_spec.get("content") or "").strip()
                    if not memory_content:
                        continue
                    memory_source_id = str(memory_spec.get("source_id") or f"memdoc:{memory_index}").strip() or f"memdoc:{memory_index}"
                    memory_metadata = memory_spec.get("metadata") if isinstance(memory_spec.get("metadata"), dict) else {}
                    memory_updated_at = _parse_datetime(memory_metadata.get("updated_at"))
                    memory_doc_fingerprint = compute_doc_fingerprint(
                        title=memory_title or None,
                        url=None,
                        content=memory_content,
                        source_id=memory_source_id,
                    )
                    memory_source_doc_id = _build_source_doc_obs_id(
                        run_id=rag_run_id or "unknown",
                        source_id=memory_source_id,
                        title=memory_title,
                        url="",
                        index=memory_index,
                    )
                    memory_chunk_id = _build_chunk_record_id(
                        run_id=rag_run_id or "unknown",
                        source_doc_id=memory_source_doc_id,
                        chunk_index=0,
                        chunk_text=memory_content,
                    )
                    memory_source_doc_metadata = enrich_metadata(
                        {
                            "scope": "persistent",
                            "run_id": rag_run_id,
                            "memory_kind": memory_metadata.get("memory_kind"),
                            **memory_metadata,
                        },
                        collection=memory_collection,
                        ingest_source="memory_context",
                        promotion_status="memory",
                        parent_run_id=rag_run_id,
                        doc_fingerprint=memory_doc_fingerprint,
                    )
                    memory_chunk_metadata = enrich_metadata(
                        {
                            "scope": "persistent",
                            "run_id": rag_run_id,
                            "source_id": memory_source_id,
                            "source_name": "memory",
                            "title": memory_title,
                            "vector_source_id": memory_source_id,
                            "source_doc_id": memory_source_doc_id,
                            "chunk_id": memory_chunk_id,
                            "doc_type": "memory_context",
                            "chunk_index": 0,
                            "total_chunks": 1,
                            "chunk_strategy": "memory_context",
                            "chunk_size": len(memory_content),
                            "chunk_overlap": 0,
                            "memory_kind": memory_metadata.get("memory_kind"),
                            **memory_metadata,
                        },
                        collection=memory_collection,
                        ingest_source="memory_context",
                        promotion_status="memory",
                        parent_run_id=rag_run_id,
                        doc_fingerprint=memory_doc_fingerprint,
                    )
                    source_doc_records.append(
                        SourceDocRecord(
                            id=memory_source_doc_id,
                            run_id=rag_run_id or "unknown",
                            collection=memory_collection,
                            source_id=memory_source_id,
                            source_type="memory_context",
                            source_name="memory",
                            url=None,
                            title=memory_title or None,
                            published_at=memory_updated_at,
                            content_raw=memory_content,
                            content_preview=memory_content[:800],
                            content_length=len(memory_content),
                            metadata_json=memory_source_doc_metadata,
                        )
                    )
                    chunk_records.append(
                        ChunkRecord(
                            id=memory_chunk_id,
                            run_id=rag_run_id or "unknown",
                            collection=memory_collection,
                            source_id=memory_source_id,
                            source_doc_id=memory_source_doc_id,
                            chunk_index=0,
                            total_chunks=1,
                            chunk_text=memory_content,
                            chunk_length=len(memory_content),
                            doc_type="memory_context",
                            chunk_strategy="memory_context",
                            chunk_size=len(memory_content),
                            chunk_overlap=0,
                            metadata_json=memory_chunk_metadata,
                        )
                    )
                    rag_docs.append(
                        RAGDocument(
                            collection=memory_collection,
                            scope="persistent",
                            source_id=memory_source_id,
                            content=memory_content,
                            title=memory_title or None,
                            url=None,
                            source="memory",
                            metadata=memory_chunk_metadata,
                            expires_at=None,
                            layer=memory_details.get("layer"),
                            entity_scope=memory_details.get("entity_scope"),
                            entity_key=memory_details.get("entity_key"),
                            ingest_source="memory_context",
                            promotion_status="memory",
                            doc_fingerprint=memory_doc_fingerprint,
                            parent_run_id=rag_run_id,
                        )
                    )
                    memory_doc_count += 1
                _append_rag_event(
                    "memory_materialized",
                    "memory",
                    {
                        "memory_collection": memory_collection,
                        "memory_doc_count": memory_doc_count,
                        "memory_source_ids": [str(item.get("source_id") or "").strip() for item in memory_specs],
                    },
                )

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

                doc_fingerprint = compute_doc_fingerprint(
                    title=title or None,
                    url=evidence_url or None,
                    content=raw_content,
                    source_id=source_id,
                )
                promote_to_kb = bool(kb_collection) and is_long_term_candidate(
                    source_type=evidence_type,
                    source=source,
                    metadata=evidence if isinstance(evidence, dict) else None,
                    title=title or None,
                    url=evidence_url or None,
                )
                source_doc_metadata = enrich_metadata(
                    {
                        "scope": scope,
                        "confidence": evidence.get("confidence"),
                        "published_date": evidence.get("published_date"),
                        "type": evidence_type,
                        "source": source,
                        "run_id": rag_run_id,
                        "kb_collection": kb_collection,
                    },
                    collection=collection,
                    ingest_source="execute_plan_stub",
                    promotion_status="promoted" if promote_to_kb else "working_set_only",
                    parent_run_id=rag_run_id,
                    doc_fingerprint=doc_fingerprint,
                )
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
                        metadata_json=source_doc_metadata,
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
                    chunk_metadata = enrich_metadata(
                        {
                            "scope": scope,
                            "source_id": source_id,
                            "source_name": source,
                            "url": evidence_url or None,
                            "title": title or None,
                            "vector_source_id": vector_source_id,
                            "published_date": evidence.get("published_date"),
                            "confidence": evidence.get("confidence"),
                            "type": evidence_type,
                            "run_id": rag_run_id,
                            "source_doc_id": source_doc_id,
                            "chunk_id": chunk_record_id,
                            "doc_type": str(chunk_meta.get("doc_type") or doc_type),
                            "chunk_index": chunk_index,
                            "total_chunks": max(1, int(chunk_meta.get("total_chunks") or chunk_total or 1)),
                            "chunk_strategy": chunk_strategy,
                            "chunk_size": int(chunk_profile.get("max_chunk_size") or len(chunk_body)),
                            "chunk_overlap": int(chunk_profile.get("overlap") or 0),
                            "kb_collection": kb_collection,
                        },
                        collection=collection,
                        ingest_source="execute_plan_stub",
                        promotion_status="promoted" if promote_to_kb else "working_set_only",
                        parent_run_id=rag_run_id,
                        doc_fingerprint=doc_fingerprint,
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
                            metadata_json=chunk_metadata,
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
                            metadata=chunk_metadata,
                            expires_at=expires_at,
                            layer=working_set_details.get("layer"),
                            entity_scope=working_set_details.get("entity_scope"),
                            entity_key=working_set_details.get("entity_key"),
                            ingest_source="execute_plan_stub",
                            promotion_status="working_set",
                            doc_fingerprint=doc_fingerprint,
                            parent_run_id=rag_run_id,
                        )
                    )
                    if promote_to_kb and kb_collection:
                        kb_vector_source_id = build_kb_vector_source_id(doc_fingerprint=doc_fingerprint, chunk_index=chunk_index)
                        kb_metadata = enrich_metadata(
                            dict(chunk_metadata),
                            collection=kb_collection,
                            ingest_source="execute_plan_stub",
                            promotion_status="promoted",
                            parent_collection=collection,
                            parent_run_id=rag_run_id,
                            doc_fingerprint=doc_fingerprint,
                        )
                        rag_docs.append(
                            RAGDocument(
                                collection=kb_collection,
                                scope="persistent",
                                source_id=kb_vector_source_id,
                                content=chunk_body,
                                title=title or None,
                                url=evidence_url or None,
                                source=source,
                                metadata=kb_metadata,
                                expires_at=None,
                                layer=kb_details.get("layer"),
                                entity_scope=kb_details.get("entity_scope"),
                                entity_key=kb_details.get("entity_key"),
                                ingest_source="execute_plan_stub",
                                promotion_status="promoted",
                                doc_fingerprint=doc_fingerprint,
                                parent_collection=collection,
                                parent_run_id=rag_run_id,
                            )
                        )
                        promoted_chunk_count += 1

            _store_call("append_source_docs", source_doc_records)
            _store_call("append_chunks", chunk_records)
            _append_rag_event("source_doc_created", "source_docs", {"source_doc_count": len(source_doc_records)})
            _append_rag_event(
                "chunk_created",
                "chunking",
                {
                    "chunk_count": len(chunk_records),
                    "memory_doc_count": memory_doc_count,
                    "promoted_chunk_count": promoted_chunk_count,
                    "memory_collection": memory_collection,
                    "kb_collection": kb_collection,
                },
            )

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

            if search_collections:
                ingest_stats: dict[str, Any] = {"indexed": 0, "skipped": 0}
                with suppress_rag_observability_hooks():
                    if rag_docs:
                        ingest_stats = await asyncio.to_thread(rag.ingest_documents, rag_docs)
                    rerank_top_n = _env_int("RAG_V2_RERANK_TOP_N", 8, min_value=1, max_value=20)
                    retrieval_k = _env_int("RAG_V2_TOP_K", max(rerank_top_n * 3, 18), min_value=1, max_value=60)
                    if len(search_collections) > 1:
                        retrieved_hits = await asyncio.to_thread(
                            rag.hybrid_search_many,
                            query_text,
                            collections=search_collections,
                            top_k=retrieval_k,
                        )
                    else:
                        retrieved_hits = await asyncio.to_thread(
                            rag.hybrid_search,
                            query_text,
                            collection=search_collections[0],
                            top_k=retrieval_k,
                        )
                pre_rerank_hits = [_decorate_rag_hit(hit) for hit in (retrieved_hits or [])]
                layer_hit_breakdown = _summarize_layer_hits(pre_rerank_hits)
                rag_hits = pre_rerank_hits[:rerank_top_n]
                reranker_used = False
                try:
                    # ⚠️ reranker 主开关默认关闭。即便 .env 配了 RAG_RERANKER 模型，
                    # 检索结果也不会经过 bge-reranker 重排（模型会被加载占内存却不生效）。
                    # 要真正启用重排提质，必须显式设置 RAG_ENABLE_RERANKER=true；
                    # 若不打算用 reranker，建议把 RAG_RERANKER* 配置删掉以省内存。
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
                                "layer": hit.get("layer") or metadata.get("layer"),
                                "collection_kind": hit.get("collection_kind") or metadata.get("collection_kind"),
                                "entity_scope": hit.get("entity_scope") or metadata.get("entity_scope"),
                                "entity_key": hit.get("entity_key") or metadata.get("entity_key"),
                                "search_collections": hit.get("search_collections") or metadata.get("search_collections"),
                                "source_collection_rank": hit.get("source_collection_rank") or metadata.get("source_collection_rank"),
                                "search_rank_in_collection": hit.get("search_rank_in_collection") or metadata.get("search_rank_in_collection"),
                                "promotion_status": hit.get("promotion_status") or metadata.get("promotion_status"),
                                "parent_collection": hit.get("parent_collection") or metadata.get("parent_collection"),
                                "parent_run_id": hit.get("parent_run_id") or metadata.get("parent_run_id"),
                                "matched_layers": hit.get("matched_layers") or metadata.get("matched_layers"),
                                "matched_collections": hit.get("matched_collections") or metadata.get("matched_collections"),
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
                        "search_collections": search_collections,
                        "memory_collection": memory_collection,
                        "kb_collection": kb_collection,
                        "layer_hit_breakdown": layer_hit_breakdown,
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
                                "layer": hit.get("layer") or metadata.get("layer"),
                                "collection_kind": hit.get("collection_kind") or metadata.get("collection_kind"),
                                "entity_scope": hit.get("entity_scope") or metadata.get("entity_scope"),
                                "entity_key": hit.get("entity_key") or metadata.get("entity_key"),
                                "promotion_status": hit.get("promotion_status") or metadata.get("promotion_status"),
                                "matched_layers": hit.get("matched_layers") or metadata.get("matched_layers"),
                                "matched_collections": hit.get("matched_collections") or metadata.get("matched_collections"),
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
                    "memory_collection": memory_collection,
                    "kb_collection": kb_collection,
                    "search_collections": search_collections,
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
                    "memory_doc_count": memory_doc_count,
                    "layer_hit_breakdown": layer_hit_breakdown,
                }
                rag_trace = {
                    "enabled": True,
                    "backend": rag.backend_name,
                    "embedding_model": getattr(rag, "embedding_model", "unknown"),
                    "reranker_used": reranker_used,
                    "router_decision": rag_priority.value,
                    "collection": collection,
                    "memory_collection": memory_collection,
                    "kb_collection": kb_collection,
                    "search_collections": search_collections,
                    "indexed": int(ingest_stats.get("indexed", 0)),
                    "hits": len(rag_hits),
                    "retrieval_k": retrieval_k,
                    "rerank_top_n": rerank_top_n,
                    "run_id": rag_run_id,
                    "user_id": user_id,
                    "source_doc_count": len(source_doc_records),
                    "chunk_count": len(chunk_records),
                    "memory_doc_count": memory_doc_count,
                    "layer_hit_breakdown": layer_hit_breakdown,
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
                    "metadata_json": {
                        "layer": working_set_details.get("layer"),
                        "memory_collection": memory_collection,
                        "working_set_collection": collection,
                        "kb_collection": kb_collection,
                        "search_collections": search_collections,
                        "memory_doc_count": memory_doc_count,
                        "promoted_chunk_count": promoted_chunk_count,
                        "layer_hit_breakdown": layer_hit_breakdown,
                    },
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
                        "memory_doc_count": memory_doc_count,
                        "layer_hit_breakdown": layer_hit_breakdown,
                    },
                )
            else:
                rag_trace = {
                    "enabled": False,
                    "reason": "no_search_collections",
                    "router_decision": rag_priority.value,
                    "run_id": rag_run_id,
                }
                rag_fallback_records.append(
                    FallbackEventRecord(
                        id=_stable_id("fallback", rag_run_id or "unknown", "no_search_collections"),
                        run_id=rag_run_id,
                        reason_code="no_search_collections",
                        reason_text="query did not resolve any RAG collections",
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
                    "metadata_json": {
                        "layer": working_set_details.get("layer"),
                        "memory_collection": memory_collection,
                        "working_set_collection": collection,
                        "kb_collection": kb_collection,
                        "search_collections": search_collections,
                        "memory_doc_count": memory_doc_count,
                        "promoted_chunk_count": promoted_chunk_count,
                        "layer_hit_breakdown": layer_hit_breakdown,
                    },
                    "fallback_reason": "no_search_collections",
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
    if str(os.getenv("RESEARCH_LEDGER_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}:
        try:
            from backend.research.ledger_builder import build_ledger_from_artifacts

            artifacts["evidence_ledger"] = build_ledger_from_artifacts(state, artifacts)
        except Exception as exc:
            logger.warning("Evidence ledger build failed: %s", exc)
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
