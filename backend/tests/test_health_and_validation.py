# -*- coding: utf-8 -*-
"""
P0 稳定性回归测试：健康检查与基本请求校验。

目标：
- /health 作为核心依赖 readiness，已删除的根路径不再伪装健康检查；
- /api/execute 在收到空 query 时由 Pydantic 校验层直接返回 422，
  避免空请求进入主链路。
"""

import os
import sys
from types import SimpleNamespace

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


def test_root_route_is_not_a_second_health_contract(client):
    resp = client.get("/")
    assert resp.status_code == 404


def test_health_endpoint_exposes_only_core_readiness(client):
    resp = client.get("/health")
    assert resp.status_code in {200, 503}
    data = resp.json()
    assert data.get("status") in ("healthy", "degraded")
    components = data.get("components") or {}
    assert set(components) == {
        "authentication",
        "database",
        "market_data",
        "langgraph_runner",
        "checkpointer",
        "llm",
    }
    assert all(set(component).issubset({"status", "error_code"}) for component in components.values())
    assert components["checkpointer"]["status"] in ("ok", "initializing", "error")
    serialized = repr(data).lower()
    for forbidden in ("embedding_model", "vector_dim", "doc_count", "fallback_reason", "recent_runs"):
        assert forbidden not in serialized
    assert "timestamp" in data


def _build_system_health_client(
    *,
    authentication,
    database,
    market_data,
    llm_available=True,
    llm_required=None,
    rag=None,
):
    from fastapi import FastAPI

    from backend.api.system_router import SystemRouterDeps, create_system_router

    app = FastAPI()
    app.include_router(
        create_system_router(
            SystemRouterDeps(
                metrics_enabled=False,
                metrics_payload=lambda: ("", "text/plain"),
                graph_runner_ready=lambda: True,
                get_graph_checkpointer_info=lambda: {"backend": "postgres"},
                get_startup_result=lambda: SimpleNamespace(
                    llm_available=llm_available,
                    **({"llm_required": llm_required} if llm_required is not None else {}),
                ),
                get_authentication_health=lambda: authentication,
                get_database_health=lambda: database,
                get_market_data_health=lambda: market_data,
                get_rag_health=(lambda: rag) if rag is not None else None,
            )
        )
    )
    return TestClient(app)


def test_health_is_healthy_only_when_all_core_dependencies_are_ready():
    with _build_system_health_client(
        authentication={"status": "ok"},
        database={"status": "ok"},
        market_data={"status": "ok"},
    ) as isolated_client:
        resp = isolated_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_health_combines_stable_auth_database_market_and_llm_failures():
    with _build_system_health_client(
        authentication={"status": "error", "error_code": "strong_auth_required"},
        database={"status": "error", "error_code": "database_schema_outdated"},
        market_data={"status": "error", "error_code": "trusted_market_provider_unconfigured"},
        llm_available=False,
    ) as isolated_client:
        resp = isolated_client.get("/health")
    assert resp.status_code == 503
    payload = resp.json()
    assert payload["status"] == "degraded"
    assert payload["components"]["authentication"]["error_code"] == "strong_auth_required"
    assert payload["components"]["database"]["error_code"] == "database_schema_outdated"
    assert payload["components"]["market_data"]["error_code"] == "trusted_market_provider_unconfigured"
    assert payload["components"]["llm"]["error_code"] == "llm_unavailable"


def test_livez_does_not_probe_dependencies():
    calls = []
    from fastapi import FastAPI
    from backend.api.system_router import SystemRouterDeps, create_system_router

    isolated = FastAPI()
    isolated.include_router(
        create_system_router(
            SystemRouterDeps(
                metrics_enabled=False,
                metrics_payload=lambda: ("", "text/plain"),
                graph_runner_ready=lambda: calls.append("graph") or False,
                get_graph_checkpointer_info=lambda: calls.append("checkpoint") or {},
                get_startup_result=lambda: calls.append("llm") or None,
                get_authentication_health=lambda: calls.append("auth") or {"status": "error"},
                get_database_health=lambda: calls.append("db") or {"status": "error"},
                get_market_data_health=lambda: calls.append("market") or {"status": "error"},
            )
        )
    )
    with TestClient(isolated) as isolated_client:
        response = isolated_client.get("/livez")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"
    assert calls == []


