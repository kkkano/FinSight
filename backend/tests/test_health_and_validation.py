# -*- coding: utf-8 -*-
"""
P0 稳定性回归测试：健康检查与基本请求校验。

目标：
- / 与 /health 端点始终可用，用于监控与存活检查；
- /chat/supervisor 在收到空 query 时由 Pydantic 校验层直接返回 422，
  避免空请求进入主链路。
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.api.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_root_health_endpoint(client):
    """根路径应返回 healthy 状态和时间戳。"""
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "healthy"
    assert "timestamp" in data
    assert "message" in data


def test_health_endpoint(client):
    """/health 端点应返回 healthy 状态。"""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ("healthy", "degraded")
    components = data.get("components") or {}
    checkpointer = components.get("checkpointer") or {}
    assert checkpointer.get("status") == "ok"
    assert checkpointer.get("schema_version") == "checkpointer.v1"
    assert checkpointer.get("backend") in ("sqlite", "postgres", "memory")
    rag = components.get("rag") or {}
    if rag:
        assert rag.get("status") in ("ok", "degraded", "error")
        assert "backend" in rag or rag.get("status") == "error"
        assert "embedding_model" in rag or rag.get("status") == "error"
        assert "vector_dim" in rag or rag.get("status") == "error"
        assert "doc_count" in rag or rag.get("status") == "error"
    assert "timestamp" in data


def test_health_rag_fallback_reason_marks_component_degraded(client, monkeypatch):
    """
    P1-10 残留缺口：RAG 存在 fallback_reason（如 embedding hash 降级）时，
    /health 的 components.rag.status 必须诚实显示 degraded，
    但整体 status 仍为 healthy（RAG 降级后服务仍可用）。
    """
    import backend.rag.hybrid_service as hybrid_service

    class _FakeRagService:
        backend_name = "memory"
        embedding_model = "hash"
        vector_dim = 256
        fallback_reason = "embedding degraded to hash (requested 'bge-m3', FlagEmbedding unavailable)"

        def count_documents(self):
            return 0

    monkeypatch.setattr(hybrid_service, "get_rag_service", lambda: _FakeRagService())
    # 期望 backend 不是 postgres，避免触发「期望 postgres 但实际不是」的整体降级逻辑
    monkeypatch.setenv("RAG_V2_BACKEND", "auto")

    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    # 整体仍健康——RAG 组件降级不影响服务可用性
    assert data.get("status") == "healthy"
    rag = (data.get("components") or {}).get("rag") or {}
    assert rag.get("status") == "degraded"
    assert "fallback_reason" in rag
    assert rag["fallback_reason"]


def test_health_rag_no_fallback_reason_stays_ok(client, monkeypatch):
    """
    无 fallback_reason 时 rag.status 保持 ok（已有行为不回归）。
    """
    import backend.rag.hybrid_service as hybrid_service

    class _FakeRagService:
        backend_name = "memory"
        embedding_model = "bge-m3"
        vector_dim = 1024
        fallback_reason = None

        def count_documents(self):
            return 3

    monkeypatch.setattr(hybrid_service, "get_rag_service", lambda: _FakeRagService())
    monkeypatch.setenv("RAG_V2_BACKEND", "auto")

    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    rag = (data.get("components") or {}).get("rag") or {}
    assert rag.get("status") == "ok"
    assert "fallback_reason" not in rag


def test_chat_empty_query_validation(client):
    """
    空 query 应在进入处理函数前被 Pydantic 拦截，返回 422。
    这样可以避免空请求进入主链路，提升稳健性。
    """
    resp = client.post("/chat/supervisor", json={"query": ""})
    assert resp.status_code == 422


def test_legacy_chat_endpoint_removed(client):
    """旧 /chat 端点应已移除，返回 404。"""
    resp = client.post("/chat", json={"query": "AAPL 现在多少钱"})
    assert resp.status_code == 404
