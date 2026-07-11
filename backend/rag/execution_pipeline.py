# -*- coding: utf-8 -*-
"""Execution-time RAG routing, ingestion, retrieval, and observability."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.graph.state import GraphState
from backend.rag.execution_observability import (
    build_rerank_hit_records,
    build_retrieval_hit_records,
    safe_store_call,
)
from backend.rag.execution_support import (
    _build_chunk_record_id,
    _build_rag_run_id,
    _build_source_doc_content,
    _build_source_doc_obs_id,
    _build_vector_source_id,
    _chunk_profile,
    _decorate_rag_hit,
    _env_int,
    _infer_chunk_doc_type,
    _infer_chunk_strategy,
    _parse_datetime,
    _resolve_rag_user_id,
    _resolve_session_id,
    _safe_event_payload,
    _stable_id,
)
from backend.rag.ingestion import (
    _build_memory_context_specs,
    _build_rag_doc_id,
    _collection_from_thread_id,
    _estimate_source_reliability,
    _kb_collection_from_subject,
    _memory_collection_from_thread,
    _summarize_layer_hits,
    _ttl_hours_for_evidence,
)
from backend.rag.layering import (
    build_kb_vector_source_id,
    collection_details,
    compute_doc_fingerprint,
    enrich_metadata,
    is_long_term_candidate,
    preferred_retrieval_collections,
)


logger = logging.getLogger(__name__)


async def run_execution_rag_pipeline(
    *,
    state: GraphState,
    subject: dict[str, Any],
    deduped: list[dict[str, Any]],
    step_index: dict[str, dict[str, Any]],
    artifacts: dict[str, Any],
    evidence_input_count: int,
) -> dict[str, Any]:
    # Phase 11.11.2: RAG v2 pipeline with routing
    rag_trace: dict[str, Any] = {"enabled": False}
    rag_run_id: str | None = None
    rag_started_at: datetime | None = None
    rag_obs_store: Any = None
    rag_event_records: list[Any] = []
    rag_fallback_records: list[Any] = []
    rag_final_update: dict[str, Any] | None = None

    def _store_call(*_args: Any, **_kwargs: Any) -> Any:
        return safe_store_call(rag_obs_store, *_args, logger=logger, **_kwargs)

    try:
        from backend.rag.chunker import chunk_document
        from backend.rag.hybrid_service import RAGDocument, get_rag_service
        from backend.rag.observability_models import (
            ChunkRecord,
            FallbackEventRecord,
            QueryEventRecord,
            QueryRunRecord,
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
                    "input_count": evidence_input_count,
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
                retrieval_records, input_rank_by_chunk_id = build_retrieval_hit_records(
                    pre_rerank_hits,
                    run_id=rag_run_id,
                    rerank_top_n=rerank_top_n,
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

                rerank_records = build_rerank_hit_records(
                    rag_hits,
                    run_id=rag_run_id,
                    input_rank_by_chunk_id=input_rank_by_chunk_id,
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
    return rag_trace
