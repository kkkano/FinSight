"""在隔离测试库验证真实 pgvector 模型隔离与词法降级。"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.rag.embedder import EmbeddingResult, EmbeddingUnavailable, SparseVector
from backend.rag.hybrid_service import HybridRAGService, RAGDocument
from backend.services.database import normalize_sync_postgres_dsn


class FixtureEmbedding:
    model_name = "fixture"
    dim = 1024
    fallback_reason = None
    version = "revision-a"
    unavailable = False

    def encode(self, texts):
        if self.unavailable:
            raise EmbeddingUnavailable("fixture outage")
        return EmbeddingResult(dense=[[1.0] + [0.0] * 1023 for _ in texts],
            sparse=[SparseVector({}) for _ in texts], model_name=self.model_name, dim=self.dim, model_version=self.version)


@pytest.fixture
def rag():
    raw = os.getenv("FINSIGHT_TEST_POSTGRES_DSN", "")
    if not raw:
        pytest.skip("未配置隔离 PostgreSQL 测试库")
    dsn = normalize_sync_postgres_dsn(raw)
    if not str(make_url(dsn).database or "").startswith("finsight_test_"):
        pytest.fail("拒绝使用业务数据库")
    engine = create_engine(dsn)
    embedding = FixtureEmbedding()
    service = HybridRAGService(backend="postgres", vector_dim=1024, rrf_k=40,
        postgres_dsn=dsn, embedder=embedding, allow_memory_fallback=False)
    collection = "test:rag:" + uuid.uuid4().hex
    try:
        yield service, embedding, collection, engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM rag_documents_v2 WHERE collection=:collection"), {"collection": collection})
        service._store._engine.dispose()
        engine.dispose()


def document(collection, source, content):
    return RAGDocument(collection=collection, scope="ephemeral", source_id=source, content=content)


def test_pgvector_same_dimensions_are_filtered_by_actual_model_revision(rag):
    service, embedding, collection, _engine = rag
    service.ingest_documents([document(collection, "old", "apple")])
    embedding.version = "revision-b"
    service.ingest_documents([document(collection, "new", "microsoft")])
    hits = service.hybrid_search("unmatched", collection=collection)
    assert [hit["source_id"] for hit in hits] == ["new"]


def test_pgvector_outage_inserts_null_embedding_and_keeps_lexical_search(rag):
    service, embedding, collection, engine = rag
    embedding.unavailable = True
    service.ingest_documents([document(collection, "lexical", "apple revenue")])
    with engine.connect() as connection:
        assert connection.execute(text("SELECT embedding IS NULL FROM rag_documents_v2 WHERE collection=:collection"), {"collection": collection}).scalar_one()
    hits = service.hybrid_search("apple", collection=collection)
    assert hits[0]["source_id"] == "lexical"
    assert hits[0]["dense_rank"] is None


def test_pgvector_unknown_legacy_embedding_is_not_assumed_to_match(rag):
    service, _embedding, collection, engine = rag
    service.ingest_documents([document(collection, "legacy", "apple revenue")])
    with engine.begin() as connection:
        connection.execute(text("UPDATE rag_documents_v2 SET metadata=metadata-'embedding_identity' WHERE collection=:collection"), {"collection": collection})
    assert service.hybrid_search("unmatched", collection=collection) == []
    hit = service.hybrid_search("apple", collection=collection)[0]
    assert hit["dense_rank"] is None and hit["sparse_rank"] is not None


def test_reingest_during_outage_preserves_valid_vector_for_unchanged_text(rag):
    service, embedding, collection, engine = rag
    doc = document(collection, "same", "apple revenue")
    service.ingest_documents([doc])
    embedding.unavailable = True
    service.ingest_documents([doc])
    with engine.connect() as connection:
        vector_exists, model = connection.execute(text("SELECT embedding IS NOT NULL,metadata->>'embedding_identity' FROM rag_documents_v2 WHERE collection=:collection"), {"collection": collection}).one()
    assert vector_exists and model == "fixture:revision-a:1024"
