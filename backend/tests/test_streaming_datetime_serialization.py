import json
from datetime import datetime, timezone

from backend.api.execution_router import _serialize_sse_item


def test_execute_stream_serializes_datetime():
    payload = json.loads(
        _serialize_sse_item(
            {"type": "trace", "timestamp": datetime(2026, 2, 7, 12, 0, tzinfo=timezone.utc)}
        )
    )
    assert payload["timestamp"].startswith("2026-02-07T12:00:00")


def test_execute_stream_sanitizes_nonfinite_numbers():
    payload = json.loads(
        _serialize_sse_item(
            {"metrics": [float("nan"), float("inf"), float("-inf"), 1.25]}
        )
    )
    assert payload["metrics"] == [None, None, None, 1.25]
