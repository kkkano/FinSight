# -*- coding: utf-8 -*-
"""
PM0-1a: Verify that LangGraph checkpointer correctly accumulates messages
across multiple invocations with the same thread_id.

This confirms that:
1. HumanMessage from build_initial_state is appended (not overwritten)
2. Same thread_id -> messages grow across calls
3. Different thread_id -> isolated message lists
"""
from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage

from backend.graph.runner import GraphRunner


def _run(coro):
    return asyncio.run(coro)


def test_messages_accumulate_across_calls():
    """Same thread_id: messages should grow with each invocation."""
    runner = GraphRunner.create()
    thread_id = "test-accumulate-001"

    # First invocation
    state1 = _run(runner.ainvoke(thread_id=thread_id, query="What is AAPL?"))
    messages1 = state1.get("messages", [])

    # At minimum, the HumanMessage from this call should be present
    human_msgs_1 = [m for m in messages1 if isinstance(m, HumanMessage)]
    assert len(human_msgs_1) >= 1, (
        f"Expected at least 1 HumanMessage after first call, got {len(human_msgs_1)}"
    )

    # Second invocation (same thread)
    state2 = _run(runner.ainvoke(thread_id=thread_id, query="What about TSLA?"))
    messages2 = state2.get("messages", [])

    human_msgs_2 = [m for m in messages2 if isinstance(m, HumanMessage)]
    assert len(human_msgs_2) >= 2, (
        f"Expected at least 2 HumanMessages after second call, got {len(human_msgs_2)}. "
        f"Checkpointer may not be accumulating messages."
    )


def test_different_threads_isolated():
    """Different thread_ids should have isolated message lists."""
    runner = GraphRunner.create()
    thread_a = "test-isolated-A"
    thread_b = "test-isolated-B"

    _run(runner.ainvoke(thread_id=thread_a, query="Analyze AAPL"))
    _run(runner.ainvoke(thread_id=thread_a, query="What about its PE ratio?"))

    state_b = _run(runner.ainvoke(thread_id=thread_b, query="Analyze NVDA"))
    human_msgs_b = [m for m in state_b.get("messages", []) if isinstance(m, HumanMessage)]

    # Thread B should only have its own messages, not Thread A's
    assert len(human_msgs_b) == 1, (
        f"Thread B should have exactly 1 HumanMessage, got {len(human_msgs_b)}. "
        f"Thread isolation may be broken."
    )


def test_messages_include_human_content():
    """Verify the accumulated HumanMessages actually contain the query text."""
    runner = GraphRunner.create()
    thread_id = "test-content-001"

    state = _run(runner.ainvoke(thread_id=thread_id, query="Tell me about MSFT"))
    messages = state.get("messages", [])
    human_msgs = [m for m in messages if isinstance(m, HumanMessage)]

    assert len(human_msgs) >= 1
    assert "MSFT" in human_msgs[0].content, (
        f"HumanMessage content should contain the query text, got: {human_msgs[0].content}"
    )
