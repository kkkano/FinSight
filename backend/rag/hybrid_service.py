# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import create_engine, text

from backend.rag.embedder import (
    EmbeddingService,
    SparseVector,
    get_embedding_service,
)
from backend.rag.layering import collection_details, enrich_metadata

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 64) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except Exception:
        return default
    return max(min_value, min(max_value, value))


def _normalize_collections(collections: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for collection in collections or []:
        value = str(collection or "").strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _search_many_bounded(
    search_one,
    query: str,
    *,
    collections: Iterable[str],
    top_k: int,
    max_workers: int | None = None,
) -> list[list[dict[str, Any]]]:
    normalized = _normalize_collections(collections)
    if not normalized:
        return []

    candidate_k = max(1, int(top_k))
    worker_count = min(len(normalized), max(1, int(max_workers or _env_int("RAG_SEARCH_MANY_MAX_WORKERS", 4, min_value=1, max_value=16))))
    groups: list[list[dict[str, Any]]] = [[] for _ in normalized]

    def _run(collection_index: int, collection: str) -> tuple[int, list[dict[str, Any]]]:
        hits = list(search_one(query, collection=collection, top_k=candidate_k) or [])
        for local_rank, hit in enumerate(hits, start=1):
            hit["search_collections"] = list(normalized)
            hit["source_collection_rank"] = collection_index + 1
            hit["search_rank_in_collection"] = local_rank
        return collection_index, hits

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="rag-search-many") as executor:
        futures = {}
        for collection_index, collection in enumerate(normalized):
            context = copy_context()
            futures[executor.submit(context.run, _run, collection_index, collection)] = collection_index
        for future in as_completed(futures):
            collection_index, hits = future.result()
            groups[collection_index] = hits
    return groups


def _is_production_env() -> bool:
    values = [
        os.getenv("APP_ENV", ""),
        os.getenv("ENV", ""),
        os.getenv("NODE_ENV", ""),
        os.getenv("FASTAPI_ENV", ""),
    ]
    return any(str(v).strip().lower() in {"prod", "production"} for v in values)


def _log_backend_fallback(*, reason: str, detail: str | None = None, backend_requested: str | None = None) -> None:
    payload: dict[str, Any] = {
        "event": "rag_backend_fallback",
        "backend": "memory",
        "reason": reason,
        "backend_requested": backend_requested or os.getenv("RAG_V2_BACKEND", "auto"),
    }
    if detail:
        payload["detail"] = detail
    log_fn = logger.warning if _is_production_env() else logger.info
    log_fn("rag_backend_fallback %s", payload)


# ---------------------------------------------------------------------------
# Embedding helpers (delegate to EmbeddingService)
# ---------------------------------------------------------------------------

def _embed_text(text_value: str, embedder: EmbeddingService) -> tuple[list[float], SparseVector]:
    """Encode a single text into (dense_vector, sparse_vector)."""
    return embedder.encode_single(text_value)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _sparse_score(query_sparse: SparseVector, doc_sparse: SparseVector) -> float:
    """Weighted sparse matching using lexical weights."""
    if not query_sparse.weights or not doc_sparse.weights:
        return 0.0
    score = 0.0
    for token, q_weight in query_sparse.weights.items():
        if token in doc_sparse.weights:
            score += q_weight * doc_sparse.weights[token]
    # Normalise by query magnitude
    q_norm = sum(w * w for w in query_sparse.weights.values()) ** 0.5
    if q_norm > 0:
        score /= q_norm
    return score


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def _safe_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


_VECTOR_DIMENSION_SQL = text(
    """
    SELECT ((regexp_match(format_type(a.atttypid, a.atttypmod), 'vector\\((\\d+)\\)'))[1])::int
    FROM pg_attribute a
    JOIN pg_class c ON a.attrelid = c.oid
    JOIN pg_namespace n ON c.relnamespace = n.oid
    WHERE c.relname = 'rag_documents_v2'
      AND n.nspname = 'public'
      AND a.attname = 'embedding'
    """
)


def _query_vector_dimension(conn: Any) -> int | None:
    try:
        row = conn.execute(_VECTOR_DIMENSION_SQL).fetchone()
    except Exception:
        return None
    if not row:
        return None
    value = row[0]
    if value in (None, ''):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _detect_postgres_vector_dimension(dsn: str) -> int | None:
    engine = create_engine(dsn, future=True, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            return _query_vector_dimension(conn)
    finally:
        engine.dispose()


def _vector_dim_mismatch_message(*, store_dim: int, vector_dim: int, embedder_dim: int, model_name: str) -> str:
    return (
        f"RAG vector dimension mismatch: pgvector schema expects {store_dim}, "
        f"configured vector dim is {vector_dim}, "
        f"embedder {model_name} produced {embedder_dim}. "
        "Please align RAG_V2_VECTOR_DIM / RAG_EMBEDDING / RAG_HASH_DIM with the existing pgvector schema."
    )


def _resolve_embedder_for_vector_dim(*, expected_dim: int, current: EmbeddingService, allow_auto_switch: bool) -> EmbeddingService:
    if current.dim == expected_dim:
        return current
    if not allow_auto_switch:
        raise ValueError(
            _vector_dim_mismatch_message(
                store_dim=expected_dim,
                vector_dim=current.dim,
                embedder_dim=current.dim,
                model_name=current.model_name,
            )
        )

    candidates: list[EmbeddingService] = [current]
    for backend_name in ("hash", "bge-m3"):
        candidates.append(EmbeddingService(force_backend=backend_name))

    seen: set[tuple[str, int]] = set()
    for candidate in candidates:
        key = (candidate.model_name, int(candidate.dim))
        if key in seen:
            continue
        seen.add(key)
        if candidate.dim == expected_dim:
            if candidate is not current:
                logger.info(
                    "RAG vector dim auto-aligned to existing pgvector dimension=%s via embedder=%s",
                    expected_dim,
                    candidate.model_name,
                )
            return candidate

    raise ValueError(
        _vector_dim_mismatch_message(
            store_dim=expected_dim,
            vector_dim=current.dim,
            embedder_dim=current.dim,
            model_name=current.model_name,
        )
    )




@dataclass(frozen=True)
class RAGDocument:
    collection: str
    scope: str
    source_id: str
    content: str
    title: Optional[str] = None
    url: Optional[str] = None
    source: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)
    expires_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=_utc_now)
    layer: Optional[str] = None
    entity_scope: Optional[str] = None
    entity_key: Optional[str] = None
    ingest_source: Optional[str] = None
    promotion_status: Optional[str] = None
    doc_fingerprint: Optional[str] = None
    parent_collection: Optional[str] = None
    parent_run_id: Optional[str] = None


