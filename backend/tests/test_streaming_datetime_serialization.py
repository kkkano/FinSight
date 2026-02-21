import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient


class _StubRunner:
    async def ainvoke(self, **_kwargs):
        return {
            "artifacts": {"draft_markdown": "ok"},
            "subject": {"tickers": ["NVDA"]},
            "output_mode": "report",
            "trace": [
                {
                    "event": "node_end",
                    "timestamp": datetime(2026, 2, 7, 12, 0, tzinfo=timezone.utc),
                }
            ],
        }


def test_chat_supervisor_stream_serializes_datetime(monkeypatch):
    import backend.api.main as main

    async def _stub_get_runner():
        return _StubRunner()

    monkeypatch.setattr(main, "aget_graph_runner", _stub_get_runner)

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
    trace = ((done_event.get("graph") or {}).get("trace")) or []
    assert trace
    assert isinstance(trace[0].get("timestamp"), str)
    assert trace[0]["timestamp"].startswith("2026-02-07T12:00:00")
