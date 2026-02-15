# -*- coding: utf-8 -*-
"""
PM0-1b: Verify that render_stub now appends an AIMessage to state messages,
so checkpointer stores complete conversation (Human + AI) turns.

This confirms:
1. After a single invocation, both HumanMessage and AIMessage are present
2. AIMessage content is derived from draft_markdown (not empty)
3. Across multiple calls, AI messages also accumulate
"""
from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage

from backend.graph.runner import GraphRunner


def _run(coro):
    return asyncio.run(coro)


def test_ai_message_present_after_invocation():
    """After a single call, messages should contain both Human and AI messages."""
    runner = GraphRunner.create()
    thread_id = "test-ai-msg-001"

    state = _run(runner.ainvoke(thread_id=thread_id, query="Analyze AAPL"))
    messages = state.get("messages", [])

    human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
    ai_msgs = [m for m in messages if isinstance(m, AIMessage)]

    assert len(human_msgs) >= 1, "Should have at least 1 HumanMessage"
    assert len(ai_msgs) >= 1, (
        f"Should have at least 1 AIMessage after render_stub, got {len(ai_msgs)}. "
        f"render_stub may not be appending AIMessage."
    )


def test_ai_message_has_content():
    """AIMessage should contain meaningful content derived from draft_markdown."""
    runner = GraphRunner.create()
    thread_id = "test-ai-content-001"

    state = _run(runner.ainvoke(
        thread_id=thread_id,
        query="Analyze TSLA",
        ui_context={"active_symbol": "TSLA"},
    ))
    messages = state.get("messages", [])
    ai_msgs = [m for m in messages if isinstance(m, AIMessage)]

    assert len(ai_msgs) >= 1
    content = ai_msgs[-1].content
    # Content should not be just the generic fallback
    assert len(content) > 10, (
        f"AIMessage content too short ({len(content)} chars), expected substantive summary"
    )


def test_ai_messages_accumulate_with_human():
    """Across two calls, should have interleaved Human+AI messages."""
    runner = GraphRunner.create()
    thread_id = "test-ai-accumulate-001"

    _run(runner.ainvoke(thread_id=thread_id, query="What is AAPL?"))
    state2 = _run(runner.ainvoke(thread_id=thread_id, query="Compare with MSFT"))
    messages = state2.get("messages", [])

    human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
    ai_msgs = [m for m in messages if isinstance(m, AIMessage)]

    assert len(human_msgs) >= 2, f"Expected >=2 HumanMessages, got {len(human_msgs)}"
    assert len(ai_msgs) >= 2, (
        f"Expected >=2 AIMessages across 2 calls, got {len(ai_msgs)}. "
        f"AIMessage may not be persisting through checkpointer."
    )
