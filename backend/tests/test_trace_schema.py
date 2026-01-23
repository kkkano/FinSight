# -*- coding: utf-8 -*-
"""Tests for TraceEvent Schema v1"""
import pytest
from backend.orchestration.trace_schema import (
    TraceEvent, TraceEventType, create_trace_event, normalize_to_v1
)


class TestTraceEvent:
    def test_create_basic(self):
        event = TraceEvent(event_type="search_start", agent="deep_search")
        assert event.schema_version == "v1"
        assert event.event_type == "search_start"
        assert event.agent == "deep_search"
        assert event.timestamp  # auto-generated

    def test_to_dict(self):
        event = TraceEvent(event_type="step", agent="test")
        d = event.to_dict()
        assert d["schema_version"] == "v1"
        assert d["event_type"] == "step"

    def test_from_dict(self):
        data = {"event_type": "error", "agent": "news", "metadata": {"msg": "fail"}}
        event = TraceEvent.from_dict(data)
        assert event.event_type == "error"
        assert event.metadata["msg"] == "fail"


class TestCreateTraceEvent:
    def test_basic(self):
        e = create_trace_event("search_result", agent="deep_search", count=5)
        assert e["event_type"] == "search_result"
        assert e["metadata"]["count"] == 5

    def test_with_duration(self):
        e = create_trace_event("agent_end", duration_ms=1234)
        assert e["duration_ms"] == 1234


class TestNormalizeToV1:
    def test_old_stage_format(self):
        old = [{"stage": "initial_search", "data": {"queries": ["AAPL"]}}]
        normalized = normalize_to_v1(old, "deep_search")
        assert normalized[0]["schema_version"] == "v1"
        assert normalized[0]["event_type"] == "initial_search"
        assert normalized[0]["metadata"]["queries"] == ["AAPL"]

    def test_mixed_formats(self):
        old = [
            {"event": "start"},
            {"event_type": "middle"},
            {"stage": "end", "data": {"x": 1}},
        ]
        normalized = normalize_to_v1(old)
        assert len(normalized) == 3
        assert all(n["schema_version"] == "v1" for n in normalized)

    def test_empty_input(self):
        assert normalize_to_v1(None) == []
        assert normalize_to_v1([]) == []
