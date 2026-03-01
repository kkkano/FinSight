# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import cn_market_router as cn_market_router_module


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(cn_market_router_module.cn_market_router)
    return TestClient(app)


def test_cn_market_router_endpoints(monkeypatch):
    monkeypatch.setattr(cn_market_router_module, "fetch_fund_flow", lambda limit=20: {"success": True, "items": [], "count": 0})
    monkeypatch.setattr(cn_market_router_module, "fetch_northbound", lambda limit=20: {"success": True, "items": [], "count": 0})
    monkeypatch.setattr(cn_market_router_module, "fetch_limit_board", lambda limit=20: {"success": True, "items": [], "count": 0})
    monkeypatch.setattr(cn_market_router_module, "fetch_lhb", lambda limit=20: {"success": True, "items": [], "count": 0})
    monkeypatch.setattr(
        cn_market_router_module,
        "fetch_concept_map",
        lambda keyword="", limit=20: {"success": True, "items": [{"concept_name": "AI"}], "count": 1},
    )

    client = _build_client()

    assert client.get("/api/cn/market/fund-flow").status_code == 200
    assert client.get("/api/cn/market/northbound").status_code == 200
    assert client.get("/api/cn/market/limit-board").status_code == 200
    assert client.get("/api/cn/market/lhb").status_code == 200

    concept_resp = client.get("/api/cn/market/concept", params={"keyword": "AI", "limit": 20})
    assert concept_resp.status_code == 200
    payload = concept_resp.json()
    assert payload["success"] is True
    assert payload["count"] == 1
