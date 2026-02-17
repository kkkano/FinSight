# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
