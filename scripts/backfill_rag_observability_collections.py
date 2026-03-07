#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text

from backend.rag.chunker import chunk_document
from backend.rag.observability_models import ChunkRecord, QueryEventRecord, QueryRunRecord, SourceDocRecord
from backend.rag.observability_runtime import _resolve_dsn
from backend.rag.observability_store import SQLRAGObservabilityStore

SCRIPT_VERSION = "2026-03-07.1"
BACKFILL_KIND = "legacy_collection_snapshot"
BACKFILL_ROUTE_NAME = "legacy_collection_backfill"
BACKFILL_EVENT_TYPE = "legacy_collection_backfilled"
BACKFILL_STAGE = "backfill"
BACKFILL_USER_ID = "system-backfill"
BACKFILL_EMAIL = "local-rag@example.com"


# ==================== 数据模型 ====================

@dataclass(frozen=True)
class CollectionCandidate:
    collection: str
    vector_doc_count: int
    active_run_count: int
    last_vector_created_at: datetime | None


@dataclass(frozen=True)
class CollectionBackfillPlan:
    collection: str
    run_id: str
    query_text: str
    vector_doc_count: int
    source_doc_count: int
    chunk_count: int
    skipped_empty_docs: int
    started_at: datetime
    finished_at: datetime


# ==================== 通用工具 ====================

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stable_id(prefix: str, *parts: object, length: int = 32) -> str:
    payload = "::".join([prefix, *[str(part or "") for part in parts]])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def _sha256_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _truncate(value: str | None, limit: int = 500) -> str | None:
    text_value = (value or "").strip()
    if not text_value:
        return None
    if len(text_value) <= limit:
        return text_value
    return text_value[: max(0, limit - 1)] + "…"


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    raw = str(value or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _load_env_file(path: Path) -> bool:
    if not path.exists():
        return False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        normalized = value.strip().strip('"').strip("'")
        os.environ[key] = normalized
    return True


def _auto_load_env_files() -> list[str]:
    loaded: list[str] = []
    for name in (".env.server", ".env"):
        path = PROJECT_ROOT / name
        if _load_env_file(path):
            loaded.append(str(path.relative_to(PROJECT_ROOT)))
    return loaded


# ==================== 切片口径 ====================

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


def _build_query_text(collection: str) -> str:
    return f"[历史回填] collection={collection} from rag_documents_v2"


# ==================== 数据读取与回填 ====================

def _fetch_collection_candidates(store: SQLRAGObservabilityStore) -> list[CollectionCandidate]:
    sql = text(
        """
        WITH vector_stats AS (
            SELECT collection, COUNT(*) AS vector_doc_count, MAX(created_at) AS last_vector_created_at
            FROM rag_documents_v2
            GROUP BY collection
        ),
        run_stats AS (
            SELECT collection, COUNT(*) AS active_run_count
            FROM rag_query_runs
            WHERE deleted_at IS NULL
            GROUP BY collection
        )
        SELECT
            vector_stats.collection,
            vector_stats.vector_doc_count,
            COALESCE(run_stats.active_run_count, 0) AS active_run_count,
            vector_stats.last_vector_created_at
        FROM vector_stats
        LEFT JOIN run_stats ON run_stats.collection = vector_stats.collection
        ORDER BY vector_stats.last_vector_created_at DESC NULLS LAST, vector_stats.collection ASC
        """
    )
    with store._engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(sql).mappings()]
    return [
        CollectionCandidate(
            collection=str(row.get("collection") or ""),
            vector_doc_count=int(row.get("vector_doc_count") or 0),
            active_run_count=int(row.get("active_run_count") or 0),
            last_vector_created_at=_parse_datetime(row.get("last_vector_created_at")),
        )
        for row in rows
        if str(row.get("collection") or "").strip()
    ]


def _fetch_vector_rows(store: SQLRAGObservabilityStore, collection: str) -> list[dict[str, Any]]:
    sql = text(
        """
        SELECT id, collection, scope, source_id, content, title, url, source, metadata, created_at, expires_at
        FROM rag_documents_v2
        WHERE collection = :collection
        ORDER BY created_at ASC, id ASC
        """
    )
    with store._engine.connect() as conn:
        return [dict(row) for row in conn.execute(sql, {"collection": collection}).mappings()]


