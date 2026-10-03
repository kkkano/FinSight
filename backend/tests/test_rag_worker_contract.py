"""推理边界与向量模型身份测试，不加载模型或连接外部服务。"""
from types import SimpleNamespace

import httpx
import pytest

from backend.rag.embedder import EmbeddingResult, EmbeddingService, EmbeddingUnavailable, SparseVector
from backend.rag.hybrid_service import HybridRAGService, RAGDocument


def test_remote_embeddings_never_import_local_model_and_keep_revision(monkeypatch):
    monkeypatch.setenv("RAG_WORKER_URL", "http://worker:8010")
    monkeypatch.setenv("RAG_WORKER_TOKEN", "fixture-token")
    observed = []
    def respond(request):
        observed.append(request)
        return httpx.Response(200, json={"model_name": "bge-m3", "model_version": "revision-a",
            "dense": [[1.0] + [0.0] * 1023]})
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    service = EmbeddingService(force_backend="bge-m3")
    monkeypatch.setattr("backend.rag.embedder._get_bge_m3", lambda: pytest.fail("API加载了本地模型"))
    result = service.encode(["revenue"])
    assert result.model_version == "revision-a"
    assert service.model_name == "bge-m3"
    assert observed[0].headers["Authorization"] == "Bearer fixture-token"


def test_remote_failure_is_explicit_not_hash_fallback(monkeypatch):
    monkeypatch.setenv("RAG_WORKER_URL", "http://worker:8010")
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(
        lambda _: httpx.Response(503)), **kwargs))
    service = EmbeddingService(force_backend="bge-m3")
    with pytest.raises(EmbeddingUnavailable):
        service.encode(["a"])
    assert service.fallback_reason == "embedding_worker_unavailable"
    assert service.model_name == "unavailable"


def test_missing_dense_output_cannot_be_labeled_bge():
    from backend.rag.embedder import _BGEM3Wrapper
    wrapper = _BGEM3Wrapper()
    wrapper._model = SimpleNamespace(encode=lambda *args, **kwargs: {"lexical_weights": [{}]})
    with pytest.raises(EmbeddingUnavailable, match="bge_dense_output_missing"):
        wrapper.encode(["apple"])


def test_worker_checks_memory_before_loading_model(monkeypatch):
    from backend.rag import worker
    monkeypatch.setattr(worker._model, "_model", None)
    monkeypatch.setattr(worker, "_memory_available_mb", lambda: 300)
    monkeypatch.setattr(worker._model, "encode", lambda *_: pytest.fail("内存不足时不能加载模型"))
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        worker._encode(["a"])
    assert caught.value.status_code == 503
    assert worker.health()["status"] == "resource_limited"


class VersionedEmbedder:
    model_name = "fixture"
    dim = 16
    fallback_reason = None
    version = "a"
    unavailable = False
    def encode(self, texts):
        if self.unavailable:
            raise EmbeddingUnavailable("fixture outage")
        return EmbeddingResult(dense=[[1.0] + [0.0] * 15 for _ in texts],
            sparse=[SparseVector({}) for _ in texts], model_name=self.model_name, dim=16, model_version=self.version)


def test_equal_dimensions_with_different_versions_never_share_dense_ranking():
    embedder = VersionedEmbedder()
    service = HybridRAGService(backend="memory", vector_dim=16, rrf_k=40, embedder=embedder)
    service.ingest_documents([RAGDocument(collection="fixture", source_id="first", scope="ephemeral", content="apple")])
    embedder.version = "b"
    assert service.hybrid_search("unrelated", collection="fixture") == []
    hit = service.hybrid_search("apple", collection="fixture")[0]
    assert hit["dense_rank"] is None
    assert hit["sparse_rank"] is not None


def test_worker_failure_keeps_documents_searchable_lexically():
    embedder = VersionedEmbedder()
    embedder.unavailable = True
    service = HybridRAGService(backend="memory", vector_dim=16, rrf_k=40, embedder=embedder)
    assert service.ingest_documents([RAGDocument(collection="fixture", source_id="first", scope="ephemeral", content="apple revenue")])["indexed"] == 1
    hit = service.hybrid_search("apple", collection="fixture")[0]
    assert hit["metadata"]["embedding_identity"] is None
    assert hit["dense_rank"] is None


def test_worker_auth_and_actual_inference_health(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.rag import worker
    monkeypatch.setenv("RAG_WORKER_TOKEN", "fixture-token")
    monkeypatch.setattr(worker._model, "_model", SimpleNamespace(model=SimpleNamespace(config=SimpleNamespace(_commit_hash="fixture-sha"))))
    monkeypatch.setattr(worker._model, "encode", lambda texts: EmbeddingResult(
        dense=[[1.0] + [0.0] * 1023 for _ in texts], sparse=[SparseVector({}) for _ in texts], model_name="bge-m3", dim=1024))
    with TestClient(worker.app) as client:
        assert client.post("/encode", json={"texts": ["a"]}).status_code == 401
        response = client.post("/encode", json={"texts": ["a"]}, headers={"Authorization": "Bearer fixture-token"})
        assert response.status_code == 200
        assert response.json()["model_version"].startswith("fixture-sha:")
        assert client.get("/health").json()["inference_verified"] is True


def test_lexical_rag_readiness_is_explicit(monkeypatch):
    from backend.api.system_router import _component_ready
    ready, value = _component_ready({"status": "degraded", "semantic_ready": False, "lexical_ready": True},
        required=True, allow_degraded=False, default_error_code="rag_unavailable")
    assert not ready
    assert value["semantic_ready"] is False
    assert value["lexical_ready"] is True