def _normalized_doc_payload(doc: RAGDocument) -> dict[str, Any]:
    collection = (doc.collection or "").strip()
    details = collection_details(collection)
    metadata = enrich_metadata(
        _safe_metadata(doc.metadata),
        collection=collection,
        layer=doc.layer,
        entity_scope=doc.entity_scope,
        entity_key=doc.entity_key,
        ingest_source=doc.ingest_source,
        promotion_status=doc.promotion_status,
        parent_collection=doc.parent_collection,
        parent_run_id=doc.parent_run_id,
        doc_fingerprint=doc.doc_fingerprint,
    )
    return {
        "collection": collection,
        "layer": str(metadata.get("layer") or details.get("layer") or "unknown"),
        "entity_scope": metadata.get("entity_scope"),
        "entity_key": metadata.get("entity_key"),
        "scope": (doc.scope or "ephemeral").strip() or "ephemeral",
        "source_id": (doc.source_id or "").strip(),
        "content": (doc.content or "").strip(),
        "title": (doc.title or "").strip() or None,
        "url": (doc.url or "").strip() or None,
        "source": (doc.source or "unknown").strip() or "unknown",
        "ingest_source": str(metadata.get("ingest_source") or "").strip() or None,
        "promotion_status": str(metadata.get("promotion_status") or "").strip() or None,
        "doc_fingerprint": str(metadata.get("doc_fingerprint") or "").strip() or None,
        "parent_collection": str(metadata.get("parent_collection") or "").strip() or None,
        "parent_run_id": str(metadata.get("parent_run_id") or "").strip() or None,
        "metadata": metadata,
        "expires_at": doc.expires_at,
        "created_at": doc.created_at,
    }


def _decorate_search_hit(hit: dict[str, Any]) -> dict[str, Any]:
    result = dict(hit or {})
    collection = str(result.get("collection") or "").strip()
    details = collection_details(collection)
    metadata = enrich_metadata(
        _safe_metadata(result.get("metadata")),
        collection=collection,
        layer=result.get("layer"),
        entity_scope=result.get("entity_scope"),
        entity_key=result.get("entity_key"),
        ingest_source=result.get("ingest_source"),
        promotion_status=result.get("promotion_status"),
        parent_collection=result.get("parent_collection"),
        parent_run_id=result.get("parent_run_id"),
        doc_fingerprint=result.get("doc_fingerprint"),
    )
    result["metadata"] = metadata
    result["layer"] = result.get("layer") or metadata.get("layer") or details.get("layer")
    result["collection_kind"] = result.get("collection_kind") or metadata.get("collection_kind") or details.get("collection_kind")
    result["entity_scope"] = result.get("entity_scope") or metadata.get("entity_scope") or details.get("entity_scope")
    result["entity_key"] = result.get("entity_key") or metadata.get("entity_key") or details.get("entity_key")
    result["ingest_source"] = result.get("ingest_source") or metadata.get("ingest_source")
    result["promotion_status"] = result.get("promotion_status") or metadata.get("promotion_status")
    result["doc_fingerprint"] = result.get("doc_fingerprint") or metadata.get("doc_fingerprint")
    result["parent_collection"] = result.get("parent_collection") or metadata.get("parent_collection")
    result["parent_run_id"] = result.get("parent_run_id") or metadata.get("parent_run_id")
    return result


def _search_hit_identity(hit: dict[str, Any]) -> str:
    metadata = _safe_metadata(hit.get("metadata"))
    for candidate in (
        hit.get("doc_fingerprint"),
        metadata.get("doc_fingerprint"),
        hit.get("chunk_id"),
        metadata.get("chunk_id"),
        hit.get("source_doc_id"),
        metadata.get("source_doc_id"),
        hit.get("source_id"),
    ):
        value = str(candidate or "").strip()
        if value:
            return value
    title = str(hit.get("title") or "").strip()
    url = str(hit.get("url") or "").strip()
    content = str(hit.get("content") or "").strip()[:200]
    return f"fallback::{title}::{url}::{content}"