def _build_collection_plan(store: SQLRAGObservabilityStore, collection: str) -> tuple[CollectionBackfillPlan, QueryRunRecord, QueryEventRecord, list[SourceDocRecord], list[ChunkRecord]]:
    vector_rows = _fetch_vector_rows(store, collection)
    now = _utc_now()
    started_at = now
    finished_at = now
    docs: list[SourceDocRecord] = []
    chunks: list[ChunkRecord] = []
    skipped_empty_docs = 0
    run_id = _stable_id("run", BACKFILL_KIND, collection)
    query_text = _build_query_text(collection)

    for row in vector_rows:
        content_raw = str(row.get("content") or "")
        if not content_raw.strip():
            skipped_empty_docs += 1
            continue
        metadata_json = _json_loads(row.get("metadata"))
        source_id = str(row.get("source_id") or "").strip() or _stable_id("legacysrc", collection, row.get("id"))
        created_at = _parse_datetime(row.get("created_at")) or now
        if not docs or created_at < started_at:
            started_at = created_at
        if not docs or created_at > finished_at:
            finished_at = created_at

        source_type = str(metadata_json.get("source_type") or metadata_json.get("type") or row.get("source") or "legacy_vector").strip() or "legacy_vector"
        source_name = str(metadata_json.get("source_name") or row.get("source") or "").strip() or None
        title = str(row.get("title") or metadata_json.get("title") or "").strip() or None
        url = str(row.get("url") or metadata_json.get("url") or "").strip() or None
        published_at = _parse_datetime(metadata_json.get("published_at") or metadata_json.get("published_date"))
        source_doc_id = _stable_id("doc", BACKFILL_KIND, collection, source_id)

        source_metadata = dict(metadata_json)
        source_metadata.setdefault("collection", collection)
        source_metadata.setdefault("scope", str(row.get("scope") or source_metadata.get("scope") or "persistent"))
        source_metadata.setdefault("source_id", source_id)
        source_metadata.setdefault("source_type", source_type)
        source_metadata["synthetic_backfill"] = True
        source_metadata["backfill_kind"] = BACKFILL_KIND
        source_metadata["backfill_script_version"] = SCRIPT_VERSION
        source_metadata["backfill_source_row_id"] = row.get("id")

        docs.append(
            SourceDocRecord(
                id=source_doc_id,
                run_id=run_id,
                collection=collection,
                source_id=source_id,
                source_type=source_type,
                source_name=source_name,
                url=url,
                title=title,
                published_at=published_at,
                content_raw=content_raw,
                content_preview=_truncate(content_raw, 500),
                content_length=len(content_raw),
                metadata_json=source_metadata,
                created_at=created_at,
            )
        )

        doc_type = _doc_type_from_source(source_type, content_raw)
        chunk_size, chunk_overlap = _chunk_params(doc_type)
        chunk_result = chunk_document(content_raw, doc_type=doc_type, title=title, max_chunk_size=chunk_size, overlap=chunk_overlap)
        chunk_texts = chunk_result.chunks or [content_raw]
        metadata_list = chunk_result.metadata or [{"chunk_index": 0, "total_chunks": 1, "doc_type": doc_type}]
        total_chunks = max(1, len(chunk_texts))

        for index, chunk_text in enumerate(chunk_texts):
            meta = metadata_list[index] if index < len(metadata_list) else {}
            chunk_metadata = dict(source_metadata)
            if isinstance(meta, dict):
                chunk_metadata.update(meta)
            chunks.append(
                ChunkRecord(
                    id=_stable_id("chunk", BACKFILL_KIND, collection, source_id, index),
                    run_id=run_id,
                    collection=collection,
                    source_id=source_id,
                    source_doc_id=source_doc_id,
                    chunk_index=int(meta.get("chunk_index", index) or index),
                    total_chunks=int(meta.get("total_chunks", total_chunks) or total_chunks),
                    chunk_text=chunk_text,
                    chunk_length=len(chunk_text),
                    doc_type=str(meta.get("doc_type") or doc_type),
                    chunk_strategy=doc_type,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    char_start=int(meta["char_start"]) if isinstance(meta, dict) and meta.get("char_start") is not None else None,
                    char_end=int(meta["char_end"]) if isinstance(meta, dict) and meta.get("char_end") is not None else None,
                    metadata_json=chunk_metadata,
                    created_at=created_at,
                )
            )

    plan = CollectionBackfillPlan(
        collection=collection,
        run_id=run_id,
        query_text=query_text,
        vector_doc_count=len(vector_rows),
        source_doc_count=len(docs),
        chunk_count=len(chunks),
        skipped_empty_docs=skipped_empty_docs,
        started_at=started_at,
        finished_at=finished_at,
    )
    run_record = QueryRunRecord(
        id=run_id,
        user_id=BACKFILL_USER_ID,
        session_id=f"backfill:{_stable_id('session', collection, length=12)}",
        thread_id=collection,
        query_text=query_text,
        query_text_redacted=query_text,
        query_hash=_sha256_text(query_text),
        route_name=BACKFILL_ROUTE_NAME,
        router_decision=BACKFILL_KIND,
        backend_requested="postgres",
        backend_actual="postgres",
        collection=collection,
        retrieval_k=0,
        rerank_top_n=0,
        source_doc_count=plan.source_doc_count,
        chunk_count=plan.chunk_count,
        retrieval_hit_count=0,
        rerank_hit_count=0,
        status="completed",
        metadata_json={
            "synthetic_backfill": True,
            "backfill_kind": BACKFILL_KIND,
            "backfill_script_version": SCRIPT_VERSION,
            "backfill_source": "rag_documents_v2",
            "vector_doc_count": plan.vector_doc_count,
            "source_doc_count": plan.source_doc_count,
            "chunk_count": plan.chunk_count,
        },
        started_at=plan.started_at,
        finished_at=plan.finished_at,
        latency_ms=0.0,
    )
    event_record = QueryEventRecord(
        id=_stable_id("evt", run_id, 1),
        run_id=run_id,
        seq_no=1,
        event_type=BACKFILL_EVENT_TYPE,
        stage=BACKFILL_STAGE,
        payload_json={
            "synthetic_backfill": True,
            "backfill_kind": BACKFILL_KIND,
            "backfill_script_version": SCRIPT_VERSION,
            "collection": collection,
            "vector_doc_count": plan.vector_doc_count,
            "source_doc_count": plan.source_doc_count,
            "chunk_count": plan.chunk_count,
            "skipped_empty_docs": plan.skipped_empty_docs,
        },
        created_at=plan.finished_at,
    )
    return plan, run_record, event_record, docs, chunks


