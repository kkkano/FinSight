# -*- coding: utf-8 -*-
import os
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.api.main import app  # noqa: E402


def test_tools_capabilities_returns_selected_tools():
    client = TestClient(app)
    response = client.get(
        "/api/tools/capabilities",
        params={"market": "US", "operation": "qa", "analysis_depth": "report"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("success") is True
    assert isinstance(payload.get("tools"), list)
    assert isinstance(payload.get("selected_tools"), list)
    assert "get_stock_price" in payload.get("selected_tools", [])
    assert "get_official_macro_releases" in payload.get("selected_tools", [])
    assert payload.get("analysis_depth") == "report"


def test_tools_capabilities_reports_env_and_market_filters(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    client = TestClient(app)

    us_response = client.get(
        "/api/tools/capabilities",
        params={"market": "US", "operation": "qa", "analysis_depth": "report"},
    )
    assert us_response.status_code == 200
    us_payload = us_response.json()
    us_tools = us_payload.get("tools") or []
    sec_tool = next((item for item in us_tools if item.get("name") == "get_sec_filings"), None)
    assert sec_tool is not None
    assert sec_tool.get("env_ready") is False
    assert "SEC_USER_AGENT" in (sec_tool.get("missing_env") or [])

    cn_response = client.get(
        "/api/tools/capabilities",
        params={"market": "CN", "operation": "qa", "analysis_depth": "report"},
    )
    assert cn_response.status_code == 200
    cn_payload = cn_response.json()
    selected = cn_payload.get("selected_tools") or []
    assert "get_sec_filings" not in selected
    assert "get_sec_material_events" not in selected
    assert "get_sec_risk_factors" not in selected
    assert "get_official_macro_releases" not in selected
    assert "get_local_market_filings" in selected
