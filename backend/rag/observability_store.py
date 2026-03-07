# -*- coding: utf-8 -*-
from __future__ import annotations

import functools
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from backend.rag.chunker import chunk_document
from backend.rag.hybrid_service import HybridRAGService, RAGDocument, get_rag_service
from backend.rag.observability_models import (
    ChunkRecord,
    FallbackEventRecord,
    PendingIngestBatch,
    PendingIngestDocRecord,
    QueryEventRecord,
    QueryRunRecord,
    RetrievalHitRecord,
    SearchRunContext,
    SourceDocRecord,
)
from backend.rag.observability_runtime import (
    NoOpRAGObservabilityStore as _RuntimeNoOp,
    SQLRAGObservabilityStore as _RuntimeSQL,
    _json_dumps,
    _resolve_dsn,
    _store_lock,
    _utc_now,
)

logger = logging.getLogger(__name__)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _truncate(value: str | None, limit: int = 280) -> str | None:
    text_value = (value or "").strip()
    if not text_value:
        return None
    if len(text_value) <= limit:
        return text_value
    return text_value[: max(0, limit - 1)] + "…"


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _json_loads(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _mapping_to_dict(row: Any) -> dict[str, Any]:
    data = dict(row)
    for key in ("metadata_json", "payload_json"):
        if key in data:
            data[key] = _json_loads(data.get(key), {})
    return data


def _encode_cursor(started_at: Any, run_id: str) -> str | None:
    if started_at is None or not run_id:
        return None
    return f"{started_at.isoformat()}|{run_id}"


def _decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor or "|" not in cursor:
        return None
    raw_dt, run_id = cursor.split("|", 1)
    try:
        dt_value = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value, run_id


def _doc_type_from_source(source_type: str | None, content: str) -> str:
    normalized = (source_type or "").strip().lower()
    if normalized in {"filing", "transcript", "news", "research", "web_page", "table"}:
        return normalized
    if "transcript" in normalized:
        return "transcript"
    if "filing" in normalized or normalized in {"sec", "10-k", "10-q", "8-k", "annual_report", "quarterly_report"}:
        return "filing"
    if "news" in normalized:
        return "news"
    if "research" in normalized or "report" in normalized:
        return "research"
    if "table" in normalized or "|" in (content or ""):
        return "table"
    return "web_page"


def _chunk_params(doc_type: str) -> tuple[int, int]:
    return {
        "filing": (1000, 200),
        "transcript": (800, 100),
        "news": (2000, 0),
        "research": (1200, 200),
        "web_page": (1200, 200),
        "table": (8000, 0),
    }.get(doc_type, (1200, 200))


_DB_BROWSER_TABLES: dict[str, dict[str, Any]] = {
    "rag_query_runs": {
        "preferred_columns": [
            "id",
            "started_at",
            "status",
            "collection",
            "route_name",
            "router_decision",
            "backend_actual",
            "query_text",
            "source_doc_count",
            "chunk_count",
            "retrieval_hit_count",
            "fallback_reason",
            "latency_ms",
            "metadata_json",
            "created_at",
            "updated_at",
            "deleted_at",
            "deleted_by",
            "delete_reason",
        ],
        "search_columns": [
            "id",
            "query_text",
            "query_text_redacted",
            "collection",
            "route_name",
            "router_decision",
            "status",
            "fallback_reason",
        ],
        "filters": {
            "collection": {"column": "collection"},
            "run_id": {"column": "id"},
        },
        "order_by": [("started_at", "DESC"), ("id", "DESC")],
    },
    "rag_source_docs": {
        "preferred_columns": [
            "id",
            "run_id",
            "collection",
            "source_id",
            "source_type",
            "source_name",
            "title",
            "url",
            "published_at",
            "content_preview",
            "content_raw",
            "content_length",
            "metadata_json",
            "created_at",
            "updated_at",
            "deleted_at",
            "deleted_by",
            "delete_reason",
        ],
        "search_columns": [
            "id",
            "run_id",
            "collection",
            "source_id",
            "source_type",
            "source_name",
            "title",
            "url",
            "content_preview",
            "content_raw",
        ],
        "filters": {
            "collection": {"column": "collection"},
            "run_id": {"column": "run_id"},
            "source_doc_id": {"column": "id"},
        },
        "order_by": [("created_at", "DESC"), ("id", "DESC")],
    },
    "rag_chunks": {
        "preferred_columns": [
            "id",
            "run_id",
            "source_doc_id",
            "source_id",
            "collection",
            "chunk_index",
            "total_chunks",
            "doc_type",
            "chunk_strategy",
            "chunk_length",
            "chunk_size",
            "chunk_overlap",
            "char_start",
            "char_end",
            "chunk_text",
            "metadata_json",
            "created_at",
            "updated_at",
            "deleted_at",
            "deleted_by",
            "delete_reason",
        ],
        "search_columns": [
            "id",
            "run_id",
            "source_doc_id",
            "source_id",
            "collection",
            "doc_type",
            "chunk_strategy",
            "chunk_text",
        ],
        "filters": {
            "collection": {"column": "collection"},
            "run_id": {"column": "run_id"},
            "source_doc_id": {"column": "source_doc_id"},
        },
        "order_by": [("created_at", "DESC"), ("id", "DESC")],
    },
    "rag_documents_v2": {
        "preferred_columns": [
            "id",
            "collection",
            "scope",
            "source_id",
            "title",
            "url",
            "source",
            "content",
            "metadata",
            "created_at",
            "expires_at",
        ],
        "search_columns": [
            "id",
            "collection",
            "scope",
            "source_id",
            "title",
            "url",
            "source",
            "content",
        ],
        "search_expressions": [
            {"expression": "LOWER(CAST(\"metadata\" AS TEXT)) LIKE :q", "requires": ["metadata"]},
        ],
        "filters": {
            "collection": {"column": "collection"},
            "run_id": {"expression": "COALESCE(metadata ->> 'run_id', '') = :run_id", "requires": ["metadata"]},
            "source_doc_id": {"expression": "COALESCE(metadata ->> 'source_doc_id', '') = :source_doc_id", "requires": ["metadata"]},
        },
        "order_by": [("created_at", "DESC"), ("id", "DESC")],
        "excluded_columns": {"embedding", "search_vector"},
    },
}


def _quote_identifier(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized or any(not (char.isalnum() or char == "_") for char in normalized):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return f'"{normalized}"'


def _db_browser_available_columns(conn: Any, table_name: str) -> list[str]:
    return [
        str(row["column_name"])
        for row in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :table_name ORDER BY ordinal_position"
            ),
            {"table_name": table_name},
        ).mappings()
    ]


