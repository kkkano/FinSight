"""验证知识工具在权限过滤后重排，失败时保留可回读的原检索结果。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from backend.rag.api_provider import HTTPRerankProvider
from backend.rag.embedder import EmbeddingService
from backend.rag.hybrid_service import HybridRAGService, RAGDocument
from backend.rag.tools import KnowledgeTools
from backend.rag.reranker import get_reranker_service, reset_reranker_service


@pytest.fixture
def store():
    return HybridRAGService(backend="memory", vector_dim=1024, rrf_k=60,
                            embedder=EmbeddingService(force_backend="lexical"))


@pytest.fixture
def remote_rerank(monkeypatch):
    monkeypatch.setenv("RAG_RERANKER", "remote_api")
    monkeypatch.setenv("RAG_RERANK_API_URL", "https://ranking.example.test/v1/rerank")
    monkeypatch.setenv("RAG_RERANK_MODEL", "fixture-rerank")
    monkeypatch.setenv("RAG_RERANK_API_KEY", "fixture-key")
    real_client = httpx.Client

    def install(responder):
        monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(
            transport=httpx.MockTransport(responder), **kw))
    return install


def document(source_id, **overrides):
    values = {"collection": "kb:stock:AAPL", "source_id": source_id, "scope": "persistent",
              "content": "现金流资料 " + source_id, "source": "filing",
              "metadata": {"visibility": "public", "as_of": "2026-10-01"}}
    values.update(overrides)
    return RAGDocument(**values)


def test_remote_rerank_sends_only_permitted_current_sources(store, remote_rerank):
    store.ingest_documents([
        document("allowed-a"), document("allowed-b"),
        document("other-owner", metadata={"owner": "bob", "as_of": "2026-10-01"}),
        document("unclassified", metadata={"as_of": "2026-10-01"}),
        document("expired", expires_at=datetime.now(timezone.utc) - timedelta(days=1)),
        document("old", metadata={"visibility": "public", "as_of": "2025-01-01"}),
        document("other-source", source="social"),
        document("other-entity", collection="kb:stock:MSFT"),
    ])
    sent = []

    def respond(request):
        body = json.loads(request.content)
        sent.extend(body["documents"])
        assert set(body["documents"]) == {"现金流资料 allowed-a", "现金流资料 allowed-b"}
        return httpx.Response(200, json={"results": [
            {"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]})

    remote_rerank(respond)
    tools = KnowledgeTools("alice", "current", service=store)
    result = tools.search_knowledge("现金流", entity="AAPL", sources=["filing"],
                                    time_range={"start": "2026-01-01", "end": "2026-12-31"})
    assert result["quality"]["rerank_used"] is True
    assert [hit["rerank_score"] for hit in result["hits"]] == [0.9, 0.1]
    assert result["hits"][0]["content"] == sent[1]
    assert all(hit["rerank_used"] for hit in result["hits"])
    first = result["hits"][0]
    read = tools.read_document(first["document_id"])
    assert read["document"]["source_id"] == first["source_id"]
    assert read["document"]["content"] == first["content"]


def test_remote_rerank_caps_external_candidates_at_32(store, remote_rerank):
    store.ingest_documents([document(str(index)) for index in range(40)])
    seen = []

    def respond(request):
        body = json.loads(request.content)
        seen.append(len(body["documents"]))
        assert body["top_n"] == 12
        return httpx.Response(200, json={"results": [
            {"index": index, "relevance_score": 1 - index / 32} for index in range(12)]})

    remote_rerank(respond)
    result = KnowledgeTools("alice", "current", service=store).search_knowledge(
        "现金流", entity="AAPL", limit=12)
    assert seen == [32]
    assert len(result["hits"]) == 12
    assert result["quality"]["rerank_used"] is True


def test_remote_rerank_failure_is_explicit_and_preserves_order(store, remote_rerank, monkeypatch):
    store.ingest_documents([document("first"), document("second")])
    tools = KnowledgeTools("alice", "current", service=store)
    monkeypatch.setenv("RAG_RERANKER", "none")
    original = tools.search_knowledge("现金流", entity="AAPL")
    monkeypatch.setenv("RAG_RERANKER", "remote_api")
    remote_rerank(lambda _: httpx.Response(503, json={"error": "private-provider-body"}))
    result = tools.search_knowledge("现金流", entity="AAPL")
    assert result["status"] == "ok"
    assert result["evidence_refs"] == original["evidence_refs"]
    assert result["data_refs"] == original["data_refs"]
    assert result["quality"]["rerank_used"] is False
    assert all(hit["rerank_score"] is None and not hit["rerank_used"] for hit in result["hits"])
    assert any("重排服务暂不可用" in note for note in result["quality"]["limitations"])
    assert "private-provider-body" not in json.dumps(result)


def test_default_and_empty_results_do_not_call_rerank(store, monkeypatch):
    monkeypatch.delenv("RAG_RERANKER", raising=False)
    monkeypatch.setattr(HTTPRerankProvider, "from_env", lambda: pytest.fail("不应调用外部重排"))
    tools = KnowledgeTools("alice", "current", service=store)
    store.ingest_documents([document("available")])
    result = tools.search_knowledge("现金流", entity="AAPL")
    assert result["evidence_refs"] == ["available"]
    assert result["quality"]["rerank_used"] is False
    monkeypatch.setenv("RAG_RERANKER", "remote_api")
    assert tools.search_knowledge("现金流", entity="MSFT")["hits"] == []

def test_legacy_kb_parent_proves_only_same_tenant_owner_access():
    from backend.rag.tools import KnowledgeTools
    tools=KnowledgeTools("alice","public:alice:current")
    base={"collection":"kb:stock:AAPL","source_id":"s","content":"report"}
    assert tools._permitted({**base,"metadata":{"parent_collection":"ws:thread:public:alice:old"}})
    assert tools._permitted({**base,"metadata":{"owner":"alice"}})
    assert not tools._permitted({**base,"metadata":{"parent_collection":"ws:thread:public:bob:old"}})
    assert not tools._permitted({**base,"metadata":{"parent_collection":"ws:thread:other:alice:old"}})
    assert not tools._permitted({**base,"metadata":{}})
    assert not tools._permitted({**base,"metadata":{"owner":"bob","parent_collection":"ws:thread:public:alice:old"}})


def test_remote_candidate_budget_includes_query_and_keeps_documents_whole(remote_rerank):
    reset_reranker_service()
    query = "q" * 2000
    documents = [{"source_id": str(index), "content": str(index).zfill(4) + "x" * 5996}
                 for index in range(25)]
    small = {"source_id": "fits-tail", "content": "tail" + "y" * 3996}
    documents.append(small)
    seen = []

    def respond(request):
        body = json.loads(request.content)
        seen.append(body)
        assert len(body["documents"]) == 20
        assert len(body["query"]) + sum(map(len, body["documents"])) == 120000
        assert body["documents"] == [doc["content"] for doc in documents[:19]] + [small["content"]]
        return httpx.Response(200, json={"results": [{"index": 19, "relevance_score": 0.9}]})

    remote_rerank(respond)
    result = get_reranker_service().rerank(query, documents, top_n=1)
    assert len(seen) == 1
    assert result[0]["source_id"] == "fits-tail"
    assert result[0]["content"] == small["content"]


def test_startup_search_and_health_share_reranker_failure_and_recovery(store, remote_rerank, monkeypatch):
    from backend.api import app_factory
    from backend.rag.readiness import verify_hosted_retrieval_startup

    reset_reranker_service()
    store.ingest_documents([document("cashflow")])
    monkeypatch.setenv("RAG_EMBEDDING", "remote_api")
    monkeypatch.setattr("backend.rag.hybrid_service.get_rag_service", lambda: store)
    original_encode = store._embedder.encode
    monkeypatch.setattr(store._embedder, "encode", lambda _: SimpleNamespace(dim=1024))
    requests = []
    state = {"fail": False}

    def respond(request):
        requests.append(request)
        if state["fail"]:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}]})

    remote_rerank(respond)
    assert verify_hosted_retrieval_startup()["reranker"] == "ok"
    singleton = get_reranker_service()
    monkeypatch.setattr(store._embedder, "encode", original_encode)
    monkeypatch.setattr(store._embedder, "worker_health", lambda: {
        "inference_verified": True, "status": "ok", "embedding_identity": "fixture:1024"})
    monkeypatch.setattr(store, "index_status", lambda _: {"pending": 0})
    monkeypatch.setattr(store, "backend_name", "postgres")
    monkeypatch.setattr(app_factory, "_is_production_runtime", lambda: True)
    assert app_factory._rag_health_uncached()["full_ready"] is True
    assert len(requests) == 1  # health 本身不消耗 API 调用。

    state["fail"] = True
    result = KnowledgeTools("alice", "current", service=store).search_knowledge("现金流", entity="AAPL")
    assert result["quality"]["rerank_used"] is False
    assert get_reranker_service() is singleton
    health = app_factory._rag_health_uncached()
    assert health["reranker"] == "degraded" and health["full_ready"] is False
    assert len(requests) == 2

    state["fail"] = False
    KnowledgeTools("alice", "current", service=store).search_knowledge("现金流", entity="AAPL")
    assert app_factory._rag_health_uncached()["full_ready"] is True
    assert len(requests) == 3


def test_singleton_preserves_current_provider_config_and_resets_verification(remote_rerank, monkeypatch):
    reset_reranker_service()
    monkeypatch.setenv("RAG_RERANKER", "none")
    disabled = get_reranker_service()
    assert disabled.health() == {"status": "disabled", "provider": "none"}
    monkeypatch.setenv("RAG_RERANKER", "remote_api")
    enabled = get_reranker_service()
    assert enabled is not disabled
    remote_rerank(lambda _: httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}]}))
    enabled.rerank("cashflow", [{"content": "cashflow"}])
    assert get_reranker_service() is enabled and enabled.health()["status"] == "ok"
    monkeypatch.setenv("RAG_RERANK_MODEL", "another-model")
    replacement = get_reranker_service()
    assert replacement is not enabled
    assert replacement.health() == {"status": "unverified", "provider": "remote_api"}
