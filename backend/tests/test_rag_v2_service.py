# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.rag.hybrid_service import HybridRAGService, RAGDocument


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_hybrid_rag_memory_ingest_and_search_ranks_relevant_doc():
    service = HybridRAGService.for_testing(backend="memory")
    base = _now()

    docs = [
        RAGDocument(
            collection="session:t1",
            scope="ephemeral",
            source_id="doc_apple",
            content="Apple revenue guidance improved with strong iPhone demand and services growth.",
            title="Apple earnings highlights",
            source="news",
            metadata={"ticker": "AAPL"},
            expires_at=base + timedelta(hours=2),
        ),
        RAGDocument(
            collection="session:t1",
            scope="ephemeral",
            source_id="doc_msft",
            content="Microsoft cloud momentum remains healthy with Azure enterprise expansion.",
            title="Microsoft cloud update",
            source="news",
            metadata={"ticker": "MSFT"},
            expires_at=base + timedelta(hours=2),
        ),
    ]

    stats = service.ingest_documents(docs)
    assert stats["indexed"] == 2

    hits = service.hybrid_search("Apple iPhone revenue outlook", collection="session:t1", top_k=3)
    assert hits, "hybrid search should return at least one hit"
    assert hits[0]["source_id"] == "doc_apple"
    assert hits[0]["rrf_score"] > 0


def test_hybrid_rag_memory_ttl_and_cleanup():
    service = HybridRAGService.for_testing(backend="memory")
    base = _now()

    stats = service.ingest_documents(
        [
            RAGDocument(
                collection="session:t2",
                scope="ephemeral",
                source_id="expired",
                content="old stale news",
                source="news",
                expires_at=base - timedelta(minutes=1),
            ),
            RAGDocument(
                collection="session:t2",
                scope="ephemeral",
                source_id="alive",
                content="fresh filing analysis for valuation and balance sheet",
                source="filing",
                expires_at=base + timedelta(hours=1),
            ),
        ]
    )
    assert stats["indexed"] == 2

    hits = service.hybrid_search("valuation balance sheet", collection="session:t2", top_k=5)
    ids = [h["source_id"] for h in hits]
    assert "alive" in ids
    assert "expired" not in ids

    cleaned = service.cleanup_expired()
    assert cleaned >= 1


def test_hybrid_rag_memory_upsert_by_collection_and_source_id():
    service = HybridRAGService.for_testing(backend="memory")
    base = _now()

    service.ingest_documents(
        [
            RAGDocument(
                collection="session:t3",
                scope="ephemeral",
                source_id="dup",
                content="initial content",
                source="selection",
                expires_at=base + timedelta(hours=1),
            )
        ]
    )
    service.ingest_documents(
        [
            RAGDocument(
                collection="session:t3",
                scope="ephemeral",
                source_id="dup",
                content="updated content with stronger relevance",
                source="selection",
                expires_at=base + timedelta(hours=1),
            )
        ]
    )

    hits = service.hybrid_search("stronger relevance", collection="session:t3", top_k=2)
    assert hits
    assert hits[0]["content"].startswith("updated content")


def test_hybrid_rag_count_documents_excludes_expired():
    service = HybridRAGService.for_testing(backend="memory")
    base = _now()

    service.ingest_documents(
        [
            RAGDocument(
                collection="session:t4",
                scope="ephemeral",
                source_id="alive_doc",
                content="active content",
                source="selection",
                expires_at=base + timedelta(hours=2),
            ),
            RAGDocument(
                collection="session:t4",
                scope="ephemeral",
                source_id="expired_doc",
                content="expired content",
                source="selection",
                expires_at=base - timedelta(minutes=1),
            ),
        ]
    )

    assert service.count_documents() >= 1
    service.cleanup_expired()
    assert service.count_documents() == 1


def test_cleanup_stale_filings_removes_old_filing_docs():
    service = HybridRAGService.for_testing(backend="memory")
    old_created_at = _now() - timedelta(days=730)

    service.ingest_documents(
        [
            RAGDocument(
                collection="session:t5",
                scope="persistent",
                source_id="old_filing",
                content="old filing content",
                source="filing",
                metadata={"type": "filing"},
                created_at=old_created_at,
                expires_at=None,
            ),
            RAGDocument(
                collection="session:t5",
                scope="persistent",
                source_id="fresh_filing",
                content="fresh filing content",
                source="filing",
                metadata={"type": "filing"},
                created_at=_now(),
                expires_at=None,
            ),
        ]
    )

    deleted = service.cleanup_stale_filings(older_than_days=365)
    assert deleted >= 1

    hits = service.hybrid_search("filing content", collection="session:t5", top_k=5)
    ids = [hit["source_id"] for hit in hits]
    assert "old_filing" not in ids
    assert "fresh_filing" in ids


