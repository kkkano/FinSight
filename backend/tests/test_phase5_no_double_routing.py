# -*- coding: utf-8 -*-
import importlib

import pytest
from fastapi.testclient import TestClient


def _load_app():
    import backend.api.main as main

    importlib.reload(main)
    return main.app


@pytest.fixture()
def client():
    app = _load_app()
    with TestClient(app) as test_client:
        yield test_client


def test_chat_supervisor_does_not_invoke_legacy_router(monkeypatch, client):
    import backend.conversation.router as legacy_router
    import backend.conversation.schema_router as legacy_schema_router

    def _boom(*_args, **_kwargs):
        raise AssertionError("legacy router should not be invoked from /chat/supervisor")

    monkeypatch.setattr(legacy_router.ConversationRouter, "route", _boom, raising=True)
    monkeypatch.setattr(legacy_schema_router.SchemaToolRouter, "route_query", _boom, raising=True)

    resp = client.post("/chat/supervisor", json={"query": "analyze impact", "context": {"active_symbol": "AAPL"}})
    assert resp.status_code == 200
    data = resp.json()

    trace = data.get("graph", {}).get("trace") or {}
    assert trace.get("routing_chain") == ["langgraph"]
