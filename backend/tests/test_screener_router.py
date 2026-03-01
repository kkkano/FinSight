# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import screener_router as screener_router_module


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(screener_router_module.screener_router)
    return TestClient(app)


def test_screener_run_endpoint(monkeypatch):
    captured = {}

    def _fake_screen_stocks(**kwargs):
        captured.update(kwargs)
        return {"success": True, "items": [], "count": 0, "market": kwargs.get("market", "US")}

    monkeypatch.setattr(screener_router_module, "screen_stocks", _fake_screen_stocks)

    client = _build_client()
    response = client.post(
        "/api/screener/run",
        json={
            "market": "US",
            "filters": {"sector": "Technology"},
            "limit": 15,
            "page": 2,
            "sort_by": "price",
            "sort_order": "asc",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert captured["market"] == "US"
    assert captured["filters"]["sector"] == "Technology"
    assert captured["limit"] == 15
    assert captured["page"] == 2
    assert captured["sort_by"] == "price"
    assert captured["sort_order"] == "asc"


def test_screener_filter_meta_endpoint():
    client = _build_client()
    response = client.get("/api/screener/filters/meta")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "US" in payload["markets"]
    assert "marketCap" in payload["sort_by"]
    assert "sector" in payload["filter_keys"]