def _db_browser_search_sql(config: dict[str, Any], actual_columns: set[str]) -> list[str]:
    expressions: list[str] = []
    for column_name in config.get("search_columns", []):
        if column_name in actual_columns:
            expressions.append(f"LOWER(CAST({_quote_identifier(column_name)} AS TEXT)) LIKE :q")
    for item in config.get("search_expressions", []):
        required = set(item.get("requires") or [])
        if required.issubset(actual_columns):
            expressions.append(str(item.get("expression") or "").strip())
    return [expression for expression in expressions if expression]


def _db_browser_filter_sql(config: dict[str, Any], actual_columns: set[str], filter_name: str) -> str | None:
    filter_config = (config.get("filters") or {}).get(filter_name) or {}
    column_name = str(filter_config.get("column") or "").strip()
    if column_name:
        if column_name not in actual_columns:
            return None
        return f"{_quote_identifier(column_name)} = :{filter_name}"
    required = set(filter_config.get("requires") or [])
    if not required.issubset(actual_columns):
        return None
    expression = str(filter_config.get("expression") or "").strip()
    return expression or None


def _db_browser_order_by_sql(config: dict[str, Any], actual_columns: set[str], selected_columns: list[str]) -> str:
    fragments: list[str] = []
    for column_name, direction in config.get("order_by", []):
        if column_name in actual_columns:
            normalized_direction = "DESC" if str(direction).upper() == "DESC" else "ASC"
            fragments.append(f"{_quote_identifier(column_name)} {normalized_direction}")
    if fragments:
        return ", ".join(fragments)
    if selected_columns:
        return f"{_quote_identifier(selected_columns[0])} ASC"
    return "1"


class NoOpRAGObservabilityStore(_RuntimeNoOp):
    def browse_db_table(self, *, table_name: str, limit: int = 50, offset: int = 0, q: str | None = None, collection: str | None = None, run_id: str | None = None, source_doc_id: str | None = None) -> dict[str, Any]:
        return {"table": table_name, "columns": [], "items": [], "total": 0, "limit": max(1, int(limit)), "offset": max(0, int(offset)), "has_more": False}

    def cache_ingest_batch(self, *, docs: Iterable[RAGDocument], ingest_stats: dict[str, Any] | None, backend_requested: str, backend_actual: str) -> list[PendingIngestBatch]:
        return []

    def claim_pending_ingest(self, *, collection: str) -> PendingIngestBatch | None:
        return None

    def begin_search_run(self, *, query: str, collection: str, top_k: int, backend_requested: str, backend_actual: str, route_name: str = "hybrid_search", router_decision: str | None = None, fallback_reason: str | None = None, metadata_json: dict[str, Any] | None = None) -> SearchRunContext:
        run = QueryRunRecord(
            id=_new_id("run"),
            user_id="system",
            session_id="rag-observability",
            thread_id=None,
            query_text=query,
            query_text_redacted=query,
            query_hash=_sha256_text(query),
            route_name=route_name,
            router_decision=router_decision,
            backend_requested=backend_requested,
            backend_actual=backend_actual,
            collection=collection,
            retrieval_k=max(1, int(top_k)),
            rerank_top_n=0,
            fallback_reason=fallback_reason,
            status="running",
            metadata_json=metadata_json or {},
        )
        return SearchRunContext(run=run, started_monotonic=time.monotonic())

    def complete_search_run(self, context: SearchRunContext, *, hits: list[dict[str, Any]] | None = None, error: Exception | None = None) -> dict[str, Any]:
        return {"id": context.run.id, "status": "failed" if error else "completed", "hit_count": len(hits or [])}