def _apply_collection_backfill(store: SQLRAGObservabilityStore, run_record: QueryRunRecord, event_record: QueryEventRecord, docs: list[SourceDocRecord], chunks: list[ChunkRecord]) -> None:
    store.start_query_run(run_record)
    if docs:
        store.append_source_docs(docs)
    if chunks:
        store.append_chunks(chunks)
    store.append_query_events([event_record])


# ==================== CLI ====================

def main() -> None:
    parser = argparse.ArgumentParser(description="历史 collection observability 回填脚本")
    parser.add_argument("--dsn", default=None, help="PostgreSQL DSN；默认从环境变量自动解析")
    parser.add_argument("--env-file", action="append", default=[], help="额外加载的 env 文件，可重复传入")
    parser.add_argument("--collection", action="append", default=[], help="仅处理指定 collection，可重复传入")
    parser.add_argument("--limit", type=int, default=100, help="最多处理多少个 collection（默认 100）")
    parser.add_argument("--include-existing-runs", action="store_true", help="连已有 run 的 collection 也允许补一条 synthetic backfill run")
    parser.add_argument("--apply", action="store_true", help="真正写库；默认仅 dry-run 预览")
    args = parser.parse_args()

    loaded_env_files = _auto_load_env_files()
    for raw in args.env_file:
        _load_env_file((PROJECT_ROOT / raw).resolve())

    dsn = str(args.dsn or _resolve_dsn() or "").strip()
    if not dsn:
        raise SystemExit("未找到 PostgreSQL DSN；请传 --dsn，或设置 RAG_OBSERVABILITY_DSN / RAG_V2_POSTGRES_DSN")

    store = SQLRAGObservabilityStore(dsn=dsn)
    store.ensure_schema()

    requested_collections = [str(item).strip() for item in args.collection if str(item).strip()]
    requested_set = set(requested_collections)
    candidates = _fetch_collection_candidates(store)
    if requested_set:
        candidates = [item for item in candidates if item.collection in requested_set]
    if args.limit > 0:
        candidates = candidates[: max(1, int(args.limit))]

    results: list[dict[str, Any]] = []
    processed = 0
    applied = 0

    for candidate in candidates:
        if candidate.active_run_count > 0 and not args.include_existing_runs:
            results.append(
                {
                    "collection": candidate.collection,
                    "vector_doc_count": candidate.vector_doc_count,
                    "active_run_count": candidate.active_run_count,
                    "last_vector_created_at": candidate.last_vector_created_at,
                    "skipped": True,
                    "reason": "existing_active_runs",
                }
            )
            continue

        plan, run_record, event_record, docs, chunks = _build_collection_plan(store, candidate.collection)
        processed += 1
        if args.apply:
            _apply_collection_backfill(store, run_record, event_record, docs, chunks)
            applied += 1
        results.append(
            {
                "collection": plan.collection,
                "run_id": plan.run_id,
                "query_text": plan.query_text,
                "vector_doc_count": plan.vector_doc_count,
                "source_doc_count": plan.source_doc_count,
                "chunk_count": plan.chunk_count,
                "skipped_empty_docs": plan.skipped_empty_docs,
                "active_run_count_before": candidate.active_run_count,
                "started_at": plan.started_at,
                "finished_at": plan.finished_at,
                "applied": bool(args.apply),
            }
        )

    payload = {
        "ok": True,
        "script_version": SCRIPT_VERSION,
        "backfill_kind": BACKFILL_KIND,
        "dry_run": not args.apply,
        "include_existing_runs": bool(args.include_existing_runs),
        "requested_collections": requested_collections,
        "loaded_env_files": loaded_env_files,
        "candidates_seen": len(candidates),
        "processed": processed,
        "applied": applied,
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
