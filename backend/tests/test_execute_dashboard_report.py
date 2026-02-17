# -*- coding: utf-8 -*-
import importlib
import json

from fastapi.testclient import TestClient


def _load_app():
    import backend.api.main as main

    importlib.reload(main)
    return main.app


def test_execute_dashboard_research_tab_returns_done_without_interrupt():
    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/execute",
        json={
            "query": "生成 AAPL 投资报告",
            "tickers": ["AAPL"],
            "output_mode": "investment_report",
            "source": "dashboard_research_tab",
            "session_id": "public:anonymous:dashboard-test",
        },
    )
    assert resp.status_code == 200

    events = []
    for line in resp.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: ") :])
        events.append(payload)

    assert any(e.get("type") == "done" for e in events), "dashboard one-click should complete in-place"
    assert not any(
        e.get("type") == "interrupt" for e in events
    ), "dashboard one-click should not require manual resume"
