import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def test_chat_supervisor_stream_serializes_datetime(monkeypatch):
    import backend.api.main as main

    async def _stub_run_graph_traced(*_args, **_kwargs):
        return {
            "artifacts": {"draft_markdown": "ok"},
            "subject": {"tickers": ["NVDA"]},
            "output_mode": "report",
            "trace": {
                "routing_chain": ["langgraph"],
                "spans": [
                    {
                        "node": "stub",
                        "timestamp": datetime(2026, 2, 7, 12, 0, tzinfo=timezone.utc),
                    }
                ],
            },
        }

    monkeypatch.setattr("backend.graph.runner.run_graph_traced", _stub_run_graph_traced)

    events = []
    with TestClient(main.app) as client:
        with client.stream("POST", "/chat/supervisor/stream", json={"query": "NVDA 最新情况"}) as response:
            assert response.status_code == 200
            for raw in response.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                if not line.startswith("data: "):
                    continue
                events.append(json.loads(line[len("data: ") :]))

    done_event = next((item for item in events if item.get("type") == "done"), None)
    assert done_event is not None
    trace = ((done_event.get("graph") or {}).get("trace")) or {}
    assert trace
    spans = trace.get("spans") or []
    assert spans
    assert isinstance(spans[0].get("timestamp"), str)
    assert spans[0]["timestamp"].startswith("2026-02-07T12:00:00")


def test_chat_supervisor_sync_sanitizes_nonfinite_numbers(monkeypatch):
    import backend.api.main as main

    async def _stub_run_graph_traced(*_args, **_kwargs):
        return {
            "artifacts": {"draft_markdown": "ok"},
            "subject": {"tickers": ["NVDA"]},
            "output_mode": "chat",
            "trace": {
                "routing_chain": ["langgraph"],
                "metrics": [float("nan"), float("inf"), float("-inf"), 1.25],
            },
        }

    monkeypatch.setattr("backend.graph.runner.run_graph_traced", _stub_run_graph_traced)

    with TestClient(main.app) as client:
        response = client.post("/chat/supervisor", json={"query": "NVDA 最新情况"})

    assert response.status_code == 200
    metrics = response.json()["graph"]["trace"]["metrics"]
    assert metrics == [None, None, None, 1.25]


def test_chat_supervisor_stream_sanitizes_nonfinite_numbers(monkeypatch):
    import backend.api.main as main

    async def _stub_run_graph_traced(*_args, **_kwargs):
        return {
            "artifacts": {"draft_markdown": "ok"},
            "subject": {"tickers": ["NVDA"]},
            "output_mode": "chat",
            "trace": {
                "routing_chain": ["langgraph"],
                "metric": float("nan"),
            },
        }

    monkeypatch.setattr("backend.graph.runner.run_graph_traced", _stub_run_graph_traced)

    events = []
    with TestClient(main.app) as client:
        with client.stream("POST", "/chat/supervisor/stream", json={"query": "NVDA 最新情况"}) as response:
            assert response.status_code == 200
            for raw in response.iter_lines():
                line = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: ") :]))

    done_event = next(item for item in events if item.get("type") == "done")
    assert done_event["graph"]["trace"]["metric"] is None
