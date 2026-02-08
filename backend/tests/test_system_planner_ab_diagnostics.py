# -*- coding: utf-8 -*-

import importlib
import os

from fastapi.testclient import TestClient


def _load_app():
    import backend.api.main as main

    importlib.reload(main)
    return main.app


def test_planner_ab_diagnostics_endpoint_returns_shape():
    os.environ["API_AUTH_ENABLED"] = "false"
    app = _load_app()
    client = TestClient(app)

    response = client.get("/diagnostics/planner-ab")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "ok"

    data = payload.get("data") or {}
    assert "enabled" in data
    assert "split_percent" in data
    assert isinstance(data.get("variants"), dict)
    assert "A" in data.get("variants", {})
    assert "B" in data.get("variants", {})


def test_planner_ab_diagnostics_alias_endpoint_returns_shape():
    os.environ["API_AUTH_ENABLED"] = "false"
    app = _load_app()
    client = TestClient(app)

    response = client.get("/diagnostics/planner_ab")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") == "ok"
