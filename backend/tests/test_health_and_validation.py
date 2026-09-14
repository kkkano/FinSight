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


def _build_system_health_client(*, authentication, database, market_data, llm_available=True):
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
                get_startup_result=lambda: SimpleNamespace(llm_available=llm_available),
                get_authentication_health=lambda: authentication,
                get_database_health=lambda: database,
                get_market_data_health=lambda: market_data,
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
