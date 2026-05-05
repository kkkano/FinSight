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
    import sys

    for module_name in ("backend.conversation.router", "backend.conversation.schema_router"):
        sys.modules.pop(module_name, None)

    resp = client.post("/chat/supervisor", json={"query": "analyze impact", "context": {"active_symbol": "AAPL"}})
    assert resp.status_code == 200
    data = resp.json()

    trace = data.get("graph", {}).get("trace") or {}
    assert trace.get("routing_chain") == ["langgraph"]
    assert "backend.conversation.router" not in sys.modules
    assert "backend.conversation.schema_router" not in sys.modules
