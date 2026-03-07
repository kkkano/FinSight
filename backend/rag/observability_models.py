# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class QueryRunRecord:
    id: str
    user_id: str
    session_id: str
    thread_id: Optional[str]
    query_text: str
    query_text_redacted: Optional[str] = None
    query_hash: str = ""
    route_name: Optional[str] = None
    router_decision: Optional[str] = None
    backend_requested: str = "auto"
    backend_actual: str = "memory"
    collection: Optional[str] = None
    retrieval_k: int = 0
    rerank_top_n: int = 0
    source_doc_count: int = 0
    chunk_count: int = 0
    retrieval_hit_count: int = 0
    rerank_hit_count: int = 0
    fallback_reason: Optional[str] = None
    status: str = "running"
    error_message: Optional[str] = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=utc_now)
    finished_at: Optional[datetime] = None
    latency_ms: Optional[float] = None
    deleted_at: Optional[datetime] = None
    delete_reason: Optional[str] = None


@dataclass(frozen=True)
class QueryEventRecord:
    id: str
    run_id: str
    seq_no: int
    event_type: str
    stage: str
    payload_json: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class SourceDocRecord:
    id: str
    run_id: str
    collection: Optional[str]
    source_id: str
    source_type: str
    source_name: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    published_at: Optional[datetime] = None
    content_raw: str = ""
    content_preview: Optional[str] = None
    content_length: int = 0
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    deleted_at: Optional[datetime] = None
    delete_reason: Optional[str] = None


@dataclass(frozen=True)
class ChunkRecord:
    id: str
    run_id: str
    collection: Optional[str]
    source_id: Optional[str]
    source_doc_id: str
    chunk_index: int
    total_chunks: int
    chunk_text: str
    chunk_length: int
    doc_type: str
    chunk_strategy: str
    chunk_size: int
    chunk_overlap: int
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    deleted_at: Optional[datetime] = None
    delete_reason: Optional[str] = None


@dataclass(frozen=True)
class RetrievalHitRecord:
    id: str
    run_id: str
    chunk_id: Optional[str]
    collection: Optional[str] = None
    source_id: Optional[str] = None
    source_doc_id: Optional[str] = None
    scope: Optional[str] = None
    dense_rank: Optional[int] = None
    dense_score: Optional[float] = None
    sparse_rank: Optional[int] = None
    sparse_score: Optional[float] = None
    rrf_score: Optional[float] = None
    selected_for_rerank: bool = False
    title: Optional[str] = None
    url: Optional[str] = None
    content_preview: Optional[str] = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    deleted_at: Optional[datetime] = None
    delete_reason: Optional[str] = None


@dataclass(frozen=True)
class RerankHitRecord:
    id: str
    run_id: str
    chunk_id: Optional[str]
    input_rank: int
    output_rank: int
    rerank_score: Optional[float] = None
    selected_for_answer: bool = False
    title: Optional[str] = None
    url: Optional[str] = None
    content_preview: Optional[str] = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    deleted_at: Optional[datetime] = None
    delete_reason: Optional[str] = None


@dataclass(frozen=True)
class FallbackEventRecord:
    id: str
    run_id: Optional[str]
    reason_code: str
    reason_text: Optional[str] = None
    backend_before: Optional[str] = None
    backend_after: str = "memory"
    payload_json: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class PendingIngestDocRecord:
    collection: str
    source_id: str
    source_type: str
    source_name: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    published_at: Optional[datetime] = None
    content_raw: str = ""
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class PendingIngestBatch:
    id: str
    collection: str
    backend_requested: str
    backend_actual: str
    ingest_stats: dict[str, Any] = field(default_factory=dict)
    docs: list[PendingIngestDocRecord] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class SearchRunContext:
    run: QueryRunRecord
    pending_batch: Optional[PendingIngestBatch] = None
    source_doc_map: dict[str, str] = field(default_factory=dict)
    primary_chunk_map: dict[str, str] = field(default_factory=dict)
    materialized_source_doc_count: int = 0
    materialized_chunk_count: int = 0
    started_monotonic: float = 0.0


__all__ = [
    "utc_now",
    "QueryRunRecord",
    "QueryEventRecord",
    "SourceDocRecord",
    "ChunkRecord",
    "RetrievalHitRecord",
    "RerankHitRecord",
    "FallbackEventRecord",
    "PendingIngestDocRecord",
    "PendingIngestBatch",
    "SearchRunContext",
]
