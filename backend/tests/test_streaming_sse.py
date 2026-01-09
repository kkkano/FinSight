#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for SSE streaming helpers.
"""

import asyncio
import json

from backend.api.streaming import stream_report_sse


class StubReportAgent:
    async def analyze_stream(self, query: str):
        yield json.dumps({"type": "tool_start", "name": "get_stock_price"}) + "\n"
        yield json.dumps({"type": "token", "content": "Hello "}) + "\n"
        yield json.dumps({"type": "token", "content": "World"}) + "\n"
        yield json.dumps({"type": "tool_end"}) + "\n"
        yield json.dumps({"type": "done"}) + "\n"


async def _collect_stream(agent, builder):
    lines = []
    async for line in stream_report_sse(agent, "test query", builder):
        lines.append(line)
    return lines


def test_stream_report_sse_includes_report():
    captured = {}

    def report_builder(content: str):
        captured["content"] = content
        return {"summary": content}

    lines = asyncio.run(_collect_stream(StubReportAgent(), report_builder))
    assert lines, "stream should yield SSE lines"

    payloads = []
    for line in lines:
        assert line.startswith("data: ")
        payloads.append(json.loads(line[len("data: "):]))

    assert payloads[0]["type"] == "tool_start"
    assert payloads[1]["type"] == "token"
    assert payloads[2]["type"] == "token"
    assert payloads[3]["type"] == "tool_end"

    done_event = payloads[-1]
    assert done_event["type"] == "done"
    assert done_event["report"]["summary"] == "Hello World"
    assert captured["content"] == "Hello World"
