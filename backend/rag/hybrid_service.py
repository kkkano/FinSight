# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import sqrt
from typing import Any, Iterable, Optional

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _tokenize(text_value: str) -> list[str]:
    if not text_value:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text_value)]


def _hash_embedding(text_value: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    tokens = _tokenize(text_value)
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _sparse_overlap_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    q = set(query_tokens)
    d = set(doc_tokens)
    overlap = len(q & d)
    if overlap == 0:
        return 0.0
    return overlap / max(1, len(q))


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
    def __init__(self, *, vector_dim: int, rrf_k: int) -> None:
        self._vector_dim = vector_dim
        self._rrf_k = rrf_k
        self._lock = threading.Lock()
        self._docs: dict[tuple[str, str], dict[str, Any]] = {}

    def ingest_documents(self, docs: Iterable[RAGDocument]) -> dict[str, Any]:
        indexed = 0
        skipped = 0
        with self._lock:
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
                    "embedding": _hash_embedding(content, self._vector_dim),
                    "tokens": _tokenize(content),
                }
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

        q_emb = _hash_embedding(query_text, self._vector_dim)
        q_tokens = _tokenize(query_text)

        dense_scored: list[tuple[str, float]] = []
        sparse_scored: list[tuple[str, float]] = []
        by_source: dict[str, dict[str, Any]] = {}
        for d in docs:
            source_id = d["source_id"]
            by_source[source_id] = d
            dense_scored.append((source_id, _cosine(q_emb, d["embedding"])))
            sparse_scored.append((source_id, _sparse_overlap_score(q_tokens, d["tokens"])))

        dense_sorted = sorted(dense_scored, key=lambda x: x[1], reverse=True)
        sparse_sorted = sorted(sparse_scored, key=lambda x: x[1], reverse=True)

        dense_rank = {sid: rank + 1 for rank, (sid, _) in enumerate(dense_sorted)}
        sparse_rank = {sid: rank + 1 for rank, (sid, _) in enumerate(sparse_sorted) if _ > 0}
        dense_score_map = dict(dense_scored)
        sparse_score_map = dict(sparse_scored)

        fused: list[dict[str, Any]] = []
        for sid, payload in by_source.items():
            d_rank = dense_rank.get(sid)
            s_rank = sparse_rank.get(sid)
            rrf = 0.0
            if d_rank is not None:
                rrf += 1.0 / (self._rrf_k + d_rank)
            if s_rank is not None:
                rrf += 1.0 / (self._rrf_k + s_rank)
            fused.append(
                {
                    "source_id": sid,
                    "collection": payload["collection"],
                    "scope": payload["scope"],
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
    def __init__(self, *, dsn: str, vector_dim: int, rrf_k: int) -> None:
        self._dsn = dsn
        self._vector_dim = vector_dim
        self._rrf_k = rrf_k
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
        with self._engine.begin() as conn:
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
                embedding = _hash_embedding(content, self._vector_dim)
                conn.execute(
                    sql,
                    {
                        "collection": collection,
                        "scope": (doc.scope or "ephemeral").strip() or "ephemeral",
                        "source_id": source_id,
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
        q_emb = _vector_literal(_hash_embedding(query_text, self._vector_dim))
        candidate_k = max(12, int(top_k) * 4)
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
                + COALESCE(1.0 / (:rrf_k + sparse.sparse_rank), 0) AS rrf_score
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
    ) -> None:
        self.vector_dim = max(16, int(vector_dim))
        self.rrf_k = max(1, int(rrf_k))
        self.backend_name = "memory"
        self.fallback_reason: Optional[str] = None
        backend_norm = (backend or "auto").strip().lower()

        if backend_norm == "memory":
            self._store = _InMemoryHybridStore(vector_dim=self.vector_dim, rrf_k=self.rrf_k)
            self.backend_name = "memory"
            return

        dsn = (postgres_dsn or "").strip()
        wants_postgres = backend_norm == "postgres" or (backend_norm == "auto" and bool(dsn))
        if wants_postgres and dsn:
            try:
                self._store = _PostgresHybridStore(dsn=dsn, vector_dim=self.vector_dim, rrf_k=self.rrf_k)
                self.backend_name = "postgres"
                return
            except Exception as exc:
                if not allow_memory_fallback:
                    raise
                self.fallback_reason = str(exc)
                logger.warning("RAG v2 fallback to memory backend: %s", exc)

        self._store = _InMemoryHybridStore(vector_dim=self.vector_dim, rrf_k=self.rrf_k)
        self.backend_name = "memory"

    @classmethod
    def from_env(cls) -> "HybridRAGService":
        backend = os.getenv("RAG_V2_BACKEND", "auto")
        vector_dim = int((os.getenv("RAG_V2_VECTOR_DIM") or "96").strip())
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
        return cls(
            backend=backend,
            vector_dim=64,
            rrf_k=40,
            postgres_dsn=None,
            allow_memory_fallback=True,
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
