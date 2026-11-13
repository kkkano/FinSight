# -*- coding: utf-8 -*-
"""Observability record builders for execution-time RAG retrieval."""
from __future__ import annotations

from typing import Any

from backend.rag.execution_support import _stable_id
from backend.rag.observability_models import RerankHitRecord, RetrievalHitRecord


def safe_store_call(
    store: Any,
    method_name: str,
    *args: Any,
    logger: Any,
    **kwargs: Any,
) -> Any:
    if store is None:
        return None
    method = getattr(store, method_name, None)
    if not callable(method):
        return None
    try:
        return method(*args, **kwargs)
    except Exception as exc:
        logger.warning("RAG 鍙娴嬪啓鍏ュけ璐?method=%s error=%s", method_name, exc)
        return None


def build_retrieval_hit_records(
    hits: list[dict[str, Any]],
    *,
    run_id: str | None,
    rerank_top_n: int,
) -> tuple[list[RetrievalHitRecord], dict[str, int]]:
    records: list[RetrievalHitRecord] = []
    input_rank_by_chunk_id: dict[str, int] = {}
    for index, hit in enumerate(hits, start=1):
        metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        chunk_id = str(hit.get("chunk_id") or metadata.get("chunk_id") or "").strip() or None
        if chunk_id:
            input_rank_by_chunk_id[chunk_id] = index
        records.append(
            RetrievalHitRecord(
                id=_stable_id("rhit", run_id or "unknown", index, chunk_id or hit.get("source_id")),
                run_id=run_id or "unknown",
                chunk_id=chunk_id,
                collection=hit.get("collection"),
                source_id=str(
                    hit.get("evidence_source_id")
                    or metadata.get("source_id")
                    or hit.get("source_id")
                    or ""
                ).strip()
                or None,
                source_doc_id=str(hit.get("source_doc_id") or metadata.get("source_doc_id") or "").strip()
                or None,
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
                    "source_collection_rank": hit.get("source_collection_rank")
                    or metadata.get("source_collection_rank"),
                    "search_rank_in_collection": hit.get("search_rank_in_collection")
                    or metadata.get("search_rank_in_collection"),
                    "promotion_status": hit.get("promotion_status") or metadata.get("promotion_status"),
                    "parent_collection": hit.get("parent_collection") or metadata.get("parent_collection"),
                    "parent_run_id": hit.get("parent_run_id") or metadata.get("parent_run_id"),
                    "matched_layers": hit.get("matched_layers") or metadata.get("matched_layers"),
                    "matched_collections": hit.get("matched_collections") or metadata.get("matched_collections"),
                },
            )
        )
    return records, input_rank_by_chunk_id


def build_rerank_hit_records(
    hits: list[dict[str, Any]],
    *,
    run_id: str | None,
    input_rank_by_chunk_id: dict[str, int],
) -> list[RerankHitRecord]:
    records: list[RerankHitRecord] = []
    for output_rank, hit in enumerate(hits, start=1):
        metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        chunk_id = str(hit.get("chunk_id") or metadata.get("chunk_id") or "").strip() or None
        records.append(
            RerankHitRecord(
                id=_stable_id("rrhit", run_id or "unknown", output_rank, chunk_id or hit.get("source_id")),
                run_id=run_id or "unknown",
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
    return records