def test_postgres_service_auto_aligns_embedder_to_existing_store_dim(monkeypatch):
    monkeypatch.delenv("RAG_EMBEDDING", raising=False)
    monkeypatch.setenv("RAG_HASH_DIM", "96")

    class DummyPostgresStore:
        def __init__(self, *, dsn, vector_dim, rrf_k, embedder=None):
            self.dsn = dsn
            self.vector_dim = vector_dim
            self.rrf_k = rrf_k
            self.embedder = embedder

        def ingest_documents(self, docs):
            return {"indexed": 0, "skipped": 0}

        def hybrid_search(self, query, *, collection, top_k):
            return []

        def hybrid_search_many(self, query, *, collections, top_k):
            return []

        def cleanup_expired(self):
            return 0

    monkeypatch.setattr("backend.rag.hybrid_service._detect_postgres_vector_dimension", lambda dsn: 96)
    monkeypatch.setattr("backend.rag.hybrid_service._PostgresHybridStore", DummyPostgresStore)

    service = HybridRAGService(
        backend="postgres",
        vector_dim=0,
        rrf_k=60,
        postgres_dsn="postgresql://demo/test",
        allow_memory_fallback=False,
    )

    assert service.backend_name == "postgres"
    assert service.vector_dim == 96
    assert service.embedding_model == "hash"


def test_postgres_service_raises_clear_error_when_explicit_embedder_conflicts(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING", "hash")
    monkeypatch.setenv("RAG_HASH_DIM", "96")
    monkeypatch.setattr("backend.rag.hybrid_service._detect_postgres_vector_dimension", lambda dsn: 1024)

    from backend.rag.embedder import reset_embedding_service

    reset_embedding_service()
    with pytest.raises(ValueError, match="vector dimension mismatch"):
        HybridRAGService(
            backend="postgres",
            vector_dim=0,
            rrf_k=60,
            postgres_dsn="postgresql://demo/test",
            allow_memory_fallback=False,
        )



def test_hybrid_rag_service_auto_aligns_to_existing_postgres_vector_dim(monkeypatch):
    monkeypatch.delenv("RAG_EMBEDDING", raising=False)
    monkeypatch.setattr("backend.rag.hybrid_service._detect_postgres_vector_dimension", lambda dsn: 96)

    class _FakeCurrentEmbedder:
        model_name = "bge-m3"
        dim = 1024

    captured: dict[str, object] = {}

    class _FakePostgresStore:
        def __init__(self, *, dsn, vector_dim, rrf_k, embedder):
            captured["dsn"] = dsn
            captured["vector_dim"] = vector_dim
            captured["rrf_k"] = rrf_k
            captured["embedder_model"] = embedder.model_name
            captured["embedder_dim"] = embedder.dim

        def ingest_documents(self, docs):
            return {"indexed": 0, "skipped": 0}

        def hybrid_search(self, query, *, collection, top_k):
            return []

        def hybrid_search_many(self, query, *, collections, top_k):
            return []

        def cleanup_expired(self):
            return 0

    monkeypatch.setattr("backend.rag.hybrid_service.get_embedding_service", lambda: _FakeCurrentEmbedder())
    monkeypatch.setattr("backend.rag.hybrid_service._PostgresHybridStore", _FakePostgresStore)

    service = HybridRAGService(
        backend="postgres",
        vector_dim=0,
        rrf_k=60,
        postgres_dsn="postgresql://example.local/test",
        allow_memory_fallback=False,
    )

    assert service.backend_name == "postgres"
    assert service.vector_dim == 96
    assert service.embedding_model == "hash"
    assert captured["vector_dim"] == 96
    assert captured["embedder_model"] == "hash"
    assert captured["embedder_dim"] == 96


def test_hybrid_rag_service_rejects_explicit_postgres_vector_dim_mismatch(monkeypatch):
    monkeypatch.setattr("backend.rag.hybrid_service._detect_postgres_vector_dimension", lambda dsn: 96)

    with pytest.raises(ValueError, match="schema expects 96"):
        HybridRAGService(
            backend="postgres",
            vector_dim=1024,
            rrf_k=60,
            postgres_dsn="postgresql://example.local/test",
            allow_memory_fallback=False,
            embedder=__import__("backend.rag.embedder", fromlist=["EmbeddingService"]).EmbeddingService(force_backend="hash"),
        )
