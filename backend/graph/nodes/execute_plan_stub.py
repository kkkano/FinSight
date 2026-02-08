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


def _ttl_hours_for_evidence(*, subject_type: str, evidence_type: str, source: str) -> int:
    """
    RAG v2 TTL policy (minimal closed-loop):
    - filing/research_doc: persistent (no TTL)
    - news/selection/search-derived: short-term TTL
    - others: session-ephemeral TTL
    """
    if subject_type in ("filing", "research_doc"):
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
            source = item.get("source") or agent_name
            evidence_pool.append(
                {
                    "title": item.get("title") or f"{agent_name} evidence {i+1}",
                    "url": item.get("url"),
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

    # Phase 11.11.2: RAG v2 minimal loop
    rag_trace: dict[str, Any] = {"enabled": False}
    try:
        from backend.rag.hybrid_service import RAGDocument, get_rag_service

        query_text = str(state.get("query") or "").strip()
        thread_id = str(state.get("thread_id") or "").strip() or "unknown"
        if query_text and deduped:
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
                ttl_hours = _ttl_hours_for_evidence(
                    subject_type=subject_type,
                    evidence_type=evidence_type,
                    source=source,
                )
                expires_at = None if ttl_hours <= 0 else now + timedelta(hours=ttl_hours)
                rag_docs.append(
                    RAGDocument(
                        collection=collection,
                        scope="persistent" if ttl_hours <= 0 else "ephemeral",
                        source_id=_build_rag_doc_id(thread_id=thread_id, evidence=evidence, index=idx),
                        content=content[:4000],
                        title=title or None,
                        url=str(evidence.get("url") or "").strip() or None,
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
                top_k = _env_int("RAG_V2_TOP_K", 6, min_value=1, max_value=20)
                rag_hits = await asyncio.to_thread(
                    rag.hybrid_search,
                    query_text,
                    collection=collection,
                    top_k=top_k,
                )
                cleaned = await asyncio.to_thread(rag.cleanup_expired)
                artifacts["rag_context"] = rag_hits
                artifacts["rag_stats"] = {
                    "backend": rag.backend_name,
                    "collection": collection,
                    "indexed": int(ingest_stats.get("indexed", 0)),
                    "skipped": int(ingest_stats.get("skipped", 0)),
                    "hits": len(rag_hits),
                    "expired_cleaned": int(cleaned),
                }
                rag_trace = {
                    "enabled": True,
                    "backend": rag.backend_name,
                    "collection": collection,
                    "indexed": int(ingest_stats.get("indexed", 0)),
                    "hits": len(rag_hits),
                    "top_k": top_k,
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
