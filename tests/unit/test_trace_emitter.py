# -*- coding: utf-8 -*-

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"output_preview": "hello"},
        {"output_preview": "hello", "foo": "bar", "tokens": 12},
        {"foo": "bar"},
    ],
)
def test_trace_emitter_emit_llm_end_accepts_output_preview_and_extra_metadata(kwargs):
    from backend.orchestration.trace_emitter import get_trace_emitter

    emitter = get_trace_emitter()

    events = []

    def listener(evt):
        events.append(evt)

    emitter.add_listener(listener)
    try:
        emitter.emit_llm_end(model="test-model", duration_ms=1, success=True, **kwargs)
    finally:
        emitter.remove_listener(listener)

    assert events, "Expected at least one trace event"
    last = events[-1]
    assert last.event_type == "llm_end"
    assert last.metadata.get("model") == "test-model"

    if "output_preview" in kwargs:
        assert last.metadata.get("output_preview") == kwargs["output_preview"]
    if "foo" in kwargs:
        assert last.metadata.get("foo") == "bar"
    if "tokens" in kwargs:
        assert last.metadata.get("tokens") == kwargs["tokens"]
