"""将 RAG 文档与观测表纳入正式 migration。

Revision ID: 20260716_0003
Revises: 20260715_0002
Create Date: 2026-07-16
"""
from __future__ import annotations

from alembic import op


revision = "20260716_0003"
down_revision = "20260715_0002"
branch_labels = None
depends_on = None


def _execute(sql: str) -> None:
    op.execute(sql)


def upgrade() -> None:
    _execute("CREATE EXTENSION IF NOT EXISTS vector")
    _execute(
        """
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
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            embedding VECTOR(1024) NOT NULL,
            search_vector TSVECTOR,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NULL,
            UNIQUE(collection, source_id)
        )
        """
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
        _execute(ddl)
    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_rag_v2_collection ON rag_documents_v2(collection)",
        "CREATE INDEX IF NOT EXISTS idx_rag_v2_layer ON rag_documents_v2(layer)",
        "CREATE INDEX IF NOT EXISTS idx_rag_v2_scope ON rag_documents_v2(scope)",
        "CREATE INDEX IF NOT EXISTS idx_rag_v2_entity_scope ON rag_documents_v2(entity_scope)",
        "CREATE INDEX IF NOT EXISTS idx_rag_v2_entity_key ON rag_documents_v2(entity_key)",
        "CREATE INDEX IF NOT EXISTS idx_rag_v2_doc_fingerprint ON rag_documents_v2(doc_fingerprint)",
        "CREATE INDEX IF NOT EXISTS idx_rag_v2_expires_at ON rag_documents_v2(expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_rag_v2_search_vector ON rag_documents_v2 USING GIN(search_vector)",
        "CREATE INDEX IF NOT EXISTS idx_rag_v2_embedding ON rag_documents_v2 USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)",
    ):
        _execute(ddl)

    _execute(
        """
        CREATE TABLE IF NOT EXISTS rag_query_runs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            thread_id TEXT NULL,
            query_text TEXT NOT NULL,
            query_text_redacted TEXT NULL,
            query_hash TEXT NOT NULL,
            route_name TEXT NULL,
            router_decision TEXT NULL,
            backend_requested TEXT NOT NULL,
            backend_actual TEXT NOT NULL,
            collection TEXT NULL,
            retrieval_k INTEGER NOT NULL DEFAULT 0,
            rerank_top_n INTEGER NOT NULL DEFAULT 0,
            source_doc_count INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            retrieval_hit_count INTEGER NOT NULL DEFAULT 0,
            rerank_hit_count INTEGER NOT NULL DEFAULT 0,
            fallback_reason TEXT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            error_message TEXT NULL,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NULL,
            latency_ms DOUBLE PRECISION NULL,
            deleted_at TIMESTAMPTZ NULL,
            deleted_by TEXT NULL,
            delete_reason TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    _execute(
        "ALTER TABLE rag_query_runs ADD COLUMN IF NOT EXISTS "
        "metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS rag_query_events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
            seq_no INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            stage TEXT NOT NULL,
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL,
            deleted_at TIMESTAMPTZ NULL,
            deleted_by TEXT NULL,
            delete_reason TEXT NULL,
            UNIQUE(run_id, seq_no)
        )
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS rag_source_docs (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
            source_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_name TEXT NULL,
            url TEXT NULL,
            title TEXT NULL,
            published_at TIMESTAMPTZ NULL,
            content_raw TEXT NOT NULL,
            content_preview TEXT NULL,
            content_length INTEGER NOT NULL DEFAULT 0,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            deleted_at TIMESTAMPTZ NULL,
            deleted_by TEXT NULL,
            delete_reason TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(run_id, source_id)
        )
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
            source_doc_id TEXT NOT NULL REFERENCES rag_source_docs(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            total_chunks INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            chunk_length INTEGER NOT NULL,
            doc_type TEXT NOT NULL,
            chunk_strategy TEXT NOT NULL,
            chunk_size INTEGER NOT NULL,
            chunk_overlap INTEGER NOT NULL,
            char_start INTEGER NULL,
            char_end INTEGER NULL,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            deleted_at TIMESTAMPTZ NULL,
            deleted_by TEXT NULL,
            delete_reason TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE(source_doc_id, chunk_index)
        )
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS rag_retrieval_hits (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
            chunk_id TEXT NULL,
            collection TEXT NULL,
            source_id TEXT NULL,
            source_doc_id TEXT NULL,
            scope TEXT NULL,
            dense_rank INTEGER NULL,
            dense_score DOUBLE PRECISION NULL,
            sparse_rank INTEGER NULL,
            sparse_score DOUBLE PRECISION NULL,
            rrf_score DOUBLE PRECISION NULL,
            selected_for_rerank BOOLEAN NOT NULL DEFAULT false,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            deleted_at TIMESTAMPTZ NULL,
            deleted_by TEXT NULL,
            delete_reason TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS rag_rerank_hits (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
            chunk_id TEXT NULL,
            input_rank INTEGER NOT NULL,
            output_rank INTEGER NOT NULL,
            rerank_score DOUBLE PRECISION NULL,
            selected_for_answer BOOLEAN NOT NULL DEFAULT false,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            deleted_at TIMESTAMPTZ NULL,
            deleted_by TEXT NULL,
            delete_reason TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(run_id, input_rank),
            UNIQUE(run_id, output_rank)
        )
        """
    )
    _execute(
        """
        CREATE TABLE IF NOT EXISTS rag_fallback_events (
            id TEXT PRIMARY KEY,
            run_id TEXT NULL REFERENCES rag_query_runs(id) ON DELETE CASCADE,
            reason_code TEXT NOT NULL,
            reason_text TEXT NULL,
            backend_before TEXT NULL,
            backend_after TEXT NOT NULL,
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL,
            deleted_at TIMESTAMPTZ NULL,
            deleted_by TEXT NULL,
            delete_reason TEXT NULL
        )
        """
    )

    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_rag_query_runs_started_at ON rag_query_runs(started_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_rag_query_runs_user_id ON rag_query_runs(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_rag_query_runs_session_id ON rag_query_runs(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_rag_query_runs_status ON rag_query_runs(status)",
        "CREATE INDEX IF NOT EXISTS idx_rag_query_runs_query_hash ON rag_query_runs(query_hash)",
        "CREATE INDEX IF NOT EXISTS idx_rag_query_runs_deleted_at ON rag_query_runs(deleted_at)",
        "CREATE INDEX IF NOT EXISTS idx_rag_query_events_run_id_seq ON rag_query_events(run_id,seq_no)",
        "CREATE INDEX IF NOT EXISTS idx_rag_query_events_event_type ON rag_query_events(event_type)",
        "CREATE INDEX IF NOT EXISTS idx_rag_source_docs_run_id ON rag_source_docs(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_rag_source_docs_source_type ON rag_source_docs(source_type)",
        "CREATE INDEX IF NOT EXISTS idx_rag_source_docs_deleted_at ON rag_source_docs(deleted_at)",
        "CREATE INDEX IF NOT EXISTS idx_rag_chunks_run_id ON rag_chunks(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_rag_chunks_source_doc_id ON rag_chunks(source_doc_id)",
        "CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_type ON rag_chunks(doc_type)",
        "CREATE INDEX IF NOT EXISTS idx_rag_chunks_deleted_at ON rag_chunks(deleted_at)",
        "CREATE INDEX IF NOT EXISTS idx_rag_retrieval_hits_run_id ON rag_retrieval_hits(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_rag_retrieval_hits_rrf_score ON rag_retrieval_hits(run_id,rrf_score DESC)",
        "CREATE INDEX IF NOT EXISTS idx_rag_retrieval_hits_chunk_id ON rag_retrieval_hits(chunk_id)",
        "CREATE INDEX IF NOT EXISTS idx_rag_rerank_hits_run_id ON rag_rerank_hits(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_rag_rerank_hits_output_rank ON rag_rerank_hits(run_id,output_rank)",
        "CREATE INDEX IF NOT EXISTS idx_rag_fallback_events_created_at ON rag_fallback_events(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_rag_fallback_events_run_id ON rag_fallback_events(run_id)",
    ):
        _execute(ddl)


def downgrade() -> None:
    _execute("DROP TABLE IF EXISTS rag_rerank_hits")
    _execute("DROP TABLE IF EXISTS rag_retrieval_hits")
    _execute("DROP TABLE IF EXISTS rag_chunks")
    _execute("DROP TABLE IF EXISTS rag_source_docs")
    _execute("DROP TABLE IF EXISTS rag_query_events")
    _execute("DROP TABLE IF EXISTS rag_fallback_events")
    _execute("DROP TABLE IF EXISTS rag_query_runs")
    _execute("DROP TABLE IF EXISTS rag_documents_v2")
