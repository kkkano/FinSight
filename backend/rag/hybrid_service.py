# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import create_engine, text

from backend.rag.embedder import (
    EmbeddingService,
    SparseVector,
    get_embedding_service,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


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
        # Collect valid docs for batch embedding
        pending: list[tuple[tuple[str, str], dict[str, Any], str]] = []
        for doc in docs:
            if not isinstance(doc, RAGDocument):
                skipped += 1
                continue
            collection = (doc.collection or "").strip()
            source_id = (doc.source_id or "").strip()
            content = (doc.content or "").strip()
            if not collection or not source_id or not content:
                skipped += 1
                continue

            key = (collection, source_id)
            payload = {
                "collection": collection,
                "scope": (doc.scope or "ephemeral").strip() or "ephemeral",
                "source_id": source_id,
                "content": content,
                "title": (doc.title or "").strip() or None,
                "url": (doc.url or "").strip() or None,
                "source": (doc.source or "unknown").strip() or "unknown",
                "metadata": _safe_metadata(doc.metadata),
                "expires_at": doc.expires_at,
                "created_at": doc.created_at,
            }
            pending.append((key, payload, content))

        if pending:
            # Batch encode all contents
            contents = [p[2] for p in pending]
            embed_result = self._embedder.encode(contents)

            with self._lock:
                for i, (key, payload, _content) in enumerate(pending):
                    payload["embedding"] = embed_result.dense[i]
                    payload["sparse"] = embed_result.sparse[i]
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
        for d in docs:
            source_id = d["source_id"]
            by_source[source_id] = d
            dense_scored.append((source_id, _cosine(q_dense, d["embedding"])))
            doc_sparse = d.get("sparse", SparseVector())
            sparse_scored.append((source_id, _sparse_score(q_sparse, doc_sparse)))

        dense_sorted = sorted(dense_scored, key=lambda x: x[1], reverse=True)
        sparse_sorted = sorted(sparse_scored, key=lambda x: x[1], reverse=True)

        dense_rank = {sid: rank + 1 for rank, (sid, _) in enumerate(dense_sorted)}
        sparse_rank = {sid: rank + 1 for rank, (sid, _) in enumerate(sparse_sorted) if _ > 0}
        dense_score_map = dict(dense_scored)
        sparse_score_map = dict(sparse_scored)

        # RRF fusion with scope boost (E5)
        _SCOPE_BOOST: dict[str, float] = {
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
            # Apply scope boost
            scope = payload.get("scope", "ephemeral")
            rrf += _SCOPE_BOOST.get(scope, 0.0)

            fused.append(
                {
                    "source_id": sid,
                    "collection": payload["collection"],
                    "scope": scope,
                    "title": payload.get("title"),
                    "url": payload.get("url"),
                    "source": payload.get("source"),
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

        fused_sorted = sorted(
            fused,
            key=lambda x: (
                float(x.get("rrf_score") or 0.0),
                float(x.get("dense_score") or 0.0),
                float(x.get("sparse_score") or 0.0),
            ),
            reverse=True,
        )
        return fused_sorted[: max(1, int(top_k))]

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


class _PostgresHybridStore:
    def __init__(self, *, dsn: str, vector_dim: int, rrf_k: int, embedder: EmbeddingService | None = None) -> None:
        self._dsn = dsn
        self._vector_dim = vector_dim
        self._rrf_k = rrf_k
        self._embedder = embedder or get_embedding_service()
        self._engine = create_engine(dsn, future=True, pool_pre_ping=True)
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

                # E6: Check existing table dimension and migrate if needed
                existing_dim = self._check_vector_dimension(conn)
                if existing_dim is not None and existing_dim != self._vector_dim:
                    logger.warning(
                        "RAG v2 vector dimension mismatch: table has %d, need %d. "
                        "Dropping and recreating table (all embeddings will be re-generated).",
                        existing_dim, self._vector_dim,
                    )
                    conn.execute(text("DROP TABLE IF EXISTS rag_documents_v2 CASCADE"))

                conn.execute(
                    text(
                        f"""
                        CREATE TABLE IF NOT EXISTS rag_documents_v2 (
                            id BIGSERIAL PRIMARY KEY,
                            collection TEXT NOT NULL,
                            scope TEXT NOT NULL,
                            source_id TEXT NOT NULL,
                            content TEXT NOT NULL,
                            title TEXT NULL,
                            url TEXT NULL,
                            source TEXT NULL,
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
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_collection ON rag_documents_v2(collection)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_scope ON rag_documents_v2(scope)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_expires_at ON rag_documents_v2(expires_at)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_v2_search_vector ON rag_documents_v2 USING GIN(search_vector)"))
                # Optional ANN index. If not supported by current pgvector settings, keep running.
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
        """Query existing embedding column dimension, return None if table doesn't exist."""
        try:
            row = conn.execute(
                text(
                    """
                    SELECT atttypmod
                    FROM pg_attribute
                    WHERE attrelid = 'rag_documents_v2'::regclass
                      AND attname = 'embedding'
                    """
                )
            ).fetchone()
            if row and row[0]:
                return int(row[0])
        except Exception:
            pass
        return None

    def ingest_documents(self, docs: Iterable[RAGDocument]) -> dict[str, Any]:
        self._ensure_schema()
        indexed = 0
        skipped = 0
        sql = text(
            """
            INSERT INTO rag_documents_v2 (
                collection, scope, source_id, content, title, url, source, metadata,
                embedding, search_vector, created_at, expires_at
            ) VALUES (
                :collection, :scope, :source_id, :content, :title, :url, :source, CAST(:metadata AS jsonb),
                CAST(:embedding AS vector), to_tsvector('simple', :content), :created_at, :expires_at
            )
            ON CONFLICT (collection, source_id)
            DO UPDATE SET
                scope = EXCLUDED.scope,
                content = EXCLUDED.content,
                title = EXCLUDED.title,
                url = EXCLUDED.url,
                source = EXCLUDED.source,
                metadata = EXCLUDED.metadata,
                embedding = EXCLUDED.embedding,
                search_vector = EXCLUDED.search_vector,
                created_at = EXCLUDED.created_at,
                expires_at = EXCLUDED.expires_at
            """
        )
        # Collect valid docs for batch embedding
        pending: list[tuple[RAGDocument, str]] = []
        for doc in docs:
            if not isinstance(doc, RAGDocument):
                skipped += 1
                continue
            content = (doc.content or "").strip()
            collection = (doc.collection or "").strip()
            source_id = (doc.source_id or "").strip()
            if not collection or not source_id or not content:
                skipped += 1
                continue
            pending.append((doc, content))

        if pending:
            contents = [p[1] for p in pending]
            embed_result = self._embedder.encode(contents)
            with self._engine.begin() as conn:
                for i, (doc, content) in enumerate(pending):
                    embedding = embed_result.dense[i]
                    conn.execute(
                        sql,
                        {
                            "collection": (doc.collection or "").strip(),
                            "scope": (doc.scope or "ephemeral").strip() or "ephemeral",
                            "source_id": (doc.source_id or "").strip(),
                            "content": content,
                            "title": (doc.title or "").strip() or None,
                            "url": (doc.url or "").strip() or None,
                            "source": (doc.source or "unknown").strip() or "unknown",
                            "metadata": json.dumps(_safe_metadata(doc.metadata), ensure_ascii=False),
                            "embedding": _vector_literal(embedding),
                            "created_at": doc.created_at,
                            "expires_at": doc.expires_at,
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
        q_emb = _vector_literal(q_dense)
        candidate_k = max(12, int(top_k) * 4)
        # Scope boost constants for RRF
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
                d.scope,
                d.source_id,
                d.title,
                d.url,
                d.source,
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
                        "scope": row.get("scope"),
                        "source_id": row.get("source_id"),
                        "title": row.get("title"),
                        "url": row.get("url"),
                        "source": row.get("source"),
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

    def cleanup_expired(self) -> int:
        self._ensure_schema()
        sql = text("DELETE FROM rag_documents_v2 WHERE expires_at IS NOT NULL AND expires_at <= now()")
        with self._engine.begin() as conn:
            result = conn.execute(sql)
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
        self._embedder = embedder or get_embedding_service()
        # Use embedder's native dim when available; env override still honoured
        effective_dim = self._embedder.dim if vector_dim <= 0 else max(16, int(vector_dim))
        self.vector_dim = effective_dim
        self.rrf_k = max(1, int(rrf_k))
        self.backend_name = "memory"
        self.embedding_model = self._embedder.model_name
        self.fallback_reason: Optional[str] = None
        backend_norm = (backend or "auto").strip().lower()

        if backend_norm == "memory":
            self._store = _InMemoryHybridStore(vector_dim=self.vector_dim, rrf_k=self.rrf_k, embedder=self._embedder)
            self.backend_name = "memory"
            return

        dsn = (postgres_dsn or "").strip()
        wants_postgres = backend_norm == "postgres" or (backend_norm == "auto" and bool(dsn))
        if wants_postgres and dsn:
            try:
                self._store = _PostgresHybridStore(dsn=dsn, vector_dim=self.vector_dim, rrf_k=self.rrf_k, embedder=self._embedder)
                self.backend_name = "postgres"
                return
            except Exception as exc:
                if not allow_memory_fallback:
                    raise
                self.fallback_reason = str(exc)
                logger.warning("RAG v2 fallback to memory backend: %s", exc)

        self._store = _InMemoryHybridStore(vector_dim=self.vector_dim, rrf_k=self.rrf_k, embedder=self._embedder)
        self.backend_name = "memory"

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
        return self._store.hybrid_search(query, collection=collection, top_k=max(1, int(top_k)))

    def cleanup_expired(self) -> int:
        return self._store.cleanup_expired()


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
