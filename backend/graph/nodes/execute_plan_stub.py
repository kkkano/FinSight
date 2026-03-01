# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import hashlib
import json
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

    # E4: DeepSearch high-quality results → persistent
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
    try:
        from backend.rag.hybrid_service import RAGDocument, get_rag_service
        from backend.rag.rag_router import RAGPriority, decide_rag_priority

        query_text = str(state.get("query") or "").strip()
        thread_id = str(state.get("thread_id") or "").strip() or "unknown"
        output_mode = str(state.get("output_mode") or "").strip()
        operation_name = str((state.get("operation") or {}).get("name", "")).strip() if isinstance(state.get("operation"), dict) else ""

        # E5: Query routing — decide RAG priority
        rag_priority = decide_rag_priority(
            query=query_text,
            output_mode=output_mode,
            operation=operation_name,
            subject_type=str((subject or {}).get("subject_type") or ""),
        )

        if rag_priority == RAGPriority.SKIP:
            rag_trace = {"enabled": False, "reason": "router_skip", "router_decision": rag_priority.value}
        elif query_text and deduped:
            rag = get_rag_service()
            subject_type = str((subject or {}).get("subject_type") or "unknown")
            collection = _collection_from_thread_id(thread_id)
            now = datetime.now(timezone.utc)
            rag_docs: list[RAGDocument] = []
            for idx, evidence in enumerate(deduped[:80]):
                title = str(evidence.get("title") or "").strip()
                snippet = str(evidence.get("snippet") or "").strip()
                content = "\n".join([v for v in (title, snippet) if v]).strip()
                if not content:
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
                rag_docs.append(
                    RAGDocument(
                        collection=collection,
                        scope=scope,
                        source_id=_build_rag_doc_id(thread_id=thread_id, evidence=evidence, index=idx),
                        content=content[:4000],
                        title=title or None,
                        url=evidence_url or None,
                        source=source,
                        metadata={
                            "published_date": evidence.get("published_date"),
                            "confidence": evidence.get("confidence"),
                            "type": evidence_type,
                        },
                        expires_at=expires_at,
                    )
                )

            if rag_docs:
                ingest_stats = await asyncio.to_thread(rag.ingest_documents, rag_docs)
                # Retrieve candidates (fetch more for reranking)
                rerank_top_n = _env_int("RAG_V2_RERANK_TOP_N", 8, min_value=1, max_value=20)
                retrieval_k = _env_int("RAG_V2_TOP_K", max(rerank_top_n * 3, 18), min_value=1, max_value=60)
                rag_hits = await asyncio.to_thread(
                    rag.hybrid_search,
                    query_text,
                    collection=collection,
                    top_k=retrieval_k,
                )
                # Cross-Encoder reranking (opt-in; disabled by default to keep
                # local/test environments stable and lightweight).
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
                        if reranker.is_enabled and rag_hits:
                            rag_hits = await asyncio.to_thread(
                                reranker.rerank,
                                query_text,
                                rag_hits,
                                top_n=rerank_top_n,
                            )
                            reranker_used = True
                    else:
                        rag_hits = rag_hits[:rerank_top_n]
                except Exception as rerank_exc:
                    logger.debug("Reranker unavailable, using RRF order: %s", rerank_exc)
                    rag_hits = rag_hits[:rerank_top_n]

                cleaned = await asyncio.to_thread(rag.cleanup_expired)
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
                }
            else:
                rag_trace = {"enabled": False, "reason": "no_rag_documents"}
        elif not deduped:
            rag_trace = {"enabled": False, "reason": "empty_evidence_pool"}
        else:
            rag_trace = {"enabled": False, "reason": "empty_query"}
    except Exception as exc:
        rag_trace = {"enabled": False, "error": str(exc)}

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