def test_readyz_reports_component_failures_without_secrets(monkeypatch):
    monkeypatch.setenv("FINSIGHT_RUNTIME_PROFILE", "production")
    with _build_system_health_client(
        authentication={"status": "ok"},
        database={"status": "ok"},
        market_data={"status": "ok"},
        llm_available=False,
        rag={
            "status": "error",
            "error_code": "rag_backend_unavailable",
            "backend": "memory",
            "reason": "postgresql://user:password@db.example/finsight",
        },
    ) as isolated_client:
        response = isolated_client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert "llm" in payload["failed_components"]
    assert "rag" in payload["failed_components"]
    # Probe responses must never echo a DSN or credentials.
    assert "password" not in repr(payload).lower()


def test_readyz_allows_optional_llm_in_test_profile(monkeypatch):
    monkeypatch.setenv("FINSIGHT_RUNTIME_PROFILE", "test")
    monkeypatch.setenv("FINSIGHT_LLM_REQUIRED", "false")
    with _build_system_health_client(
        authentication={"status": "disabled"},
        database={"status": "disabled"},
        market_data={"status": "disabled"},
        llm_available=False,
        rag={"status": "degraded", "backend": "memory", "reason": "test profile"},
    ) as isolated_client:
        response = isolated_client.get("/readyz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert payload["components"]["llm"]["status"] == "disabled"


def test_production_readyz_ignores_optional_llm_result(monkeypatch):
    monkeypatch.setenv("FINSIGHT_RUNTIME_PROFILE", "production")
    monkeypatch.setenv("FINSIGHT_LLM_REQUIRED", "false")
    with _build_system_health_client(
        authentication={"status": "ok"},
        database={"status": "ok"},
        market_data={"status": "ok"},
        llm_available=False,
        llm_required=False,
        rag={"status": "ok", "backend": "postgres", "embedding": "bge-m3", "reranker": "ok"},
    ) as isolated_client:
        response = isolated_client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["components"]["llm"] == {
        "status": "error",
        "error_code": "llm_unavailable",
        "required": True,
    }


def test_rag_readiness_probe_is_cached_and_uses_real_encoder(monkeypatch):
    from backend.api import app_factory

    class FakeEmbedder:
        model_name = "bge-m3"

        def __init__(self):
            self.calls = 0

        def encode_single(self, text):
            self.calls += 1
            return [0.1, 0.2, 0.3], {"text": 1.0}

    embedder = FakeEmbedder()
    service = type("FakeRag", (), {"_embedder": embedder, "vector_dim": 3})()
    monkeypatch.setattr(app_factory, "_is_production_runtime", lambda: True)
    # Patch imports used inside the uncached probe without loading real models.
    import backend.rag.hybrid_service as hybrid
    import backend.rag.reranker as reranker
    monkeypatch.setattr(hybrid, "get_rag_service", lambda: service)
    monkeypatch.setattr(
        reranker,
        "get_reranker_service",
        lambda: type("FakeReranker", (), {"is_enabled": True})(),
    )
    monkeypatch.setenv("FINSIGHT_RUNTIME_PROFILE", "production")
    monkeypatch.setenv("RAG_V2_BACKEND", "postgres")
    monkeypatch.setenv("RAG_EMBEDDING", "bge-m3")
    app_factory.reset_rag_readiness_probe_for_testing()

    first = app_factory.warm_rag_readiness_probe(force=True)
    second = app_factory.warm_rag_readiness_probe()

    assert first["status"] == "error"  # fake service lacks a postgres backend
    assert first["error_code"] == "rag_backend_unavailable"
    assert second == first
    assert embedder.calls == 1


def test_rag_readiness_fails_when_production_encoder_degrades_to_hash(monkeypatch):
    from backend.api import app_factory
    import backend.rag.hybrid_service as hybrid
    import backend.rag.reranker as reranker

    class FakeEmbedder:
        model_name = "hash"

        def encode_single(self, _text):
            return [0.1, 0.2, 0.3], {}

    service = type("FakeRag", (), {"_embedder": FakeEmbedder(), "vector_dim": 3, "backend_name": "postgres", "embedding_model": "hash", "fallback_reason": None})()
    monkeypatch.setattr(app_factory, "_is_production_runtime", lambda: True)
    monkeypatch.setattr(hybrid, "get_rag_service", lambda: service)
    monkeypatch.setattr(reranker, "get_reranker_service", lambda: type("R", (), {"is_enabled": True})())
    monkeypatch.setenv("FINSIGHT_RUNTIME_PROFILE", "production")
    monkeypatch.setenv("RAG_V2_BACKEND", "postgres")
    monkeypatch.setenv("RAG_EMBEDDING", "bge-m3")
    app_factory.reset_rag_readiness_probe_for_testing()

    result = app_factory.warm_rag_readiness_probe(force=True)

    assert result["status"] == "error"
    assert result["error_code"] == "rag_embedding_degraded"


def test_non_production_rag_probe_skips_model_and_database(monkeypatch):
    from backend.api import app_factory

    monkeypatch.setattr(app_factory, "_is_production_runtime", lambda: False)
    monkeypatch.setenv("FINSIGHT_RUNTIME_PROFILE", "test")
    app_factory.reset_rag_readiness_probe_for_testing()
    result = app_factory._rag_health_uncached()
    assert result["status"] == "disabled"
    assert result["reason"] == "rag_probe_skipped_non_production"


def test_failed_rag_probe_retries_after_short_ttl(monkeypatch):
    from backend.api import app_factory

    clock = [100.0]
    calls: list[int] = []
    monkeypatch.setattr(app_factory.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("RAG_PROBE_FAILURE_TTL_SECONDS", "30")

    def probe():
        calls.append(1)
        if len(calls) == 1:
            return {"status": "error", "error_code": "rag_backend_unavailable"}
        return {"status": "ok", "backend": "postgres", "embedding": "bge-m3"}

    monkeypatch.setattr(app_factory, "_rag_health_uncached", probe)
    app_factory.reset_rag_readiness_probe_for_testing()

    first = app_factory.warm_rag_readiness_probe()
    within_ttl = app_factory.warm_rag_readiness_probe()
    clock[0] += 31
    recovered = app_factory.warm_rag_readiness_probe()
    after_recovery = app_factory.warm_rag_readiness_probe()

    assert first["status"] == "error"
    assert within_ttl == first
    assert recovered["status"] == "ok"
    assert after_recovery == recovered
    assert len(calls) == 2


def test_authentication_health_probes_configured_jwks(monkeypatch: pytest.MonkeyPatch):
    from backend.services import system_health

    monkeypatch.setattr(
        system_health,
        "security_settings",
        lambda: SimpleNamespace(supabase_auth_required=True, supabase_url="https://example.supabase.co"),
    )
    monkeypatch.setattr(system_health, "is_production_mode", lambda: True)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    called = []
    monkeypatch.setattr(system_health, "ensure_auth_verifier_ready", lambda: called.append(True))

    assert system_health.authentication_health() == {"status": "ok"}
    assert called == [True]


def test_authentication_health_reports_unavailable_jwks(monkeypatch: pytest.MonkeyPatch):
    from backend.security.supabase_auth import AuthConfigurationError
    from backend.services import system_health

    monkeypatch.setattr(
        system_health,
        "security_settings",
        lambda: SimpleNamespace(supabase_auth_required=True, supabase_url="https://missing.supabase.co"),
    )
    monkeypatch.setattr(system_health, "is_production_mode", lambda: True)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)

    def unavailable() -> None:
        raise AuthConfigurationError("无法获取 Supabase JWKS")

    monkeypatch.setattr(system_health, "ensure_auth_verifier_ready", unavailable)

    assert system_health.authentication_health() == {
        "status": "error",
        "error_code": "auth_verifier_unavailable",
    }


def test_chat_empty_query_validation(client):
    """
    空 query 应在进入处理函数前被 Pydantic 拦截，返回 422。
    这样可以避免空请求进入主链路，提升稳健性。
    """
    resp = client.post("/api/execute", json={"query": ""})
    assert resp.status_code == 422


def test_legacy_chat_endpoint_removed(client):
    """旧 /chat 端点应已移除，返回 404。"""
    resp = client.post("/chat", json={"query": "AAPL 现在多少钱"})
    assert resp.status_code == 404


def test_legacy_supervisor_endpoint_removed(client):
    resp = client.post("/chat/supervisor", json={"query": "AAPL 现在多少钱"})
    assert resp.status_code == 404