def _sort_search_hits(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated = [_decorate_search_hit(item) for item in list(items or [])]
    return sorted(
        decorated,
        key=lambda item: (
            -float(item.get("rrf_score") or 0.0),
            int(item.get("source_collection_rank") or 999999),
            -float(item.get("dense_score") or 0.0),
            -float(item.get("sparse_score") or 0.0),
        ),
    )


def _merge_search_hits(groups: Iterable[Iterable[dict[str, Any]]], *, top_k: int) -> list[dict[str, Any]]:
    flat_hits = _sort_search_hits([hit for group in groups for hit in (group or [])])
    best_by_identity: dict[str, tuple[float, int, dict[str, Any]]] = {}
    provenance_by_identity: dict[str, dict[str, list[str]]] = {}

    for hit in flat_hits:
        identity = _search_hit_identity(hit)
        score = float(hit.get("rrf_score") or 0.0)
        source_collection_rank = int(hit.get("source_collection_rank") or 999999)
        metadata = _safe_metadata(hit.get("metadata"))
        collection = str(hit.get("collection") or metadata.get("collection") or "").strip()
        layer = str(hit.get("layer") or metadata.get("layer") or collection_details(collection).get("layer") or "unknown").strip().lower() or "unknown"

        provenance = provenance_by_identity.setdefault(identity, {"matched_layers": [], "matched_collections": []})
        if layer and layer not in provenance["matched_layers"]:
            provenance["matched_layers"].append(layer)
        if collection and collection not in provenance["matched_collections"]:
            provenance["matched_collections"].append(collection)

        current = best_by_identity.get(identity)
        if current is None or score > current[0] or (score == current[0] and source_collection_rank < current[1]):
            best_by_identity[identity] = (score, source_collection_rank, hit)

    merged: list[dict[str, Any]] = []
    for identity, (_, _, hit) in best_by_identity.items():
        result = dict(hit)
        metadata = dict(_safe_metadata(result.get("metadata")))
        provenance = provenance_by_identity.get(identity) or {}
        matched_layers = list(provenance.get("matched_layers") or [])
        matched_collections = list(provenance.get("matched_collections") or [])
        if matched_layers:
            result["matched_layers"] = matched_layers
            metadata["matched_layers"] = matched_layers
        if matched_collections:
            result["matched_collections"] = matched_collections
            metadata["matched_collections"] = matched_collections
        result["metadata"] = metadata
        merged.append(result)

    return _sort_search_hits(merged)[: max(1, int(top_k))]

class _InMemoryHybridStore:
    def __init__(self, *, vector_dim: int, rrf_k: int, embedder: EmbeddingService | None = None) -> None:
        self._vector_dim = vector_dim
        self._rrf_k = rrf_k
        self._embedder = embedder or get_embedding_service()
        self._lock = threading.Lock()
        self._docs: dict[tuple[str, str], dict[str, Any]] = {}

    def ingest_documents(self, docs: Iterable[RAGDocument]) -> dict[str, Any]:
        indexed = 0
        skipped = 0
        pending: list[tuple[tuple[str, str], dict[str, Any], str]] = []
        for doc in docs:
            if not isinstance(doc, RAGDocument):
                skipped += 1
                continue
            payload = _normalized_doc_payload(doc)
            collection = payload["collection"]
            source_id = payload["source_id"]
            content = payload["content"]
            if not collection or not source_id or not content:
                skipped += 1
                continue
            key = (collection, source_id)
            pending.append((key, payload, content))

        if pending:
            contents = [item[2] for item in pending]
            embed_result = self._embedder.encode(contents)
            with self._lock:
                for index, (key, payload, _content) in enumerate(pending):
                    payload["embedding"] = embed_result.dense[index]
                    payload["sparse"] = embed_result.sparse[index]
                    self._docs[key] = payload
                    indexed += 1

        return {"indexed": indexed, "skipped": skipped}

    def _active_docs(self, *, collection: str, now: datetime) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        with self._lock:
            for payload in self._docs.values():
                if payload.get("collection") != collection:
                    continue
                expires_at = payload.get("expires_at")
                if isinstance(expires_at, datetime) and expires_at <= now:
                    continue
                docs.append(payload)
        return docs

    def hybrid_search(self, query: str, *, collection: str, top_k: int) -> list[dict[str, Any]]:
        query_text = (query or "").strip()
        if not query_text:
            return []
        now = _utc_now()
        docs = self._active_docs(collection=collection, now=now)
        if not docs:
            return []

        q_dense, q_sparse = _embed_text(query_text, self._embedder)

        dense_scored: list[tuple[str, float]] = []
        sparse_scored: list[tuple[str, float]] = []
        by_source: dict[str, dict[str, Any]] = {}
        for payload in docs:
            source_id = payload["source_id"]
            by_source[source_id] = payload
            dense_scored.append((source_id, _cosine(q_dense, payload["embedding"])))
            doc_sparse = payload.get("sparse", SparseVector())
            sparse_scored.append((source_id, _sparse_score(q_sparse, doc_sparse)))

        dense_sorted = sorted(dense_scored, key=lambda item: item[1], reverse=True)
        sparse_sorted = sorted(sparse_scored, key=lambda item: item[1], reverse=True)

        dense_rank = {sid: rank + 1 for rank, (sid, _score) in enumerate(dense_sorted)}
        sparse_rank = {sid: rank + 1 for rank, (sid, score) in enumerate(sparse_sorted) if score > 0}
        dense_score_map = dict(dense_scored)
        sparse_score_map = dict(sparse_scored)

        scope_boost: dict[str, float] = {
            "persistent": 0.15,
            "medium_ttl": 0.05,
            "ephemeral": 0.0,
        }

        fused: list[dict[str, Any]] = []
        for sid, payload in by_source.items():
            d_rank = dense_rank.get(sid)
            s_rank = sparse_rank.get(sid)
            rrf = 0.0
            if d_rank is not None:
                rrf += 1.0 / (self._rrf_k + d_rank)
            if s_rank is not None:
                rrf += 1.0 / (self._rrf_k + s_rank)
            scope = payload.get("scope", "ephemeral")
            rrf += scope_boost.get(scope, 0.0)
            fused.append(
                {
                    "source_id": sid,
                    "collection": payload["collection"],
                    "layer": payload.get("layer"),
                    "entity_scope": payload.get("entity_scope"),
                    "entity_key": payload.get("entity_key"),
                    "scope": scope,
                    "title": payload.get("title"),
                    "url": payload.get("url"),
                    "source": payload.get("source"),
                    "ingest_source": payload.get("ingest_source"),
                    "promotion_status": payload.get("promotion_status"),
                    "doc_fingerprint": payload.get("doc_fingerprint"),
                    "parent_collection": payload.get("parent_collection"),
                    "parent_run_id": payload.get("parent_run_id"),
                    "content": payload.get("content"),
                    "metadata": payload.get("metadata") or {},
                    "created_at": payload.get("created_at"),
                    "expires_at": payload.get("expires_at"),
                    "dense_score": dense_score_map.get(sid, 0.0),
                    "sparse_score": sparse_score_map.get(sid, 0.0),
                    "dense_rank": d_rank,
                    "sparse_rank": s_rank,
                    "rrf_score": rrf,
                }
            )

        return _sort_search_hits(fused)[: max(1, int(top_k))]

    def hybrid_search_many(self, query: str, *, collections: Iterable[str], top_k: int) -> list[dict[str, Any]]:
        normalized = _normalize_collections(collections)
        if not normalized:
            return []
        groups = _search_many_bounded(
            self.hybrid_search,
            query,
            collections=normalized,
            top_k=max(1, int(top_k)),
        )
        return _merge_search_hits(groups, top_k=max(1, int(top_k)))

    def delete_collections(self, *, collections: Iterable[str]) -> int:
        normalized = set(_normalize_collections(collections))
        if not normalized:
            return 0
        with self._lock:
            keys = [key for key in self._docs if key[0] in normalized]
            for key in keys:
                self._docs.pop(key, None)
        return len(keys)

    def cleanup_expired(self) -> int:
        now = _utc_now()
        to_delete: list[tuple[str, str]] = []
        with self._lock:
            for key, payload in self._docs.items():
                expires_at = payload.get("expires_at")
                if isinstance(expires_at, datetime) and expires_at <= now:
                    to_delete.append(key)
            for key in to_delete:
                self._docs.pop(key, None)
        return len(to_delete)

    def count_documents(self) -> int:
        now = _utc_now()
        with self._lock:
            return sum(
                1
                for payload in self._docs.values()
                if not (isinstance(payload.get("expires_at"), datetime) and payload.get("expires_at") <= now)
            )

    def cleanup_stale_filings(self, *, older_than_days: int = 365) -> int:
        threshold = _utc_now() - timedelta(days=max(1, int(older_than_days)))
        to_delete: list[tuple[str, str]] = []
        with self._lock:
            for key, payload in self._docs.items():
                metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
                doc_type = str(metadata.get("type") or "").strip().lower()
                created_at = payload.get("created_at")
                if doc_type in {"filing", "research_doc"} and isinstance(created_at, datetime) and created_at <= threshold:
                    to_delete.append(key)
            for key in to_delete:
                self._docs.pop(key, None)
        return len(to_delete)


class _PostgresHybridStore:
    def __init__(self, *, dsn: str, vector_dim: int, rrf_k: int, embedder: EmbeddingService | None = None) -> None:
        self._dsn = dsn
        self._vector_dim = vector_dim
        self._rrf_k = rrf_k
        self._embedder = embedder or get_embedding_service()
        self._engine = create_engine(dsn, future=True, pool_pre_ping=True)
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self._existing_vector_dim: int | None = None
        try:
            with self._engine.connect() as conn:
                self._existing_vector_dim = self._check_vector_dimension(conn)
        except Exception:
            self._existing_vector_dim = None
        if self._existing_vector_dim is not None and int(self._existing_vector_dim) != int(self._vector_dim):
            raise ValueError(
                _vector_dim_mismatch_message(
                    store_dim=int(self._existing_vector_dim),
                    vector_dim=int(self._vector_dim),
                    embedder_dim=int(self._embedder.dim),
                    model_name=self._embedder.model_name,
                )
            )
    @staticmethod
    def _has_vector_type(conn: Any) -> bool:
        try:
            value = conn.execute(text("SELECT to_regtype('vector') IS NOT NULL")).scalar()
        except Exception:
            return False
        return bool(value)

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._engine.begin() as conn:
                if _env_bool("RAG_V2_RESET", False):
                    conn.execute(text("DROP TABLE IF EXISTS rag_documents_v2 CASCADE"))

                conn.execute(
                    text(
                        f"""
                        CREATE TABLE IF NOT EXISTS rag_documents_v2 (
                            id BIGSERIAL PRIMARY KEY,
                            collection TEXT NOT NULL,
                            layer TEXT NULL,
                            entity_scope TEXT NULL,
                            entity_key TEXT NULL,
                            scope TEXT NOT NULL,
                            source_id TEXT NOT NULL,
                            content TEXT NOT NULL,
                            title TEXT NULL,
                            url TEXT NULL,
                            source TEXT NULL,
                            ingest_source TEXT NULL,
                            promotion_status TEXT NULL,
                            doc_fingerprint TEXT NULL,
                            parent_collection TEXT NULL,
                            parent_run_id TEXT NULL,
                            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                            embedding VECTOR({self._vector_dim}) NOT NULL,
                            search_vector tsvector,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            expires_at TIMESTAMPTZ NULL,
                            UNIQUE(collection, source_id)
                        )
                        """
                    )
                )
                for ddl in (
                    "ALTER TABLE rag_documents_v2 ADD COLUMN IF NOT EXISTS layer TEXT NULL",
                    "ALTER TABLE rag_documents_v2 ADD COLUMN IF NOT EXISTS entity_scope TEXT NULL",
                    "ALTER TABLE rag_documents_v2 ADD COLUMN IF NOT EXISTS entity_key TEXT NULL",
                    "ALTER TABLE rag_documents_v2 ADD COLUMN IF NOT EXISTS ingest_source TEXT NULL",
                    "ALTER TABLE rag_documents_v2 ADD COLUMN IF NOT EXISTS promotion_status TEXT NULL",
                    "ALTER TABLE rag_documents_v2 ADD COLUMN IF NOT EXISTS doc_fingerprint TEXT NULL",
                    "ALTER TABLE rag_documents_v2 ADD COLUMN IF NOT EXISTS parent_collection TEXT NULL",
                    "ALTER TABLE rag_documents_v2 ADD COLUMN IF NOT EXISTS parent_run_id TEXT NULL",
                ):
                    conn.execute(text(ddl))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_collection ON rag_documents_v2(collection)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_layer ON rag_documents_v2(layer)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_scope ON rag_documents_v2(scope)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_entity_scope ON rag_documents_v2(entity_scope)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_entity_key ON rag_documents_v2(entity_key)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_doc_fingerprint ON rag_documents_v2(doc_fingerprint)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_expires_at ON rag_documents_v2(expires_at)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_search_vector ON rag_documents_v2 USING GIN(search_vector)"))
                try:
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS idx_rag_v2_embedding "
                            "ON rag_documents_v2 USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
                        )
                    )
                except Exception as exc:  # pragma: no cover - depends on pgvector runtime config
                    logger.warning("RAG v2 ivfflat index skipped: %s", exc)
            self._schema_ready = True

    @staticmethod
    def _check_vector_dimension(conn: Any) -> int | None:
        return _query_vector_dimension(conn)

    def _validate_embedding_dim(self, actual_dim: int, *, operation: str) -> None:
        normalized = int(actual_dim)
        if normalized != self._vector_dim:
            raise ValueError(
                f"{operation}: "
                + _vector_dim_mismatch_message(
                    store_dim=self._vector_dim,
                    vector_dim=self._vector_dim,
                    embedder_dim=normalized,
                    model_name=self._embedder.model_name,
                )
            )
    def ingest_documents(self, docs: Iterable[RAGDocument]) -> dict[str, Any]:
        self._ensure_schema()
        indexed = 0
        skipped = 0
        sql = text(
            """
            INSERT INTO rag_documents_v2 (
                collection, layer, entity_scope, entity_key, scope, source_id, content, title, url, source,
                ingest_source, promotion_status, doc_fingerprint, parent_collection, parent_run_id, metadata,
                embedding, search_vector, created_at, expires_at
            ) VALUES (
                :collection, :layer, :entity_scope, :entity_key, :scope, :source_id, :content, :title, :url, :source,
                :ingest_source, :promotion_status, :doc_fingerprint, :parent_collection, :parent_run_id, CAST(:metadata AS jsonb),
                CAST(:embedding AS vector), to_tsvector('simple', :content), :created_at, :expires_at
            )
            ON CONFLICT (collection, source_id)
            DO UPDATE SET
                layer = EXCLUDED.layer,
                entity_scope = EXCLUDED.entity_scope,
                entity_key = EXCLUDED.entity_key,
                scope = EXCLUDED.scope,
                content = EXCLUDED.content,
                title = EXCLUDED.title,
                url = EXCLUDED.url,
                source = EXCLUDED.source,
                ingest_source = EXCLUDED.ingest_source,
                promotion_status = EXCLUDED.promotion_status,
                doc_fingerprint = EXCLUDED.doc_fingerprint,
                parent_collection = EXCLUDED.parent_collection,
                parent_run_id = EXCLUDED.parent_run_id,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding,
                search_vector = EXCLUDED.search_vector,
                created_at = EXCLUDED.created_at,
                expires_at = EXCLUDED.expires_at
            """
        )
        pending: list[dict[str, Any]] = []
        for doc in docs:
            if not isinstance(doc, RAGDocument):
                skipped += 1
                continue
            payload = _normalized_doc_payload(doc)
            if not payload["collection"] or not payload["source_id"] or not payload["content"]:
                skipped += 1
                continue
            pending.append(payload)

        if pending:
            contents = [payload["content"] for payload in pending]
            embed_result = self._embedder.encode(contents)
            if int(embed_result.dim or 0) != int(self._vector_dim):
                raise ValueError(
                    _vector_dim_mismatch_message(
                        store_dim=int(self._vector_dim),
                        vector_dim=int(self._vector_dim),
                        embedder_dim=int(embed_result.dim or 0),
                        model_name=str(embed_result.model_name or self._embedder.model_name),
                    )
                )
            with self._engine.begin() as conn:
                for index, payload in enumerate(pending):
                    conn.execute(
                        sql,
                        {
                            "collection": payload["collection"],
                            "layer": payload["layer"],
                            "entity_scope": payload["entity_scope"],
                            "entity_key": payload["entity_key"],
                            "scope": payload["scope"],
                            "source_id": payload["source_id"],
                            "content": payload["content"],
                            "title": payload["title"],
                            "url": payload["url"],
                            "source": payload["source"],
                            "ingest_source": payload["ingest_source"],
                            "promotion_status": payload["promotion_status"],
                            "doc_fingerprint": payload["doc_fingerprint"],
                            "parent_collection": payload["parent_collection"],
                            "parent_run_id": payload["parent_run_id"],
                            "metadata": json.dumps(payload["metadata"], ensure_ascii=False),
                            "embedding": _vector_literal(embed_result.dense[index]),
                            "created_at": payload["created_at"],
                            "expires_at": payload["expires_at"],
                        },
                    )
                    indexed += 1
        return {"indexed": indexed, "skipped": skipped}

    def hybrid_search(self, query: str, *, collection: str, top_k: int) -> list[dict[str, Any]]:
        self._ensure_schema()
        query_text = (query or "").strip()
        if not query_text:
            return []
        q_dense, _q_sparse = _embed_text(query_text, self._embedder)
        if len(q_dense) != int(self._vector_dim):
            raise ValueError(
                _vector_dim_mismatch_message(
                    store_dim=int(self._vector_dim),
                    vector_dim=int(self._vector_dim),
                    embedder_dim=len(q_dense),
                    model_name=self._embedder.model_name,
                )
            )
        q_emb = _vector_literal(q_dense)
        candidate_k = max(12, int(top_k) * 4)
        scope_boost_persistent = 0.15
        scope_boost_medium = 0.05
        sql = text(
            """
            WITH live_docs AS (
                SELECT *
                FROM rag_documents_v2
                WHERE collection = :collection
                  AND (expires_at IS NULL OR expires_at > now())
            ),
            dense AS (
                SELECT
                    source_id,
                    row_number() OVER (ORDER BY embedding <=> CAST(:query_embedding AS vector)) AS dense_rank,
                    1 - (embedding <=> CAST(:query_embedding AS vector)) AS dense_score
                FROM live_docs
                ORDER BY embedding <=> CAST(:query_embedding AS vector)
                LIMIT :candidate_k
            ),
            sparse AS (
                SELECT
                    source_id,
                    row_number() OVER (
                        ORDER BY ts_rank_cd(search_vector, plainto_tsquery('simple', :query)) DESC
                    ) AS sparse_rank,
                    ts_rank_cd(search_vector, plainto_tsquery('simple', :query)) AS sparse_score
                FROM live_docs
                WHERE search_vector @@ plainto_tsquery('simple', :query)
                ORDER BY sparse_score DESC
                LIMIT :candidate_k
            ),
            ids AS (
                SELECT source_id FROM dense
                UNION
                SELECT source_id FROM sparse
            )
            SELECT
                d.collection,
                d.layer,
                d.entity_scope,
                d.entity_key,
                d.scope,
                d.source_id,
                d.title,
                d.url,
                d.source,
                d.ingest_source,
                d.promotion_status,
                d.doc_fingerprint,
                d.parent_collection,
                d.parent_run_id,
                d.content,
                d.metadata,
                d.created_at,
                d.expires_at,
                dense.dense_rank,
                dense.dense_score,
                sparse.sparse_rank,
                sparse.sparse_score,
                COALESCE(1.0 / (:rrf_k + dense.dense_rank), 0)
                + COALESCE(1.0 / (:rrf_k + sparse.sparse_rank), 0)
                + CASE
                    WHEN d.scope = 'persistent' THEN :scope_boost_persistent
                    WHEN d.scope = 'medium_ttl' THEN :scope_boost_medium
                    ELSE 0
                  END AS rrf_score
            FROM ids
            JOIN live_docs d USING (source_id)
            LEFT JOIN dense USING (source_id)
            LEFT JOIN sparse USING (source_id)
            ORDER BY rrf_score DESC, dense_score DESC NULLS LAST, sparse_score DESC NULLS LAST
            LIMIT :top_k
            """
        )
        with self._engine.connect() as conn:
            rows = conn.execute(
                sql,
                {
                    "collection": collection,
                    "query": query_text,
                    "query_embedding": q_emb,
                    "candidate_k": candidate_k,
                    "top_k": max(1, int(top_k)),
                    "rrf_k": self._rrf_k,
                    "scope_boost_persistent": scope_boost_persistent,
                    "scope_boost_medium": scope_boost_medium,
                },
            ).mappings()

            hits: list[dict[str, Any]] = []
            for row in rows:
                metadata = row.get("metadata")
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except Exception:
                        metadata = {}
                elif not isinstance(metadata, dict):
                    metadata = {}
                hits.append(
                    {
                        "collection": row.get("collection"),
                        "layer": row.get("layer") or metadata.get("layer"),
                        "entity_scope": row.get("entity_scope") or metadata.get("entity_scope"),
                        "entity_key": row.get("entity_key") or metadata.get("entity_key"),
                        "scope": row.get("scope"),
                        "source_id": row.get("source_id"),
                        "title": row.get("title"),
                        "url": row.get("url"),
                        "source": row.get("source"),
                        "ingest_source": row.get("ingest_source") or metadata.get("ingest_source"),
                        "promotion_status": row.get("promotion_status") or metadata.get("promotion_status"),
                        "doc_fingerprint": row.get("doc_fingerprint") or metadata.get("doc_fingerprint"),
                        "parent_collection": row.get("parent_collection") or metadata.get("parent_collection"),
                        "parent_run_id": row.get("parent_run_id") or metadata.get("parent_run_id"),
                        "content": row.get("content"),
                        "metadata": metadata,
                        "created_at": row.get("created_at"),
                        "expires_at": row.get("expires_at"),
                        "dense_rank": row.get("dense_rank"),
                        "dense_score": float(row.get("dense_score") or 0.0),
                        "sparse_rank": row.get("sparse_rank"),
                        "sparse_score": float(row.get("sparse_score") or 0.0),
                        "rrf_score": float(row.get("rrf_score") or 0.0),
                    }
                )
            return hits

    def hybrid_search_many(self, query: str, *, collections: Iterable[str], top_k: int) -> list[dict[str, Any]]:
        normalized = _normalize_collections(collections)
        if not normalized:
            return []
        groups = _search_many_bounded(
            self.hybrid_search,
            query,
            collections=normalized,
            top_k=max(1, int(top_k)),
        )
        return _merge_search_hits(groups, top_k=max(1, int(top_k)))

    def cleanup_expired(self) -> int:
        self._ensure_schema()
        sql = text("DELETE FROM rag_documents_v2 WHERE expires_at IS NOT NULL AND expires_at <= now()")
        with self._engine.begin() as conn:
            result = conn.execute(sql)
        return int(result.rowcount or 0)

    def delete_collections(self, *, collections: Iterable[str]) -> int:
        normalized = _normalize_collections(collections)
        if not normalized:
            return 0
        self._ensure_schema()
        deleted = 0
        with self._engine.begin() as conn:
            for collection in normalized:
                result = conn.execute(
                    text("DELETE FROM rag_documents_v2 WHERE collection = :collection"),
                    {"collection": collection},
                )
                deleted += int(result.rowcount or 0)
        return deleted

    def count_documents(self) -> int:
        self._ensure_schema()
        sql = text(
            """
            SELECT COUNT(1)
            FROM rag_documents_v2
            WHERE expires_at IS NULL OR expires_at > now()
            """
        )
        with self._engine.connect() as conn:
            value = conn.execute(sql).scalar() or 0
        return int(value)

    def cleanup_stale_filings(self, *, older_than_days: int = 365) -> int:
        self._ensure_schema()
        sql = text(
            """
            DELETE FROM rag_documents_v2
            WHERE created_at <= (now() - make_interval(days => :older_than_days))
              AND lower(COALESCE(metadata->>'type', '')) IN ('filing', 'research_doc')
            """
        )
        with self._engine.begin() as conn:
            result = conn.execute(sql, {"older_than_days": max(1, int(older_than_days))})
        return int(result.rowcount or 0)


