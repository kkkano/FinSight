from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    import backend.api.chat_router as chat_router
    import backend.api.main as main

    def _unavailable() -> None:
        raise HTTPException(status_code=503, detail="llm unavailable in test")

    monkeypatch.setattr(chat_router, "_ensure_llm_available", _unavailable)
    with TestClient(main.app) as test_client:
        yield test_client


def test_sync_financial_term_bypasses_llm_preflight(client: TestClient) -> None:
    response = client.post("/chat/supervisor", json={"query": "PE 是什么"})

    assert response.status_code == 200
    payload = response.json()
    assert "市盈率" in payload["response"]
    assert "股价 / 每股收益" in payload["response"]
    assert payload["graph"]["trace"]["events"][-1]["event"] == "financial_term_resolved"


def test_stream_financial_term_bypasses_llm_preflight(client: TestClient) -> None:
    response = client.post("/chat/supervisor/stream", json={"query": "ROE 是什么意思"})

    assert response.status_code == 200
    events = [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    done = next(event for event in events if event.get("type") == "done")
    assert "净资产收益率" in done["response"]


@pytest.mark.parametrize(
    "options",
    [
        {"output_mode": "investment_report"},
        {"agents": ["fundamental"]},
    ],
)
def test_report_or_forced_agent_does_not_bypass_llm_preflight(
    client: TestClient,
    options: dict[str, object],
) -> None:
    response = client.post(
        "/chat/supervisor",
        json={"query": "PE 是什么", "options": options},
    )

    assert response.status_code == 503
