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
