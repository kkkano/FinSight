# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, text

from backend.rag.observability_models import (
    ChunkRecord,
    FallbackEventRecord,
    QueryEventRecord,
    QueryRunRecord,
    RerankHitRecord,
    RetrievalHitRecord,
    SourceDocRecord,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_dsn() -> str:
    return (
        os.getenv("RAG_OBSERVABILITY_DSN")
        or os.getenv("RAG_V2_POSTGRES_DSN")
        or os.getenv("LANGGRAPH_CHECKPOINT_POSTGRES_DSN")
        or ""
    ).strip()


def _env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 3650) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except Exception:
        return default
    return max(min_value, min(max_value, value))


def _json_dumps(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


class NoOpRAGObservabilityStore:
    def ensure_schema(self) -> bool:
        return False

    def start_query_run(self, record: QueryRunRecord) -> str:
        return record.id

    def update_query_run(self, run_id: str, **fields: Any) -> int:
        return 0

    def append_query_events(self, records: Iterable[QueryEventRecord]) -> int:
        return 0

    def append_source_docs(self, records: Iterable[SourceDocRecord]) -> int:
        return 0

    def append_chunks(self, records: Iterable[ChunkRecord]) -> int:
        return 0

    def append_retrieval_hits(self, records: Iterable[RetrievalHitRecord]) -> int:
        return 0

    def append_rerank_hits(self, records: Iterable[RerankHitRecord]) -> int:
        return 0

    def append_fallback_event(self, record: FallbackEventRecord) -> str:
        return record.id

    def cleanup_retention(self) -> int:
        return 0


class SQLRAGObservabilityStore:
    def __init__(self, *, dsn: str) -> None:
        self._engine = create_engine(dsn, future=True, pool_pre_ping=True)
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def ensure_schema(self) -> bool:
        if self._schema_ready:
            return True
        with self._schema_lock:
            if self._schema_ready:
                return True
            with self._engine.begin() as conn:
                conn.execute(text("CREATE TABLE IF NOT EXISTS rag_query_runs (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT NOT NULL, thread_id TEXT NULL, query_text TEXT NOT NULL, query_text_redacted TEXT NULL, query_hash TEXT NOT NULL, route_name TEXT NULL, router_decision TEXT NULL, backend_requested TEXT NOT NULL, backend_actual TEXT NOT NULL, collection TEXT NULL, retrieval_k INTEGER NOT NULL DEFAULT 0, rerank_top_n INTEGER NOT NULL DEFAULT 0, source_doc_count INTEGER NOT NULL DEFAULT 0, chunk_count INTEGER NOT NULL DEFAULT 0, retrieval_hit_count INTEGER NOT NULL DEFAULT 0, rerank_hit_count INTEGER NOT NULL DEFAULT 0, fallback_reason TEXT NULL, status TEXT NOT NULL DEFAULT 'running', error_message TEXT NULL, started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ NULL, latency_ms DOUBLE PRECISION NULL, deleted_at TIMESTAMPTZ NULL, deleted_by TEXT NULL, delete_reason TEXT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
                conn.execute(text("CREATE TABLE IF NOT EXISTS rag_query_events (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE, seq_no INTEGER NOT NULL, event_type TEXT NOT NULL, stage TEXT NOT NULL, payload_json JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ NULL, deleted_by TEXT NULL, delete_reason TEXT NULL, UNIQUE(run_id, seq_no))"))
                conn.execute(text("CREATE TABLE IF NOT EXISTS rag_source_docs (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE, source_id TEXT NOT NULL, source_type TEXT NOT NULL, source_name TEXT NULL, url TEXT NULL, title TEXT NULL, published_at TIMESTAMPTZ NULL, content_raw TEXT NOT NULL, content_preview TEXT NULL, content_length INTEGER NOT NULL DEFAULT 0, metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb, deleted_at TIMESTAMPTZ NULL, deleted_by TEXT NULL, delete_reason TEXT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(run_id, source_id))"))
                conn.execute(text("CREATE TABLE IF NOT EXISTS rag_chunks (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE, source_doc_id TEXT NOT NULL REFERENCES rag_source_docs(id) ON DELETE CASCADE, chunk_index INTEGER NOT NULL, total_chunks INTEGER NOT NULL, chunk_text TEXT NOT NULL, chunk_length INTEGER NOT NULL, doc_type TEXT NOT NULL, chunk_strategy TEXT NOT NULL, chunk_size INTEGER NOT NULL, chunk_overlap INTEGER NOT NULL, char_start INTEGER NULL, char_end INTEGER NULL, metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb, deleted_at TIMESTAMPTZ NULL, deleted_by TEXT NULL, delete_reason TEXT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(source_doc_id, chunk_index))"))
                conn.execute(text("CREATE TABLE IF NOT EXISTS rag_retrieval_hits (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE, chunk_id TEXT NULL, collection TEXT NULL, source_id TEXT NULL, source_doc_id TEXT NULL, scope TEXT NULL, dense_rank INTEGER NULL, dense_score DOUBLE PRECISION NULL, sparse_rank INTEGER NULL, sparse_score DOUBLE PRECISION NULL, rrf_score DOUBLE PRECISION NULL, selected_for_rerank BOOLEAN NOT NULL DEFAULT false, metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb, deleted_at TIMESTAMPTZ NULL, deleted_by TEXT NULL, delete_reason TEXT NULL, created_at TIMESTAMPTZ NOT NULL)"))
                conn.execute(text("CREATE TABLE IF NOT EXISTS rag_rerank_hits (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE, chunk_id TEXT NULL, input_rank INTEGER NOT NULL, output_rank INTEGER NOT NULL, rerank_score DOUBLE PRECISION NULL, selected_for_answer BOOLEAN NOT NULL DEFAULT false, metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb, deleted_at TIMESTAMPTZ NULL, deleted_by TEXT NULL, delete_reason TEXT NULL, created_at TIMESTAMPTZ NOT NULL, UNIQUE(run_id, input_rank), UNIQUE(run_id, output_rank))"))
                conn.execute(text("CREATE TABLE IF NOT EXISTS rag_fallback_events (id TEXT PRIMARY KEY, run_id TEXT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE, reason_code TEXT NOT NULL, reason_text TEXT NULL, backend_before TEXT NULL, backend_after TEXT NOT NULL, payload_json JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL, deleted_at TIMESTAMPTZ NULL, deleted_by TEXT NULL, delete_reason TEXT NULL)"))
            self._schema_ready = True
        return True

    def start_query_run(self, record: QueryRunRecord) -> str:
        self.ensure_schema()
        with self._engine.begin() as conn:
            conn.execute(text("INSERT INTO rag_query_runs (id, user_id, session_id, thread_id, query_text, query_text_redacted, query_hash, route_name, router_decision, backend_requested, backend_actual, collection, retrieval_k, rerank_top_n, source_doc_count, chunk_count, retrieval_hit_count, rerank_hit_count, fallback_reason, status, error_message, started_at, finished_at, latency_ms, updated_at) VALUES (:id, :user_id, :session_id, :thread_id, :query_text, :query_text_redacted, :query_hash, :route_name, :router_decision, :backend_requested, :backend_actual, :collection, :retrieval_k, :rerank_top_n, :source_doc_count, :chunk_count, :retrieval_hit_count, :rerank_hit_count, :fallback_reason, :status, :error_message, :started_at, :finished_at, :latency_ms, :updated_at) ON CONFLICT (id) DO UPDATE SET updated_at = EXCLUDED.updated_at"), {'id': record.id, 'user_id': record.user_id, 'session_id': record.session_id, 'thread_id': record.thread_id, 'query_text': record.query_text, 'query_text_redacted': record.query_text_redacted, 'query_hash': record.query_hash, 'route_name': record.route_name, 'router_decision': record.router_decision, 'backend_requested': record.backend_requested, 'backend_actual': record.backend_actual, 'collection': record.collection, 'retrieval_k': int(record.retrieval_k), 'rerank_top_n': int(record.rerank_top_n), 'source_doc_count': int(record.source_doc_count), 'chunk_count': int(record.chunk_count), 'retrieval_hit_count': int(record.retrieval_hit_count), 'rerank_hit_count': int(record.rerank_hit_count), 'fallback_reason': record.fallback_reason, 'status': record.status, 'error_message': record.error_message, 'started_at': record.started_at, 'finished_at': record.finished_at, 'latency_ms': record.latency_ms, 'updated_at': _utc_now()})
        return record.id
    def update_query_run(self, run_id: str, **fields: Any) -> int:
        self.ensure_schema()
        allowed = {'router_decision','backend_requested','backend_actual','collection','retrieval_k','rerank_top_n','source_doc_count','chunk_count','retrieval_hit_count','rerank_hit_count','fallback_reason','status','error_message','finished_at','latency_ms'}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return 0
        params: dict[str, Any] = {'id': run_id, 'updated_at': _utc_now()}
        assignments: list[str] = []
        for idx, (key, value) in enumerate(updates.items()):
            bind_key = f'v{idx}'
            assignments.append(f'{key} = :{bind_key}')
            params[bind_key] = value
        assignments.append('updated_at = :updated_at')
        with self._engine.begin() as conn:
            result = conn.execute(text(f"UPDATE rag_query_runs SET {', '.join(assignments)} WHERE id = :id"), params)
        return int(result.rowcount or 0)

    def append_query_events(self, records: Iterable[QueryEventRecord]) -> int:
        sql = text("INSERT INTO rag_query_events (id, run_id, seq_no, event_type, stage, payload_json, created_at) VALUES (:id, :run_id, :seq_no, :event_type, :stage, CAST(:payload_json AS jsonb), :created_at) ON CONFLICT (run_id, seq_no) DO UPDATE SET payload_json = EXCLUDED.payload_json")
        return self._bulk_insert(sql, ({'id': r.id, 'run_id': r.run_id, 'seq_no': int(r.seq_no), 'event_type': r.event_type, 'stage': r.stage, 'payload_json': _json_dumps(r.payload_json), 'created_at': r.created_at} for r in records))

    def append_source_docs(self, records: Iterable[SourceDocRecord]) -> int:
        sql = text("INSERT INTO rag_source_docs (id, run_id, source_id, source_type, source_name, url, title, published_at, content_raw, content_preview, content_length, metadata_json, created_at) VALUES (:id, :run_id, :source_id, :source_type, :source_name, :url, :title, :published_at, :content_raw, :content_preview, :content_length, CAST(:metadata_json AS jsonb), :created_at) ON CONFLICT (run_id, source_id) DO UPDATE SET content_raw = EXCLUDED.content_raw, content_preview = EXCLUDED.content_preview, content_length = EXCLUDED.content_length, metadata_json = EXCLUDED.metadata_json, updated_at = now()")
        return self._bulk_insert(sql, ({'id': r.id, 'run_id': r.run_id, 'source_id': r.source_id, 'source_type': r.source_type, 'source_name': r.source_name, 'url': r.url, 'title': r.title, 'published_at': r.published_at, 'content_raw': r.content_raw, 'content_preview': r.content_preview, 'content_length': int(r.content_length), 'metadata_json': _json_dumps(r.metadata_json), 'created_at': r.created_at} for r in records))

    def append_chunks(self, records: Iterable[ChunkRecord]) -> int:
        sql = text("INSERT INTO rag_chunks (id, run_id, source_doc_id, chunk_index, total_chunks, chunk_text, chunk_length, doc_type, chunk_strategy, chunk_size, chunk_overlap, char_start, char_end, metadata_json, created_at) VALUES (:id, :run_id, :source_doc_id, :chunk_index, :total_chunks, :chunk_text, :chunk_length, :doc_type, :chunk_strategy, :chunk_size, :chunk_overlap, :char_start, :char_end, CAST(:metadata_json AS jsonb), :created_at) ON CONFLICT (source_doc_id, chunk_index) DO UPDATE SET chunk_text = EXCLUDED.chunk_text, metadata_json = EXCLUDED.metadata_json, updated_at = now()")
        return self._bulk_insert(sql, ({'id': r.id, 'run_id': r.run_id, 'source_doc_id': r.source_doc_id, 'chunk_index': int(r.chunk_index), 'total_chunks': int(r.total_chunks), 'chunk_text': r.chunk_text, 'chunk_length': int(r.chunk_length), 'doc_type': r.doc_type, 'chunk_strategy': r.chunk_strategy, 'chunk_size': int(r.chunk_size), 'chunk_overlap': int(r.chunk_overlap), 'char_start': r.char_start, 'char_end': r.char_end, 'metadata_json': _json_dumps(r.metadata_json), 'created_at': r.created_at} for r in records))

    def append_retrieval_hits(self, records: Iterable[RetrievalHitRecord]) -> int:
        sql = text("INSERT INTO rag_retrieval_hits (id, run_id, chunk_id, collection, source_id, source_doc_id, scope, dense_rank, dense_score, sparse_rank, sparse_score, rrf_score, selected_for_rerank, metadata_json, created_at) VALUES (:id, :run_id, :chunk_id, :collection, :source_id, :source_doc_id, :scope, :dense_rank, :dense_score, :sparse_rank, :sparse_score, :rrf_score, :selected_for_rerank, CAST(:metadata_json AS jsonb), :created_at) ON CONFLICT (id) DO NOTHING")
        return self._bulk_insert(sql, ({'id': r.id, 'run_id': r.run_id, 'chunk_id': r.chunk_id, 'collection': r.collection, 'source_id': r.source_id, 'source_doc_id': r.source_doc_id, 'scope': r.scope, 'dense_rank': r.dense_rank, 'dense_score': r.dense_score, 'sparse_rank': r.sparse_rank, 'sparse_score': r.sparse_score, 'rrf_score': r.rrf_score, 'selected_for_rerank': bool(r.selected_for_rerank), 'metadata_json': _json_dumps(r.metadata_json), 'created_at': r.created_at} for r in records))

    def append_rerank_hits(self, records: Iterable[RerankHitRecord]) -> int:
        sql = text("INSERT INTO rag_rerank_hits (id, run_id, chunk_id, input_rank, output_rank, rerank_score, selected_for_answer, metadata_json, created_at) VALUES (:id, :run_id, :chunk_id, :input_rank, :output_rank, :rerank_score, :selected_for_answer, CAST(:metadata_json AS jsonb), :created_at) ON CONFLICT (id) DO NOTHING")
        return self._bulk_insert(sql, ({'id': r.id, 'run_id': r.run_id, 'chunk_id': r.chunk_id, 'input_rank': int(r.input_rank), 'output_rank': int(r.output_rank), 'rerank_score': r.rerank_score, 'selected_for_answer': bool(r.selected_for_answer), 'metadata_json': _json_dumps(r.metadata_json), 'created_at': r.created_at} for r in records))

    def append_fallback_event(self, record: FallbackEventRecord) -> str:
        self.ensure_schema()
        with self._engine.begin() as conn:
            conn.execute(text("INSERT INTO rag_fallback_events (id, run_id, reason_code, reason_text, backend_before, backend_after, payload_json, created_at) VALUES (:id, :run_id, :reason_code, :reason_text, :backend_before, :backend_after, CAST(:payload_json AS jsonb), :created_at) ON CONFLICT (id) DO NOTHING"), {'id': record.id, 'run_id': record.run_id, 'reason_code': record.reason_code, 'reason_text': record.reason_text, 'backend_before': record.backend_before, 'backend_after': record.backend_after, 'payload_json': _json_dumps(record.payload_json), 'created_at': record.created_at})
        return record.id

    def cleanup_retention(self) -> int:
        self.ensure_schema()
        threshold = _utc_now() - timedelta(days=_env_int("RAG_OBSERVABILITY_RETENTION_DAYS", 30))
        total = 0
        with self._engine.begin() as conn:
            total += int(conn.execute(text("DELETE FROM rag_query_runs WHERE started_at < :threshold"), {'threshold': threshold}).rowcount or 0)
            total += int(conn.execute(text("DELETE FROM rag_fallback_events WHERE run_id IS NULL AND created_at < :threshold"), {'threshold': threshold}).rowcount or 0)
        return total

    def _bulk_insert(self, sql: Any, rows: Iterable[dict[str, Any]]) -> int:
        payload = list(rows)
        if not payload:
            return 0
        self.ensure_schema()
        with self._engine.begin() as conn:
            for row in payload:
                conn.execute(sql, row)
        return len(payload)


RAGObservabilityStore = SQLRAGObservabilityStore
_store_singleton: SQLRAGObservabilityStore | NoOpRAGObservabilityStore | None = None
_store_lock = threading.Lock()


def get_rag_observability_store() -> SQLRAGObservabilityStore | NoOpRAGObservabilityStore:
    global _store_singleton
    if _store_singleton is not None:
        return _store_singleton
    with _store_lock:
        if _store_singleton is None:
            dsn = _resolve_dsn()
            _store_singleton = SQLRAGObservabilityStore(dsn=dsn) if dsn else NoOpRAGObservabilityStore()
    return _store_singleton


def reset_rag_observability_store_cache() -> None:
    global _store_singleton
    with _store_lock:
        _store_singleton = None


def install_rag_observability_hooks() -> bool:
    return True


__all__ = [
    'NoOpRAGObservabilityStore',
    'SQLRAGObservabilityStore',
    'RAGObservabilityStore',
    'get_rag_observability_store',
    'reset_rag_observability_store_cache',
    'install_rag_observability_hooks',
]


def _runtime_fetch_all(store: SQLRAGObservabilityStore, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    store.ensure_schema()
    with store._engine.connect() as conn:
        rows = conn.execute(text(sql), params or {}).mappings().all()
    items = [dict(row) for row in rows]
    for item in items:
        if 'payload_json' in item:
            try:
                item['payload_json'] = json.loads(item['payload_json']) if isinstance(item['payload_json'], str) else item['payload_json']
            except Exception:
                item['payload_json'] = {}
        if 'metadata_json' in item:
            try:
                item['metadata_json'] = json.loads(item['metadata_json']) if isinstance(item['metadata_json'], str) else item['metadata_json']
            except Exception:
                item['metadata_json'] = {}
        if 'metadata' in item:
            try:
                item['metadata'] = json.loads(item['metadata']) if isinstance(item['metadata'], str) else item['metadata']
            except Exception:
                item['metadata'] = {}
    return items


def _runtime_fetch_one(store: SQLRAGObservabilityStore, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    items = _runtime_fetch_all(store, sql, params)
    return items[0] if items else None


def _noop_health_summary(self: NoOpRAGObservabilityStore, recent_limit: int = 3, fallback_limit: int = 3) -> dict[str, Any]:
    return {'enabled': False, 'status': 'disabled', 'recent_runs': [], 'fallback_summary': [], 'recent_run_count_24h': 0, 'recent_fallback_count_24h': 0, 'recent_empty_hits_rate_24h': 0.0, 'last_run_at': None, 'last_fallback_at': None}


def _sql_health_summary(self: SQLRAGObservabilityStore, recent_limit: int = 3, fallback_limit: int = 3) -> dict[str, Any]:
    since = _utc_now() - timedelta(hours=24)
    stats = _runtime_fetch_one(self, "SELECT COUNT(*) AS total_runs, SUM(CASE WHEN started_at >= :since THEN 1 ELSE 0 END) AS recent_run_count_24h, SUM(CASE WHEN started_at >= :since AND COALESCE(retrieval_hit_count, 0) = 0 THEN 1 ELSE 0 END) AS recent_empty_hit_runs, MAX(started_at) AS last_run_at FROM rag_query_runs WHERE deleted_at IS NULL", {'since': since}) or {}
    fallback = _runtime_fetch_one(self, "SELECT COUNT(*) AS recent_fallback_count_24h, MAX(created_at) AS last_fallback_at FROM rag_fallback_events WHERE deleted_at IS NULL AND created_at >= :since", {'since': since}) or {}
    recent_runs = _runtime_fetch_all(self, "SELECT * FROM rag_query_runs WHERE deleted_at IS NULL ORDER BY started_at DESC LIMIT :limit", {'limit': max(1, int(recent_limit))})
    fallback_summary = _runtime_fetch_all(self, "SELECT * FROM rag_fallback_events WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT :limit", {'limit': max(1, int(fallback_limit))})
    total_recent = int(stats.get('recent_run_count_24h') or 0)
    empty_recent = int(stats.get('recent_empty_hit_runs') or 0)
    return {'enabled': True, 'status': 'ok', 'recent_runs': recent_runs, 'fallback_summary': fallback_summary, 'recent_run_count_24h': total_recent, 'recent_fallback_count_24h': int(fallback.get('recent_fallback_count_24h') or 0), 'recent_empty_hits_rate_24h': (empty_recent / total_recent) if total_recent > 0 else 0.0, 'last_run_at': stats.get('last_run_at'), 'last_fallback_at': fallback.get('last_fallback_at')}


def _noop_list_runs(self: NoOpRAGObservabilityStore, *, limit: int = 20, cursor: str | None = None, q: str | None = None, fallback_only: bool = False) -> dict[str, Any]:
    return {'items': [], 'next_cursor': None}


def _sql_list_runs(self: SQLRAGObservabilityStore, *, limit: int = 20, cursor: str | None = None, q: str | None = None, fallback_only: bool = False) -> dict[str, Any]:
    where = ["deleted_at IS NULL"]
    params: dict[str, Any] = {'limit': max(1, min(int(limit), 200))}
    if cursor:
        where.append("started_at < :cursor")
        params['cursor'] = cursor
    if q:
        where.append("(lower(query_text) LIKE :q OR lower(COALESCE(query_text_redacted, '')) LIKE :q)")
        params['q'] = f"%{str(q).strip().lower()}%"
    if fallback_only:
        where.append("fallback_reason IS NOT NULL")
    items = _runtime_fetch_all(self, f"SELECT * FROM rag_query_runs WHERE {' AND '.join(where)} ORDER BY started_at DESC LIMIT :limit", params)
    return {'items': items, 'next_cursor': items[-1].get('started_at') if items else None}


def _noop_get_run_detail(self: NoOpRAGObservabilityStore, run_id: str) -> dict[str, Any] | None:
    return None


def _sql_get_run_detail(self: SQLRAGObservabilityStore, run_id: str) -> dict[str, Any] | None:
    return _runtime_fetch_one(self, "SELECT * FROM rag_query_runs WHERE id = :run_id", {'run_id': run_id})


def _noop_list_events(self: NoOpRAGObservabilityStore, *, run_id: str, limit: int = 500) -> dict[str, Any]:
    return {'items': []}


def _sql_list_events(self: SQLRAGObservabilityStore, *, run_id: str, limit: int = 500) -> dict[str, Any]:
    return {'items': _runtime_fetch_all(self, "SELECT * FROM rag_query_events WHERE run_id = :run_id AND deleted_at IS NULL ORDER BY seq_no ASC LIMIT :limit", {'run_id': run_id, 'limit': max(1, min(int(limit), 2000))})}


def _noop_list_documents(self: NoOpRAGObservabilityStore, *, run_id: str | None = None, collection: str | None = None, include_deleted: bool = False, limit: int = 200) -> dict[str, Any]:
    return {'items': []}


def _sql_list_documents(self: SQLRAGObservabilityStore, *, run_id: str | None = None, collection: str | None = None, include_deleted: bool = False, limit: int = 200) -> dict[str, Any]:
    where = ["1=1"]
    params: dict[str, Any] = {'limit': max(1, min(int(limit), 1000))}
    if not include_deleted:
        where.append("deleted_at IS NULL")
    if run_id:
        where.append("run_id = :run_id")
        params['run_id'] = run_id
    items = _runtime_fetch_all(self, f"SELECT * FROM rag_source_docs WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT :limit", params)
    if collection:
        items = [item for item in items if str((item.get('metadata_json') or {}).get('collection') or '') == collection]
    return {'items': items}


def _noop_list_chunks(self: NoOpRAGObservabilityStore, *, run_id: str | None = None, collection: str | None = None, source_doc_id: str | None = None, include_deleted: bool = False, limit: int = 500) -> dict[str, Any]:
    return {'items': []}


def _sql_list_chunks(self: SQLRAGObservabilityStore, *, run_id: str | None = None, collection: str | None = None, source_doc_id: str | None = None, include_deleted: bool = False, limit: int = 500) -> dict[str, Any]:
    where = ["1=1"]
    params: dict[str, Any] = {'limit': max(1, min(int(limit), 2000))}
    if not include_deleted:
        where.append("deleted_at IS NULL")
    if run_id:
        where.append("run_id = :run_id")
        params['run_id'] = run_id
    if source_doc_id:
        where.append("source_doc_id = :source_doc_id")
        params['source_doc_id'] = source_doc_id
    items = _runtime_fetch_all(self, f"SELECT * FROM rag_chunks WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT :limit", params)
    if collection:
        items = [item for item in items if str((item.get('metadata_json') or {}).get('collection') or '') == collection]
    return {'items': items}


def _noop_list_hits(self: NoOpRAGObservabilityStore, *, run_id: str | None = None, collection: str | None = None, include_deleted: bool = False, limit: int = 500) -> dict[str, Any]:
    return {'items': []}


def _sql_list_hits(self: SQLRAGObservabilityStore, *, run_id: str | None = None, collection: str | None = None, include_deleted: bool = False, limit: int = 500) -> dict[str, Any]:
    where = ["1=1"]
    params: dict[str, Any] = {'limit': max(1, min(int(limit), 2000))}
    if not include_deleted:
        where.append("rh.deleted_at IS NULL")
    if run_id:
        where.append("rh.run_id = :run_id")
        params['run_id'] = run_id
    items = _runtime_fetch_all(self, f"SELECT rh.*, rr.input_rank, rr.output_rank, rr.rerank_score, rr.selected_for_answer, ch.chunk_index, ch.chunk_text FROM rag_retrieval_hits rh LEFT JOIN rag_rerank_hits rr ON rr.run_id = rh.run_id AND COALESCE(rr.chunk_id, '') = COALESCE(rh.chunk_id, '') LEFT JOIN rag_chunks ch ON ch.id = rh.chunk_id WHERE {' AND '.join(where)} ORDER BY rh.created_at DESC LIMIT :limit", params)
    if collection:
        items = [item for item in items if str(item.get('collection') or '') == collection]
    for item in items:
        item['chunk_preview'] = str(item.get('chunk_text') or '')[:220]
    return {'items': items}


def _noop_list_collections(self: NoOpRAGObservabilityStore, *, limit: int = 200) -> dict[str, Any]:
    return {'items': []}


def _sql_list_collections(self: SQLRAGObservabilityStore, *, limit: int = 200) -> dict[str, Any]:
    try:
        items = _runtime_fetch_all(self, "SELECT collection, COUNT(*) AS row_count, MAX(created_at) AS last_created_at FROM rag_documents_v2 GROUP BY collection ORDER BY MAX(created_at) DESC LIMIT :limit", {'limit': max(1, min(int(limit), 1000))})
    except Exception:
        items = []
    return {'items': items}


def _noop_search_preview(self: NoOpRAGObservabilityStore, *, query: str, collection: str, top_k: int = 10) -> list[dict[str, Any]]:
    return []


def _sql_search_preview(self: SQLRAGObservabilityStore, *, query: str, collection: str, top_k: int = 10) -> list[dict[str, Any]]:
    from backend.rag.hybrid_service import get_rag_service
    if not query.strip() or not collection.strip():
        return []
    return list(get_rag_service().hybrid_search(query, collection=collection, top_k=max(1, int(top_k))))


def _noop_soft_delete_run(self: NoOpRAGObservabilityStore, run_id: str, deleted_by: str = 'system', reason: str | None = None) -> dict[str, Any] | None:
    return None


def _sql_soft_delete_run(self: SQLRAGObservabilityStore, run_id: str, deleted_by: str = 'system', reason: str | None = None) -> dict[str, Any] | None:
    self.update_query_run(run_id, status='deleted')
    deleted_at = _utc_now()
    with self._engine.begin() as conn:
        for table in ('rag_query_runs', 'rag_query_events', 'rag_source_docs', 'rag_chunks', 'rag_retrieval_hits', 'rag_rerank_hits', 'rag_fallback_events'):
            key = 'id' if table == 'rag_query_runs' else 'run_id'
            conn.execute(text(f"UPDATE {table} SET deleted_at = :deleted_at, deleted_by = :deleted_by, delete_reason = :reason WHERE {key} = :run_id AND deleted_at IS NULL"), {'deleted_at': deleted_at, 'deleted_by': deleted_by, 'reason': reason, 'run_id': run_id})
    return _sql_get_run_detail(self, run_id)


def _noop_soft_delete_source_doc(self: NoOpRAGObservabilityStore, source_doc_id: str, deleted_by: str = 'system', reason: str | None = None) -> dict[str, Any] | None:
    return None


def _sql_soft_delete_source_doc(self: SQLRAGObservabilityStore, source_doc_id: str, deleted_by: str = 'system', reason: str | None = None) -> dict[str, Any] | None:
    deleted_at = _utc_now()
    with self._engine.begin() as conn:
        conn.execute(text("UPDATE rag_source_docs SET deleted_at = :deleted_at, deleted_by = :deleted_by, delete_reason = :reason WHERE id = :source_doc_id AND deleted_at IS NULL"), {'deleted_at': deleted_at, 'deleted_by': deleted_by, 'reason': reason, 'source_doc_id': source_doc_id})
        conn.execute(text("UPDATE rag_chunks SET deleted_at = :deleted_at, deleted_by = :deleted_by, delete_reason = :reason WHERE source_doc_id = :source_doc_id AND deleted_at IS NULL"), {'deleted_at': deleted_at, 'deleted_by': deleted_by, 'reason': reason, 'source_doc_id': source_doc_id})
    return _runtime_fetch_one(self, "SELECT * FROM rag_source_docs WHERE id = :source_doc_id", {'source_doc_id': source_doc_id})


NoOpRAGObservabilityStore.health_summary = _noop_health_summary
SQLRAGObservabilityStore.health_summary = _sql_health_summary
NoOpRAGObservabilityStore.list_runs = _noop_list_runs
SQLRAGObservabilityStore.list_runs = _sql_list_runs
NoOpRAGObservabilityStore.get_run_detail = _noop_get_run_detail
SQLRAGObservabilityStore.get_run_detail = _sql_get_run_detail
NoOpRAGObservabilityStore.list_events = _noop_list_events
SQLRAGObservabilityStore.list_events = _sql_list_events
NoOpRAGObservabilityStore.list_documents = _noop_list_documents
SQLRAGObservabilityStore.list_documents = _sql_list_documents
NoOpRAGObservabilityStore.list_chunks = _noop_list_chunks
SQLRAGObservabilityStore.list_chunks = _sql_list_chunks
NoOpRAGObservabilityStore.list_hits = _noop_list_hits
SQLRAGObservabilityStore.list_hits = _sql_list_hits
NoOpRAGObservabilityStore.list_collections = _noop_list_collections
SQLRAGObservabilityStore.list_collections = _sql_list_collections
NoOpRAGObservabilityStore.search_preview = _noop_search_preview
SQLRAGObservabilityStore.search_preview = _sql_search_preview
NoOpRAGObservabilityStore.soft_delete_run = _noop_soft_delete_run
SQLRAGObservabilityStore.soft_delete_run = _sql_soft_delete_run
NoOpRAGObservabilityStore.soft_delete_source_doc = _noop_soft_delete_source_doc
SQLRAGObservabilityStore.soft_delete_source_doc = _sql_soft_delete_source_doc