class HybridRAGService:
    def __init__(
        self,
        *,
        backend: str,
        vector_dim: int,
        rrf_k: int,
        postgres_dsn: Optional[str] = None,
        allow_memory_fallback: bool = True,
        embedder: EmbeddingService | None = None,
    ) -> None:
        backend_norm = (backend or "auto").strip().lower()
        dsn = (postgres_dsn or "").strip()
        wants_postgres = backend_norm == "postgres" or (backend_norm == "auto" and bool(dsn))

        requested_embedder = embedder or get_embedding_service()
        explicit_vector_dim = vector_dim > 0
        explicit_embedding_backend = embedder is not None or bool(str(os.getenv("RAG_EMBEDDING", "")).strip())
        existing_vector_dim = _detect_postgres_vector_dimension(dsn) if wants_postgres and dsn else None
        resolved_embedder = requested_embedder
        if existing_vector_dim is not None:
            resolved_embedder = _resolve_embedder_for_vector_dim(
                expected_dim=int(existing_vector_dim),
                current=requested_embedder,
                allow_auto_switch=not explicit_embedding_backend,
            )

        effective_dim = resolved_embedder.dim if vector_dim <= 0 else max(16, int(vector_dim))
        if existing_vector_dim is not None:
            if explicit_vector_dim and int(effective_dim) != int(existing_vector_dim):
                raise ValueError(
                    _vector_dim_mismatch_message(
                        store_dim=int(existing_vector_dim),
                        vector_dim=int(effective_dim),
                        embedder_dim=int(resolved_embedder.dim),
                        model_name=resolved_embedder.model_name,
                    )
                )
            effective_dim = int(existing_vector_dim)
        elif wants_postgres and explicit_vector_dim and int(resolved_embedder.dim) != int(effective_dim):
            raise ValueError(
                _vector_dim_mismatch_message(
                    store_dim=int(effective_dim),
                    vector_dim=int(effective_dim),
                    embedder_dim=int(resolved_embedder.dim),
                    model_name=resolved_embedder.model_name,
                )
            )

        self._embedder = resolved_embedder
        self.vector_dim = int(effective_dim)
        self.rrf_k = max(1, int(rrf_k))
        self.backend_name = "memory"
        self.embedding_model = self._embedder.model_name
        self.fallback_reason: Optional[str] = None

        if backend_norm == "memory":
            self._store = _InMemoryHybridStore(vector_dim=self.vector_dim, rrf_k=self.rrf_k, embedder=self._embedder)
            self.backend_name = "memory"
            return

        if backend_norm == "postgres" and not dsn:
            message = "postgres backend requested but no DSN configured"
            if not allow_memory_fallback:
                raise ValueError(message)
            self.fallback_reason = message
            _log_backend_fallback(
                reason="postgres_dsn_missing",
                detail=message,
                backend_requested=backend_norm,
            )
            self._store = _InMemoryHybridStore(vector_dim=self.vector_dim, rrf_k=self.rrf_k, embedder=self._embedder)
            self.backend_name = "memory"
            return

        if wants_postgres and dsn:
            try:
                self._store = _PostgresHybridStore(dsn=dsn, vector_dim=self.vector_dim, rrf_k=self.rrf_k, embedder=self._embedder)
                self.backend_name = "postgres"
                return
            except Exception as exc:
                if not allow_memory_fallback:
                    raise
                self.fallback_reason = str(exc)
                _log_backend_fallback(
                    reason="postgres_init_failed",
                    detail=str(exc),
                    backend_requested=backend_norm,
                )

        self._store = _InMemoryHybridStore(vector_dim=self.vector_dim, rrf_k=self.rrf_k, embedder=self._embedder)
        self.backend_name = "memory"
        if wants_postgres and self.fallback_reason is None:
            _log_backend_fallback(
                reason="postgres_unavailable_use_memory",
                backend_requested=backend_norm,
            )
    @classmethod
    def from_env(cls) -> "HybridRAGService":
        backend = os.getenv("RAG_V2_BACKEND", "auto")
        # Default to 0 = "auto-detect from embedder"
        raw_dim = os.getenv("RAG_V2_VECTOR_DIM", "").strip()
        vector_dim = int(raw_dim) if raw_dim else 0
        rrf_k = int((os.getenv("RAG_V2_RRF_K") or "60").strip())
        postgres_dsn = (os.getenv("RAG_V2_POSTGRES_DSN") or os.getenv("LANGGRAPH_CHECKPOINT_POSTGRES_DSN") or "").strip()
        allow_fallback = _env_bool("RAG_V2_ALLOW_MEMORY_FALLBACK", True)
        return cls(
            backend=backend,
            vector_dim=vector_dim,
            rrf_k=rrf_k,
            postgres_dsn=postgres_dsn or None,
            allow_memory_fallback=allow_fallback,
        )

    @classmethod
    def for_testing(cls, *, backend: str = "memory") -> "HybridRAGService":
        # Force hash backend for fast, deterministic tests
        embedder = EmbeddingService(force_backend="hash")
        return cls(
            backend=backend,
            vector_dim=0,  # auto from embedder
            rrf_k=40,
            postgres_dsn=None,
            allow_memory_fallback=True,
            embedder=embedder,
        )

    def ingest_documents(self, docs: Iterable[RAGDocument]) -> dict[str, Any]:
        return self._store.ingest_documents(docs)

    def hybrid_search(self, query: str, *, collection: str, top_k: int = 6) -> list[dict[str, Any]]:
        hits = self._store.hybrid_search(query, collection=collection, top_k=max(1, int(top_k)))
        return [_decorate_search_hit(hit) for hit in list(hits or [])]

    def hybrid_search_many(self, query: str, *, collections: Iterable[str], top_k: int = 6) -> list[dict[str, Any]]:
        normalized_collections = _normalize_collections(collections)
        if not normalized_collections:
            return []
        candidate_k = max(1, int(top_k)) * 2
        groups = _search_many_bounded(
            self.hybrid_search,
            query,
            collections=normalized_collections,
            top_k=candidate_k,
        )
        return _merge_search_hits(groups, top_k=max(1, int(top_k)))

    def cleanup_expired(self) -> int:
        return self._store.cleanup_expired()

    def count_documents(self) -> int:
        count_fn = getattr(self._store, "count_documents", None)
        if callable(count_fn):
            return int(count_fn())
        return 0

    def cleanup_stale_filings(self, *, older_than_days: int = 365) -> int:
        cleanup_fn = getattr(self._store, "cleanup_stale_filings", None)
        if callable(cleanup_fn):
            return int(cleanup_fn(older_than_days=older_than_days))
        return 0

    def delete_collections(self, *, collections: Iterable[str]) -> int:
        delete_fn = getattr(self._store, "delete_collections", None)
        if callable(delete_fn):
            return int(delete_fn(collections=collections))
        return 0


_service_singleton: Optional[HybridRAGService] = None
_service_lock = threading.Lock()


def get_rag_service() -> HybridRAGService:
    global _service_singleton
    if _service_singleton is not None:
        return _service_singleton
    with _service_lock:
        if _service_singleton is None:
            _service_singleton = HybridRAGService.from_env()
    return _service_singleton


def reset_rag_service_cache() -> None:
    global _service_singleton
    with _service_lock:
        _service_singleton = None


__all__ = [
    "RAGDocument",
    "HybridRAGService",
    "get_rag_service",
    "reset_rag_service_cache",
]