class SQLRAGObservabilityStore(_RuntimeSQL):
    def __init__(self, *, dsn: str) -> None:
        super().__init__(dsn=dsn)
        self._extended_schema_ready = False
        self._pending_lock = threading.Lock()
        self._pending_batches: dict[str, deque[PendingIngestBatch]] = defaultdict(deque)
        self._pending_ttl_seconds = max(30, min(86400, int(os.getenv("RAG_OBSERVABILITY_PENDING_TTL_SECONDS", "900") or "900")))
        self._pending_max_batches = max(1, min(500, int(os.getenv("RAG_OBSERVABILITY_PENDING_BATCHES", "20") or "20")))

    def ensure_schema(self) -> bool:
        super().ensure_schema()
        if self._extended_schema_ready:
            return True
        with self._schema_lock:
            if self._extended_schema_ready:
                return True
            with self._engine.begin() as conn:
                conn.execute(text("ALTER TABLE rag_query_runs ADD COLUMN IF NOT EXISTS metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb"))
            self._extended_schema_ready = True
        return True

    def start_query_run(self, record: QueryRunRecord) -> str:
        self.ensure_schema()
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO rag_query_runs (id, user_id, session_id, thread_id, query_text, query_text_redacted, query_hash, route_name, router_decision, backend_requested, backend_actual, collection, retrieval_k, rerank_top_n, source_doc_count, chunk_count, retrieval_hit_count, rerank_hit_count, fallback_reason, status, error_message, metadata_json, started_at, finished_at, latency_ms, updated_at) VALUES (:id, :user_id, :session_id, :thread_id, :query_text, :query_text_redacted, :query_hash, :route_name, :router_decision, :backend_requested, :backend_actual, :collection, :retrieval_k, :rerank_top_n, :source_doc_count, :chunk_count, :retrieval_hit_count, :rerank_hit_count, :fallback_reason, :status, :error_message, CAST(:metadata_json AS jsonb), :started_at, :finished_at, :latency_ms, :updated_at) ON CONFLICT (id) DO UPDATE SET query_text = EXCLUDED.query_text, query_text_redacted = EXCLUDED.query_text_redacted, route_name = EXCLUDED.route_name, router_decision = EXCLUDED.router_decision, backend_requested = EXCLUDED.backend_requested, backend_actual = EXCLUDED.backend_actual, collection = EXCLUDED.collection, retrieval_k = EXCLUDED.retrieval_k, rerank_top_n = EXCLUDED.rerank_top_n, source_doc_count = EXCLUDED.source_doc_count, chunk_count = EXCLUDED.chunk_count, retrieval_hit_count = EXCLUDED.retrieval_hit_count, rerank_hit_count = EXCLUDED.rerank_hit_count, fallback_reason = EXCLUDED.fallback_reason, status = EXCLUDED.status, error_message = EXCLUDED.error_message, metadata_json = EXCLUDED.metadata_json, finished_at = EXCLUDED.finished_at, latency_ms = EXCLUDED.latency_ms, updated_at = EXCLUDED.updated_at"
                ),
                {
                    "id": record.id,
                    "user_id": record.user_id,
                    "session_id": record.session_id,
                    "thread_id": record.thread_id,
                    "query_text": record.query_text,
                    "query_text_redacted": record.query_text_redacted,
                    "query_hash": record.query_hash,
                    "route_name": record.route_name,
                    "router_decision": record.router_decision,
                    "backend_requested": record.backend_requested,
                    "backend_actual": record.backend_actual,
                    "collection": record.collection,
                    "retrieval_k": int(record.retrieval_k),
                    "rerank_top_n": int(record.rerank_top_n),
                    "source_doc_count": int(record.source_doc_count),
                    "chunk_count": int(record.chunk_count),
                    "retrieval_hit_count": int(record.retrieval_hit_count),
                    "rerank_hit_count": int(record.rerank_hit_count),
                    "fallback_reason": record.fallback_reason,
                    "status": record.status,
                    "error_message": record.error_message,
                    "metadata_json": _json_dumps(record.metadata_json),
                    "started_at": record.started_at,
                    "finished_at": record.finished_at,
                    "latency_ms": record.latency_ms,
                    "updated_at": _utc_now(),
                },
            )
        return record.id

    def health_summary(self, *, recent_limit: int = 3, fallback_limit: int = 3) -> dict[str, Any]:
        self.ensure_schema()
        since = _utc_now() - timedelta(hours=24)
        with self._engine.connect() as conn:
            recent = [_mapping_to_dict(row) for row in conn.execute(text("SELECT id, query_text, collection, backend_requested, backend_actual, status, fallback_reason, retrieval_hit_count, source_doc_count, chunk_count, started_at, finished_at, latency_ms FROM rag_query_runs WHERE deleted_at IS NULL AND COALESCE((metadata_json ->> 'synthetic_backfill')::boolean, false) = false ORDER BY started_at DESC, id DESC LIMIT :limit"), {"limit": max(1, int(recent_limit))}).mappings()]
            fallback = [_mapping_to_dict(row) for row in conn.execute(text("SELECT reason_code, backend_before, backend_after, COUNT(1) AS count, MAX(created_at) AS latest_at FROM rag_fallback_events WHERE deleted_at IS NULL GROUP BY reason_code, backend_before, backend_after ORDER BY latest_at DESC LIMIT :limit"), {"limit": max(1, int(fallback_limit))}).mappings()]
            run_stats = _mapping_to_dict(conn.execute(text("SELECT SUM(CASE WHEN started_at >= :since THEN 1 ELSE 0 END) AS recent_run_count_24h, SUM(CASE WHEN started_at >= :since AND COALESCE(retrieval_hit_count, 0) = 0 THEN 1 ELSE 0 END) AS recent_empty_hit_runs, MAX(started_at) AS last_run_at FROM rag_query_runs WHERE deleted_at IS NULL AND COALESCE((metadata_json ->> 'synthetic_backfill')::boolean, false) = false"), {"since": since}).mappings().first() or {})
            fallback_stats = _mapping_to_dict(conn.execute(text("SELECT COUNT(1) AS recent_fallback_count_24h, MAX(created_at) AS last_fallback_at FROM rag_fallback_events WHERE deleted_at IS NULL AND created_at >= :since"), {"since": since}).mappings().first() or {})
        recent_run_count_24h = int(run_stats.get("recent_run_count_24h") or 0)
        recent_empty_hit_runs = int(run_stats.get("recent_empty_hit_runs") or 0)
        return {
            "enabled": True,
            "status": "ok",
            "recent_runs": recent,
            "fallback_summary": fallback,
            "recent_run_count_24h": recent_run_count_24h,
            "recent_fallback_count_24h": int(fallback_stats.get("recent_fallback_count_24h") or 0),
            "recent_empty_hits_rate_24h": (recent_empty_hit_runs / recent_run_count_24h) if recent_run_count_24h > 0 else 0.0,
            "last_run_at": run_stats.get("last_run_at"),
            "last_fallback_at": fallback_stats.get("last_fallback_at"),
            "pending_ingest_batches": self._pending_batch_count(),
        }

    def list_collections(self, *, limit: int = 200) -> dict[str, Any]:
        self.ensure_schema()
        limit_value = max(1, min(int(limit), 1000))
        try:
            with self._engine.connect() as conn:
                items = [
                    _mapping_to_dict(row)
                    for row in conn.execute(
                        text(
                            """
                            WITH collection_base AS (
                                SELECT DISTINCT collection
                                FROM rag_query_runs
                                WHERE deleted_at IS NULL AND COALESCE(collection, '') <> ''
                                UNION
                                SELECT DISTINCT collection
                                FROM rag_documents_v2
                                WHERE COALESCE(collection, '') <> ''
                            ),
                            run_stats AS (
                                SELECT collection, COUNT(*) AS run_count, MAX(started_at) AS latest_run_at
                                FROM rag_query_runs
                                WHERE deleted_at IS NULL AND COALESCE(collection, '') <> ''
                                GROUP BY collection
                            ),
                            doc_stats AS (
                                SELECT qr.collection, COUNT(DISTINCT rsd.source_id) AS document_count, MAX(rsd.created_at) AS latest_document_at
                                FROM rag_query_runs qr
                                JOIN rag_source_docs rsd ON rsd.run_id = qr.id
                                WHERE qr.deleted_at IS NULL AND rsd.deleted_at IS NULL AND COALESCE(qr.collection, '') <> ''
                                GROUP BY qr.collection
                            ),
                            chunk_stats AS (
                                SELECT qr.collection, COUNT(DISTINCT (rsd.source_id, rc.chunk_index)) AS chunk_count
                                FROM rag_query_runs qr
                                JOIN rag_chunks rc ON rc.run_id = qr.id
                                JOIN rag_source_docs rsd ON rsd.id = rc.source_doc_id
                                WHERE qr.deleted_at IS NULL AND rc.deleted_at IS NULL AND rsd.deleted_at IS NULL AND COALESCE(qr.collection, '') <> ''
                                GROUP BY qr.collection
                            ),
                            vector_stats AS (
                                SELECT collection, COUNT(*) AS row_count, MAX(created_at) AS last_created_at
                                FROM rag_documents_v2
                                WHERE COALESCE(collection, '') <> ''
                                GROUP BY collection
                            ),
                            synthetic_stats AS (
                                SELECT collection, id AS synthetic_backfill_run_id, started_at AS synthetic_backfill_started_at
                                FROM (
                                    SELECT
                                        collection,
                                        id,
                                        started_at,
                                        ROW_NUMBER() OVER (
                                            PARTITION BY collection
                                            ORDER BY started_at DESC, id DESC
                                        ) AS row_no
                                    FROM rag_query_runs
                                    WHERE deleted_at IS NULL
                                      AND COALESCE(collection, '') <> ''
                                      AND COALESCE((metadata_json ->> 'synthetic_backfill')::boolean, false) = true
                                ) ranked
                                WHERE row_no = 1
                            )
                            SELECT
                                base.collection,
                                COALESCE(run_stats.run_count, 0) AS run_count,
                                GREATEST(COALESCE(doc_stats.document_count, 0), COALESCE(vector_stats.row_count, 0)) AS document_count,
                                COALESCE(chunk_stats.chunk_count, 0) AS chunk_count,
                                run_stats.latest_run_at AS latest_run_at,
                                COALESCE(doc_stats.latest_document_at, vector_stats.last_created_at) AS latest_document_at,
                                COALESCE(vector_stats.row_count, doc_stats.document_count, 0) AS row_count,
                                run_stats.latest_run_at AS last_run_at,
                                COALESCE(doc_stats.latest_document_at, vector_stats.last_created_at) AS last_created_at,
                                synthetic_stats.synthetic_backfill_run_id AS synthetic_backfill_run_id,
                                synthetic_stats.synthetic_backfill_started_at AS synthetic_backfill_started_at
                            FROM collection_base base
                            LEFT JOIN run_stats ON run_stats.collection = base.collection
                            LEFT JOIN doc_stats ON doc_stats.collection = base.collection
                            LEFT JOIN chunk_stats ON chunk_stats.collection = base.collection
                            LEFT JOIN vector_stats ON vector_stats.collection = base.collection
                            LEFT JOIN synthetic_stats ON synthetic_stats.collection = base.collection
                            ORDER BY COALESCE(run_stats.latest_run_at, doc_stats.latest_document_at, vector_stats.last_created_at) DESC NULLS LAST, base.collection ASC
                            LIMIT :limit
                            """
                        ),
                        {"limit": limit_value},
                    ).mappings()
                ]
        except Exception:
            return super().list_collections(limit=limit_value)
        return {"items": items}

    def browse_db_table(self, *, table_name: str, limit: int = 50, offset: int = 0, q: str | None = None, collection: str | None = None, run_id: str | None = None, source_doc_id: str | None = None) -> dict[str, Any]:
        self.ensure_schema()
        table_key = str(table_name or "").strip()
        config = _DB_BROWSER_TABLES.get(table_key)
        if not config:
            raise ValueError(f"unsupported table: {table_name}")

        limit_value = max(1, min(int(limit), 200))
        offset_value = max(0, int(offset))
        table_sql = _quote_identifier(table_key)

        with self._engine.connect() as conn:
            available_columns = _db_browser_available_columns(conn, table_key)
            if not available_columns:
                raise ValueError(f"table not found: {table_key}")

            available_column_set = set(available_columns)
            excluded_columns = set(config.get("excluded_columns") or set())
            preferred_columns = [column for column in config.get("preferred_columns", []) if column in available_column_set and column not in excluded_columns]
            selected_columns = preferred_columns or [column for column in available_columns if column not in excluded_columns]
            if not selected_columns:
                raise ValueError(f"no readable columns for table: {table_key}")

            where_clauses = ["1=1"]
            params: dict[str, Any] = {"limit": limit_value, "offset": offset_value}

            q_value = str(q or "").strip().lower()
            if q_value:
                search_clauses = _db_browser_search_sql(config, available_column_set)
                if search_clauses:
                    where_clauses.append(f"({' OR '.join(search_clauses)})")
                    params["q"] = f"%{q_value}%"

            for filter_name, raw_value in (("collection", collection), ("run_id", run_id), ("source_doc_id", source_doc_id)):
                filter_value = str(raw_value or "").strip()
                if not filter_value:
                    continue
                filter_sql = _db_browser_filter_sql(config, available_column_set, filter_name)
                if not filter_sql:
                    continue
                where_clauses.append(filter_sql)
                params[filter_name] = filter_value

            where_sql = " AND ".join(where_clauses)
            order_by_sql = _db_browser_order_by_sql(config, available_column_set, selected_columns)
            select_sql = ", ".join(_quote_identifier(column) for column in selected_columns)

            total_row = conn.execute(text(f"SELECT COUNT(*) AS total FROM {table_sql} WHERE {where_sql}"), params).mappings().first() or {}
            total = int(dict(total_row).get("total") or 0)
            rows = [
                _mapping_to_dict(row)
                for row in conn.execute(
                    text(f"SELECT {select_sql} FROM {table_sql} WHERE {where_sql} ORDER BY {order_by_sql} LIMIT :limit OFFSET :offset"),
                    params,
                ).mappings()
            ]

        return {
            "table": table_key,
            "columns": selected_columns,
            "items": rows,
            "total": total,
            "limit": limit_value,
            "offset": offset_value,
            "has_more": offset_value + len(rows) < total,
        }

    def cache_ingest_batch(self, *, docs: Iterable[RAGDocument], ingest_stats: dict[str, Any] | None, backend_requested: str, backend_actual: str) -> list[PendingIngestBatch]:
        grouped: dict[str, list[PendingIngestDocRecord]] = defaultdict(list)
        for doc in docs or []:
            if not isinstance(doc, RAGDocument):
                continue
            collection = str(doc.collection or '').strip()
            source_id = str(doc.source_id or '').strip()
            content_raw = str(doc.content or '')
            if not collection or not source_id or not content_raw.strip():
                continue
            metadata_json = dict(doc.metadata or {})
            metadata_json.setdefault('collection', collection)
            metadata_json.setdefault('scope', str(doc.scope or 'ephemeral').strip() or 'ephemeral')
            metadata_json.setdefault('source_id', source_id)
            pending_doc = PendingIngestDocRecord(
                collection=collection,
                source_id=source_id,
                source_type=str(metadata_json.get('source_type') or doc.source or 'unknown'),
                source_name=str(metadata_json.get('source_name') or '') or None,
                url=doc.url,
                title=doc.title,
                published_at=metadata_json.get('published_at') if isinstance(metadata_json.get('published_at'), datetime) else None,
                content_raw=content_raw,
                metadata_json=metadata_json,
                created_at=doc.created_at,
            )
            grouped[collection].append(pending_doc)

        batches: list[PendingIngestBatch] = []
        if not grouped:
            return batches

        with self._pending_lock:
            for collection, pending_docs in grouped.items():
                queue = self._pending_batches[collection]
                self._purge_pending_locked(queue)
                batch = PendingIngestBatch(
                    id=_new_id('batch'),
                    collection=collection,
                    backend_requested=backend_requested,
                    backend_actual=backend_actual,
                    ingest_stats=dict(ingest_stats or {}),
                    docs=list(pending_docs),
                    created_at=_utc_now(),
                )
                queue.append(batch)
                while len(queue) > self._pending_max_batches:
                    queue.popleft()
                batches.append(batch)
        return batches

    def claim_pending_ingest(self, *, collection: str) -> PendingIngestBatch | None:
        normalized = str(collection or '').strip()
        if not normalized:
            return None
        with self._pending_lock:
            queue = self._pending_batches.get(normalized)
            if not queue:
                return None
            self._purge_pending_locked(queue)
            while queue:
                batch = queue.pop()
                if batch.collection == normalized:
                    return batch
        return None

    def begin_search_run(self, *, query: str, collection: str, top_k: int, backend_requested: str, backend_actual: str, route_name: str = "hybrid_search", router_decision: str | None = None, fallback_reason: str | None = None, metadata_json: dict[str, Any] | None = None) -> SearchRunContext:
        run = QueryRunRecord(
            id=_new_id('run'),
            user_id='system',
            session_id='rag-observability',
            thread_id=None,
            query_text=query,
            query_text_redacted=query,
            query_hash=_sha256_text(query),
            route_name=route_name,
            router_decision=router_decision,
            backend_requested=backend_requested,
            backend_actual=backend_actual,
            collection=collection,
            retrieval_k=max(1, int(top_k)),
            rerank_top_n=0,
            fallback_reason=fallback_reason,
            status='running',
            metadata_json=dict(metadata_json or {}),
        )
        self.start_query_run(run)
        pending_batch = self.claim_pending_ingest(collection=collection)
        context = SearchRunContext(run=run, pending_batch=pending_batch, started_monotonic=time.monotonic())
        self._append_event(run.id, 'search_started', 'search', {'query_preview': _truncate(query, 160), 'collection': collection, 'backend_requested': backend_requested, 'backend_actual': backend_actual, 'top_k': max(1, int(top_k)), 'pending_batch_id': pending_batch.id if pending_batch else None})
        if pending_batch is not None:
            self._append_event(run.id, 'pending_ingest_claimed', 'ingest', {'batch_id': pending_batch.id, 'collection': pending_batch.collection, 'doc_count': len(pending_batch.docs), 'ingest_stats': pending_batch.ingest_stats})
        return context

    def complete_search_run(self, context: SearchRunContext, *, hits: list[dict[str, Any]] | None = None, error: Exception | None = None) -> dict[str, Any]:
        if context.pending_batch is not None:
            self._materialize_pending_batch(context)
        hit_records = self._build_hit_records(context, list(hits or []))
        if hit_records:
            self.append_retrieval_hits(hit_records)
        if context.run.fallback_reason:
            self.append_fallback_event(FallbackEventRecord(id=_new_id('fallback'), run_id=context.run.id, reason_code='rag_backend_fallback', reason_text=context.run.fallback_reason, backend_before=context.run.backend_requested, backend_after=context.run.backend_actual, payload_json={'collection': context.run.collection, 'query_preview': _truncate(context.run.query_text, 160)}, created_at=_utc_now()))
        latency_ms = max(0.0, (time.monotonic() - context.started_monotonic) * 1000.0)
        status = 'failed' if error else 'completed'
        source_doc_count = max(len(context.source_doc_map), int(context.materialized_source_doc_count or 0))
        chunk_count = max(len(context.primary_chunk_map), int(context.materialized_chunk_count or 0))
        self.update_query_run(context.run.id, source_doc_count=source_doc_count, chunk_count=chunk_count, retrieval_hit_count=len(hit_records), rerank_hit_count=0, fallback_reason=context.run.fallback_reason, status=status, error_message=str(error) if error else None, finished_at=_utc_now(), latency_ms=latency_ms)
        self._append_event(context.run.id, 'search_failed' if error else 'search_completed', 'search', {'status': status, 'hit_count': len(hit_records), 'source_doc_count': source_doc_count, 'chunk_count': chunk_count, 'latency_ms': latency_ms, 'error': str(error) if error else None})
        return {'id': context.run.id, 'status': status, 'hit_count': len(hit_records)}

    def _materialize_pending_batch(self, context: SearchRunContext) -> None:
        batch = context.pending_batch
        if batch is None:
            return
        docs: list[SourceDocRecord] = []
        chunks: list[ChunkRecord] = []
        for pending_doc in batch.docs:
            source_doc_id = _new_id('doc')
            content_raw = pending_doc.content_raw or ''
            source_metadata = dict(pending_doc.metadata_json or {})
            source_metadata.setdefault('collection', batch.collection)
            source_metadata.setdefault('source_id', pending_doc.source_id)
            docs.append(SourceDocRecord(id=source_doc_id, run_id=context.run.id, collection=batch.collection, source_id=pending_doc.source_id, source_type=pending_doc.source_type, source_name=pending_doc.source_name, url=pending_doc.url, title=pending_doc.title, published_at=pending_doc.published_at, content_raw=content_raw, content_preview=_truncate(content_raw, 500), content_length=len(content_raw), metadata_json=source_metadata, created_at=pending_doc.created_at))
            context.source_doc_map[pending_doc.source_id] = source_doc_id
            doc_type = _doc_type_from_source(pending_doc.source_type, content_raw)
            chunk_size, chunk_overlap = _chunk_params(doc_type)
            chunk_result = chunk_document(content_raw, doc_type=doc_type, title=pending_doc.title, max_chunk_size=chunk_size, overlap=chunk_overlap)
            chunk_texts = chunk_result.chunks or [content_raw]
            metadata_list = chunk_result.metadata or [{'chunk_index': 0, 'total_chunks': 1, 'doc_type': doc_type}]
            total_chunks = max(1, len(chunk_texts))
            for index, chunk_text in enumerate(chunk_texts):
                chunk_id = _new_id('chunk')
                context.primary_chunk_map.setdefault(pending_doc.source_id, chunk_id)
                meta = metadata_list[index] if index < len(metadata_list) else {}
                chunk_metadata = dict(source_metadata)
                if isinstance(meta, dict):
                    chunk_metadata.update(meta)
                chunk_metadata.setdefault('collection', batch.collection)
                chunk_metadata.setdefault('source_id', pending_doc.source_id)
                chunks.append(ChunkRecord(id=chunk_id, run_id=context.run.id, collection=batch.collection, source_id=pending_doc.source_id, source_doc_id=source_doc_id, chunk_index=int(meta.get('chunk_index', index) or index), total_chunks=int(meta.get('total_chunks', total_chunks) or total_chunks), chunk_text=chunk_text, chunk_length=len(chunk_text), doc_type=str(meta.get('doc_type') or doc_type), chunk_strategy=doc_type, chunk_size=chunk_size, chunk_overlap=chunk_overlap, char_start=int(meta['char_start']) if isinstance(meta, dict) and meta.get('char_start') is not None else None, char_end=int(meta['char_end']) if isinstance(meta, dict) and meta.get('char_end') is not None else None, metadata_json=chunk_metadata, created_at=pending_doc.created_at))
        if docs:
            self.append_source_docs(docs)
        if chunks:
            self.append_chunks(chunks)
        context.materialized_source_doc_count = len(docs)
        context.materialized_chunk_count = len(chunks)
        self._append_event(context.run.id, 'pending_ingest_materialized', 'ingest', {'batch_id': batch.id, 'collection': batch.collection, 'doc_count': len(docs), 'chunk_count': len(chunks)})

    def _build_hit_records(self, context: SearchRunContext, hits: list[dict[str, Any]]) -> list[RetrievalHitRecord]:
        records: list[RetrievalHitRecord] = []
        for hit in hits:
            source_id = str(hit.get('source_id') or '') or None
            metadata_json = hit.get('metadata') if isinstance(hit.get('metadata'), dict) else {}
            records.append(RetrievalHitRecord(id=_new_id('hit'), run_id=context.run.id, chunk_id=context.primary_chunk_map.get(source_id or ''), collection=hit.get('collection') or context.run.collection, source_id=source_id, source_doc_id=context.source_doc_map.get(source_id or '') if source_id else None, scope=hit.get('scope'), dense_rank=hit.get('dense_rank'), dense_score=float(hit.get('dense_score') or 0.0) if hit.get('dense_score') is not None else None, sparse_rank=hit.get('sparse_rank'), sparse_score=float(hit.get('sparse_score') or 0.0) if hit.get('sparse_score') is not None else None, rrf_score=float(hit.get('rrf_score') or 0.0) if hit.get('rrf_score') is not None else None, selected_for_rerank=False, title=hit.get('title'), url=hit.get('url'), content_preview=_truncate(hit.get('content') or hit.get('content_preview') or '', 500), metadata_json=metadata_json))
        return records

    def _next_seq(self, run_id: str) -> int:
        with self._engine.connect() as conn:
            value = conn.execute(text('SELECT COALESCE(MAX(seq_no), 0) FROM rag_query_events WHERE run_id = :run_id'), {'run_id': run_id}).scalar()
        return int(value or 0) + 1

    def _append_event(self, run_id: str, event_type: str, stage: str, payload: dict[str, Any]) -> None:
        self.append_query_events([QueryEventRecord(id=_new_id('evt'), run_id=run_id, seq_no=self._next_seq(run_id), event_type=event_type, stage=stage, payload_json=payload)])

    def _purge_pending_locked(self, queue: deque[PendingIngestBatch]) -> None:
        threshold = _utc_now() - timedelta(seconds=self._pending_ttl_seconds)
        keep = deque(item for item in queue if item.created_at >= threshold)
        queue.clear()
        queue.extend(keep)

    def _pending_batch_count(self) -> int:
        with self._pending_lock:
            total = 0
            for queue in self._pending_batches.values():
                self._purge_pending_locked(queue)
                total += len(queue)
            return total


