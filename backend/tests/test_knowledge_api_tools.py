"""知识工具与托管模型边界：不访问网络、数据库或本地模型。"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.rag.api_provider import HTTPEmbeddingProvider, HTTPRerankProvider, ProviderUnavailable
from backend.rag.embedder import EmbeddingService, EmbeddingUnavailable, embedding_identity, lexical_search_text, lexical_tsquery
from backend.rag.hybrid_service import HybridRAGService, RAGDocument
from backend.rag.layering import build_thread_working_set_collection
from backend.rag.reranker import RerankerService
from backend.rag.tools import KnowledgeTools


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING", "remote_api")
    monkeypatch.setenv("RAG_EMBEDDING_API_URL", "https://embedding.example.test/v1/embeddings")
    monkeypatch.setenv("RAG_EMBEDDING_MODEL", "fixture-embedding")
    monkeypatch.setenv("RAG_EMBEDDING_API_KEY", "private-fixture-key")
    monkeypatch.setenv("RAG_EMBEDDING_DIM", "16")
    monkeypatch.setenv("RAG_EMBEDDING_MODEL_VERSION", "generation-a")
    monkeypatch.delenv("RAG_WORKER_URL", raising=False)
    real = httpx.Client

    def use(response):
        monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(response), **kw))
    return use


def test_default_lexical_never_loads_local_models(monkeypatch):
    monkeypatch.delenv("RAG_EMBEDDING", raising=False)
    monkeypatch.delenv("RAG_WORKER_URL", raising=False)
    monkeypatch.setattr(EmbeddingService, "_check_bge", lambda _: pytest.fail("加载了本地模型"))
    service = EmbeddingService()
    assert service.model_name == "lexical"
    assert service.is_hash_fallback is False
    with pytest.raises(EmbeddingUnavailable, match="lexical"):
        service.encode(["经营现金流"])
    assert service.worker_health()["lexical_ready"] is True


def test_hosted_embeddings_validate_order_and_identity(remote):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "model": "fixture-embedding", "model_version": "provider-r1",
            "data": [{"index": 1, "embedding": [2.0] * 16}, {"index": 0, "embedding": [1.0] * 16}],
        })
    remote(respond)
    result = EmbeddingService().encode(["cash flow", "现金流"])
    assert result.dense[0] == [1.0] * 16
    assert result.dense[1] == [2.0] * 16
    assert result.model_name == "fixture-embedding"
    assert result.model_version.startswith("api-v1:")
    assert requests[0].url.path == "/v1/embeddings"
    assert requests[0].headers["Authorization"] == "Bearer private-fixture-key"
    assert json.loads(requests[0].content)["input"] == ["cash flow", "现金流"]
    assert "private-fixture-key" not in repr(HTTPEmbeddingProvider.from_env())


@pytest.mark.parametrize("payload", [
    {"model": "changed", "data": [{"index": 0, "embedding": [1.0] * 16}]},
    {"data": [{"index": 1, "embedding": [1.0] * 16}]},
    {"data": [{"index": 0, "embedding": [True] * 16}]},
    {"data": [{"index": 0, "embedding": [0.0] * 16}]},
    {"data": [{"index": 0, "embedding": [1.0] * 15}]},
    {"data": []},
])
def test_invalid_hosted_vectors_are_explicit_not_hash(remote, payload):
    remote(lambda _: httpx.Response(200, json=payload))
    service = EmbeddingService()
    with pytest.raises(EmbeddingUnavailable):
        service.encode(["a"])
    assert service.fallback_reason
    assert service.model_name != "hash"


def test_hosted_failure_does_not_disclose_provider_body(remote):
    remote(lambda _: httpx.Response(401, json={"error": "private-fixture-key was rejected"}))
    with pytest.raises(EmbeddingUnavailable) as exc:
        EmbeddingService().encode(["a"])
    assert "private-fixture-key" not in str(exc.value)
    assert str(exc.value) == "embedding_api_request_failed"


def test_identity_changes_with_explicit_generation(remote, monkeypatch):
    remote(lambda _: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * 16}]}))
    first = EmbeddingService().encode(["a"])
    monkeypatch.setenv("RAG_EMBEDDING_MODEL_VERSION", "generation-b")
    second = EmbeddingService().encode(["a"])
    assert embedding_identity(first) != embedding_identity(second)


def test_revision_cannot_change_between_batches(remote, monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING_BATCH_SIZE", "1")
    replies = iter(["revision-a", "revision-b"])
    remote(lambda _: httpx.Response(200, json={
        "revision": next(replies), "data": [{"index": 0, "embedding": [1.0] * 16}],
    }))
    with pytest.raises(EmbeddingUnavailable, match="revision_changed"):
        EmbeddingService().encode(["a", "b"])


def test_hosted_redirect_does_not_forward_credentials(remote):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(307, headers={"Location": "https://other.example.test/steal"})
    remote(respond)
    with pytest.raises(EmbeddingUnavailable):
        EmbeddingService().encode(["a"])
    assert len(seen) == 1


def test_unconfigured_remote_keeps_records_lexically_readable(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDING", "remote_api")
    monkeypatch.delenv("RAG_EMBEDDING_API_KEY", raising=False)
    embedder = EmbeddingService()
    service = HybridRAGService(backend="memory", vector_dim=1024, rrf_k=60, embedder=embedder)
    service.ingest_documents([RAGDocument(collection="test", source_id="1", scope="persistent",
                                       content="公司经营现金流持续改善，经营利润增长。")])
    hits = service.hybrid_search("现金流", collection="test")
    assert len(hits) == 1
    assert hits[0]["dense_rank"] is None
    assert hits[0]["metadata"]["index_state"] == "lexical_only"


def test_chinese_lexical_queries_are_segmented_without_operator_injection():
    assert "现金 金流" in lexical_search_text("经营现金流")
    assert lexical_tsquery("现金流 | ! ' OR") == "现金 | 金流 | or"


def test_reranker_is_disabled_without_import_or_network(monkeypatch):
    monkeypatch.delenv("RAG_RERANKER", raising=False)
    monkeypatch.setattr("backend.rag.reranker._get_reranker", lambda: pytest.fail("加载重排模型"))
    service = RerankerService()
    assert service.is_enabled is False
    assert service.rerank("a", [{"content": "b"}, {"content": "c"}], top_n=1) == [{"content": "b"}]


def test_hosted_reranker_scores_reorder_documents(remote, monkeypatch):
    monkeypatch.setenv("RAG_RERANKER", "remote_api")
    monkeypatch.setenv("RAG_RERANK_API_URL", "https://ranking.example.test/v1/rerank")
    monkeypatch.setenv("RAG_RERANK_MODEL", "fixture-rerank")
    monkeypatch.setenv("RAG_RERANK_API_KEY", "ranking-fixture")
    remote(lambda _: httpx.Response(200, json={"results": [
        {"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1},
    ]}))
    rows = RerankerService().rerank("现金流", [{"content": "price"}, {"content": "cashflow"}], top_n=2)
    assert [row["content"] for row in rows] == ["cashflow", "price"]
    assert rows[0]["rerank_score"] == 0.9


@pytest.fixture
def knowledge_store():
    return HybridRAGService(backend="memory", vector_dim=1024, rrf_k=60,
                            embedder=EmbeddingService(force_backend="lexical"))


def test_knowledge_scope_filters_private_kb_and_other_session(knowledge_store):
    store = knowledge_store
    store.ingest_documents([
        RAGDocument(collection="kb:stock:AAPL", source_id="public", scope="persistent",
                    content="Apple revenue annual report", metadata={"visibility": "public"}),
        RAGDocument(collection="kb:stock:AAPL", source_id="private", scope="persistent",
                    content="Apple revenue private notes", metadata={"owner": "bob"}),
        RAGDocument(collection="kb:stock:AAPL", source_id="legacy", scope="persistent",
                    content="Apple revenue unclassified notes"),
        RAGDocument(collection=build_thread_working_set_collection("other"), source_id="other",
                    scope="ephemeral", content="Apple revenue other session"),
    ])
    tools = KnowledgeTools("alice", "current", service=store)
    result = tools.search_knowledge("Apple revenue", entity="AAPL")
    assert result["evidence_refs"] == ["public"]
    assert result["hits"][0]["content_is_untrusted"] is True
    assert result["hits"][0]["retrieval_method"] == "lexical"


def test_document_ticket_is_scoped_and_revalidates_current_access(knowledge_store):
    store = knowledge_store
    collection = build_thread_working_set_collection("current")
    doc = RAGDocument(collection=collection, source_id="statement", scope="ephemeral",
                      content="现金流第一段。现金流第二段。", metadata={"owner": "alice"})
    store.ingest_documents([doc])
    tools = KnowledgeTools("alice", "current", service=store)
    ticket = tools.search_knowledge("现金流")["hits"][0]["document_id"]
    assert tools.read_document(ticket, max_chars=7)["document"]["has_more"] is True
    assert KnowledgeTools("bob", "other", service=store).read_document(ticket)["status"] == "unavailable"
    # 权限变化不能使用之前已发出的票据绕过。
    doc.metadata["owner"] = "bob"
    store.ingest_documents([doc])
    assert tools.read_document(ticket)["status"] == "unavailable"


def test_expired_and_updated_documents_require_new_search(knowledge_store):
    store = knowledge_store
    collection = build_thread_working_set_collection("current")
    doc = RAGDocument(collection=collection, source_id="statement", scope="ephemeral", content="cashflow old")
    store.ingest_documents([doc])
    tools = KnowledgeTools("alice", "current", service=store)
    ticket = tools.search_knowledge("cashflow")["hits"][0]["document_id"]
    doc = replace(doc, content="cashflow revised")
    store.ingest_documents([doc])
    assert tools.read_document(ticket)["error"]["code"] == "document_changed"
    doc = replace(doc, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    store.ingest_documents([doc])
    assert tools.search_knowledge("cashflow")["hits"] == []


def test_memory_tool_reads_only_scoped_snapshot_and_strips_secret_fields(knowledge_store):
    tools = KnowledgeTools("alice", "current", service=knowledge_store,
                           memory_context={"preferences": {"risk": "conservative", "api_key": "private-value"}})
    result = tools.search_memory("conservative")
    assert len(result["hits"]) == 1
    serialized = json.dumps(result)
    assert "private-value" not in serialized
    assert tools.read_document(result["hits"][0]["document_id"])["status"] == "ok"

def test_production_lexical_readiness_does_not_encode(monkeypatch, knowledge_store):
    from backend.api import app_factory
    monkeypatch.setattr(app_factory, "_is_production_runtime", lambda: True)
    monkeypatch.setenv("RAG_EMBEDDING", "lexical")
    monkeypatch.setenv("RAG_RERANKER", "none")
    knowledge_store.backend_name = "postgres"
    monkeypatch.setattr("backend.rag.hybrid_service.get_rag_service", lambda: knowledge_store)
    monkeypatch.setattr(knowledge_store._embedder, "encode", lambda _: pytest.fail("词法就绪不应编码"))
    result = app_factory._rag_health_uncached()
    assert result["status"] == "ok"
    assert result["lexical_ready"] is True
    assert result["semantic_ready"] is False
    assert result["reranker"] == "disabled"


def test_hosted_health_uses_real_last_identity_without_probe_requests(remote, monkeypatch):
    from backend.api import app_factory
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * 16}]})
    remote(respond)
    monkeypatch.setenv("RAG_RERANKER", "none")
    service = HybridRAGService(backend="memory", vector_dim=16, rrf_k=60, embedder=EmbeddingService())
    service.ingest_documents([RAGDocument(collection="test", source_id="source", scope="persistent", content="cash flow")])
    service.backend_name = "postgres"
    monkeypatch.setattr(app_factory, "_is_production_runtime", lambda: True)
    monkeypatch.setattr("backend.rag.hybrid_service.get_rag_service", lambda: service)
    result = app_factory._rag_health_uncached()
    assert result["status"] == "ok"
    assert result["semantic_ready"] is True
    assert result["full_ready"] is True
    assert result["index"]["pending"] == 0
    assert len(seen) == 1


def test_unverified_remote_health_preserves_lexical_availability(remote, monkeypatch):
    from backend.api import app_factory
    remote(lambda _: pytest.fail("健康检查不能消耗API额度"))
    service = HybridRAGService(backend="memory", vector_dim=16, rrf_k=60, embedder=EmbeddingService())
    service.backend_name = "postgres"
    monkeypatch.setattr(app_factory, "_is_production_runtime", lambda: True)
    monkeypatch.setattr("backend.rag.hybrid_service.get_rag_service", lambda: service)
    result = app_factory._rag_health_uncached()
    assert result["status"] == "degraded"
    assert result["lexical_ready"] is True
    assert result["semantic_ready"] is False


