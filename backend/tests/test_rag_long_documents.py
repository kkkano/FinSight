"""长文索引单元、原文版本和父票据的无损边界。"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.rag.chunker import INDEX_CHUNK_MAX_BYTES, chunk_for_index
from backend.rag.embedder import EmbeddingService
from backend.rag.hybrid_service import HybridRAGService, RAGDocument
from backend.rag.tools import KnowledgeTools


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("RAG_RERANKER", "none")
    return HybridRAGService(backend="memory", vector_dim=1024, rrf_k=60,
                            embedder=EmbeddingService(force_backend="lexical"))


def long_document(**changes):
    values = dict(collection="kb:stock:AAPL", source_id="annual-report", scope="persistent",
                  content="  年度财务报告🙂：经营现金流改善。\n" * 2400 + "全文末尾：独特偿债线索。  ",
                  url="https://example.invalid/report", source="filing",
                  metadata={"owner": "alice", "as_of": "2026-10-01", "source_doc_id": "original-source",
                            "parent_collection": "ws:thread:tenant:alice:thread"})
    values.update(changes)
    return RAGDocument(**values)


def test_utf8_chunks_preserve_every_character_and_boundary():
    content = long_document().content
    result = chunk_for_index(content)
    assert "".join(result.chunks) == content
    assert len(result.chunks) > 1
    for chunk, meta in zip(result.chunks, result.metadata):
        assert len(chunk.encode("utf-8")) <= INDEX_CHUNK_MAX_BYTES
        assert content[meta["char_start"]:meta["char_end"]] == chunk
        assert content.encode("utf-8")[meta["byte_start"]:meta["byte_end"]].decode("utf-8") == chunk


def test_ingest_keeps_source_and_stable_permission_inheriting_chunks(store):
    doc = long_document()
    store.ingest_documents([doc])
    source = store.read_document(collection=doc.collection, source_id=doc.source_id)
    chunks = [row for row in store._store._docs.values() if row["metadata"].get("parent_source_id") == doc.source_id]
    assert source["content"] == doc.content
    assert source["metadata"]["index_state"] == "source_document"
    assert source["metadata"]["source_content_sha256"] == hashlib.sha256(doc.content.encode()).hexdigest()
    assert "".join(row["content"] for row in chunks) == doc.content
    for row in chunks:
        assert row["collection"] == doc.collection
        assert row["url"] == doc.url
        assert row["metadata"]["owner"] == "alice"
        assert row["metadata"]["source_doc_id"] == "original-source"
        assert row["metadata"]["parent_collection"] == doc.metadata["parent_collection"]
        assert "visibility" not in row["metadata"]
    ids = set(store._store._docs)
    store.ingest_documents([doc])
    assert set(store._store._docs) == ids
    status = store.index_status()
    assert status["source_documents"] == 1
    assert status["indexable"] == status["pending"] == len(chunks)
    assert status["unprepared_long_documents"] == 0
    hits = store.hybrid_search("经营现金流", collection=doc.collection, top_k=100)
    assert hits and all(row["source_id"] != doc.source_id for row in hits)


def test_legacy_preparation_is_explicit_idempotent_and_does_not_touch_expired(store, monkeypatch):
    doc = long_document(content=long_document().content.strip())
    expired = replace(doc, source_id="expired", expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    # 直接写旧形态以模拟迁移前数据，不经过新入口的自动分块。
    store._store.ingest_documents([doc, expired], embed=False)
    original = dict(store._store._docs[(doc.collection, doc.source_id)])
    expired_before = dict(store._store._docs[(expired.collection, expired.source_id)])
    with pytest.raises(ValueError, match="require_preparation"):
        store.reindex_pending()
    monkeypatch.setattr(store._embedder, "encode", lambda _: pytest.fail("prepare 不应调用向量服务"))
    result = store.prepare_long_documents()
    assert result["prepared_sources"] == 1
    assert result["created_chunks"] > 1
    update = result["source_updates"][0]
    assert update["clear_embedding"] is True
    assert update["previous_metadata"] == original["metadata"]
    allowed = {"index_state", "source_content_sha256", "chunk_strategy_version", "chunk_count"}
    assert {key: value for key, value in update["metadata"].items() if key not in allowed} == {
        key: value for key, value in original["metadata"].items() if key not in allowed}
    assert store.read_document(collection=doc.collection, source_id=doc.source_id)["content"] == original["content"]
    assert store._store._docs[(expired.collection, expired.source_id)] == expired_before
    assert store.prepare_long_documents()["prepared_sources"] == 0


def test_parent_ticket_reads_full_source_and_revalidates_content_and_owner(store):
    doc = long_document()
    store.ingest_documents([doc])
    tools = KnowledgeTools("alice", "current", service=store)
    result = tools.search_knowledge("独特偿债线索", entity="AAPL", limit=1)
    hit = result["hits"][0]
    assert hit["source_id"] == doc.source_id
    assert hit["chunk_source_id"].startswith(doc.source_id + ":chunk:")
    ticket = hit["document_id"]
    read = tools.read_document(ticket, offset=len(doc.content) - 30, max_chars=100)
    assert read["document"]["content"] == doc.content[-30:]
    assert read["document"]["total_chars"] == len(doc.content)
    assert KnowledgeTools("bob", "other", service=store).read_document(ticket)["status"] == "unavailable"
    source = store._store._docs[(doc.collection, doc.source_id)]
    source["metadata"]["owner"] = "bob"
    assert tools.read_document(ticket)["status"] == "unavailable"
    assert tools.search_knowledge("独特偿债线索", entity="AAPL")["hits"] == []
    source["metadata"]["owner"] = "alice"
    source["content"] += "修订"
    assert tools.read_document(ticket)["error"]["code"] == "document_changed"
    assert tools.search_knowledge("独特偿债线索", entity="AAPL")["hits"] == []


def test_changed_source_expires_old_chunks_and_old_ticket(store):
    doc = long_document()
    store.ingest_documents([doc])
    tools = KnowledgeTools("alice", "current", service=store)
    ticket = tools.search_knowledge("独特偿债线索", entity="AAPL", limit=1)["hits"][0]["document_id"]
    previous = set(store._store._docs) - {(doc.collection, doc.source_id)}
    changed = replace(doc, content=doc.content.replace("独特偿债线索", "全新偿债事实"))
    store.ingest_documents([changed])
    assert all(store._store._docs[key]["expires_at"] <= datetime.now(timezone.utc) for key in previous)
    assert tools.read_document(ticket)["error"]["code"] == "document_changed"
    assert tools.search_knowledge("全新偿债事实", entity="AAPL", limit=1)["hits"][0]["source_id"] == doc.source_id
    # 用户把原文缩短后，即使沿用已存元数据也必须恢复为普通索引单元。
    stored = store.read_document(collection=doc.collection, source_id=doc.source_id)
    store.ingest_documents([replace(changed, content="修订后的短报告。", metadata=stored["metadata"])])
    assert store.index_status()["source_documents"] == 0
    assert store.index_status()["indexable"] == 1