RAGObservabilityStore = SQLRAGObservabilityStore
_store_singleton: SQLRAGObservabilityStore | NoOpRAGObservabilityStore | None = None
_hooks_lock = threading.Lock()
_hooks_installed = False


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
    global _hooks_installed
    if _hooks_installed:
        return True
    with _hooks_lock:
        if _hooks_installed or getattr(HybridRAGService, "_rag_observability_hooks_installed", False):
            _hooks_installed = True
            return True
        original_ingest = HybridRAGService.ingest_documents
        original_search = HybridRAGService.hybrid_search

        @functools.wraps(original_ingest)
        def observed_ingest(self: HybridRAGService, docs: Iterable[RAGDocument]) -> dict[str, Any]:
            doc_list = list(docs or [])
            result = original_ingest(self, doc_list)
            if doc_list:
                try:
                    get_rag_observability_store().cache_ingest_batch(docs=doc_list, ingest_stats=result if isinstance(result, dict) else {"result": result}, backend_requested=str(os.getenv("RAG_V2_BACKEND", "auto")).strip().lower() or "auto", backend_actual=str(getattr(self, "backend_name", "unknown") or "unknown"))
                except Exception as exc:
                    logger.exception("[RAGObservability] 缓存 ingest 批次失败: %s", exc)
            return result

        @functools.wraps(original_search)
        def observed_search(self: HybridRAGService, query: str, *, collection: str, top_k: int = 6) -> list[dict[str, Any]]:
            store = get_rag_observability_store()
            context: SearchRunContext | None = None
            try:
                context = store.begin_search_run(query=query, collection=collection, top_k=max(1, int(top_k)), backend_requested=str(os.getenv("RAG_V2_BACKEND", "auto")).strip().lower() or "auto", backend_actual=str(getattr(self, "backend_name", "unknown") or "unknown"), route_name="hybrid_search", router_decision="hybrid_search", fallback_reason=str(getattr(self, "fallback_reason", "") or "") or None, metadata_json={"embedding_model": getattr(self, "embedding_model", None), "vector_dim": getattr(self, "vector_dim", None)})
            except Exception as exc:
                logger.exception("[RAGObservability] 创建查询运行失败: %s", exc)
            try:
                hits = original_search(self, query, collection=collection, top_k=top_k)
            except Exception as exc:
                if context is not None:
                    try:
                        store.complete_search_run(context, hits=None, error=exc)
                    except Exception as inner_exc:
                        logger.exception("[RAGObservability] 记录失败查询时出错: %s", inner_exc)
                raise
            if context is not None:
                try:
                    store.complete_search_run(context, hits=hits, error=None)
                except Exception as exc:
                    logger.exception("[RAGObservability] 记录查询完成失败: %s", exc)
            return hits

        HybridRAGService.ingest_documents = observed_ingest
        HybridRAGService.hybrid_search = observed_search
        setattr(HybridRAGService, "_rag_observability_hooks_installed", True)
        _hooks_installed = True
        return True


__all__ = [
    "NoOpRAGObservabilityStore",
    "SQLRAGObservabilityStore",
    "RAGObservabilityStore",
    "get_rag_observability_store",
    "reset_rag_observability_store_cache",
    "install_rag_observability_hooks",
]



