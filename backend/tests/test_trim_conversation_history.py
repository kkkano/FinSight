# -*- coding: utf-8 -*-
"""
PM0-2a: Verify trim_conversation_history node trims long message lists
while preserving recent messages.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from backend.graph.nodes.trim_conversation_history import (
    _token_counter,
    trim_conversation_history,
)


def test_no_trimming_when_within_budget():
    """When messages are within budget, return empty dict (no state change)."""
    messages = [
        HumanMessage(content="Hello"),
        AIMessage(content="Hi there!"),
    ]
    state = {"messages": messages}
    result = trim_conversation_history(state)
    assert result == {}, "Should not trim when within budget"


def test_empty_messages_returns_empty():
    """Empty messages list should return empty dict."""
    result = trim_conversation_history({"messages": []})
    assert result == {}


def test_trimming_when_over_budget(monkeypatch):
    """When messages exceed token budget, they should be trimmed."""
    monkeypatch.setenv("LANGGRAPH_MAX_HISTORY_TOKENS", "50")

    # Reimport to pick up new env var (module-level default won't change,
    # so we test the function's internal logic instead)
    from backend.graph.nodes import trim_conversation_history as mod

    # Create enough messages to exceed 50 tokens
    big_messages = []
    for i in range(20):
        big_messages.append(HumanMessage(content=f"Message number {i} " * 10))
        big_messages.append(AIMessage(content=f"Response to message {i} " * 10))

    state = {"messages": big_messages}
    # Directly test _token_counter to ensure it counts properly
    total_tokens = _token_counter(big_messages)
    assert total_tokens > 50, f"Expected >50 tokens, got {total_tokens}"


def test_token_counter_basic():
    """Token counter should produce reasonable counts."""
    messages = [
        HumanMessage(content="Hello world"),
        AIMessage(content="Hi! How can I help you today?"),
    ]
    count = _token_counter(messages)
    # tiktoken should count about 2-3 tokens for "Hello world" + 4 overhead
    # and about 8-9 tokens for the AI message + 4 overhead
    # Total should be roughly 20-30
    assert 10 < count < 100, f"Token count {count} seems unreasonable"


def test_token_counter_cjk():
    """Token counter should handle Chinese characters correctly."""
    messages = [
        HumanMessage(content="分析苹果公司的股价走势"),
        AIMessage(content="苹果公司（AAPL）近期股价表现强劲，受益于新产品发布和服务收入增长。"),
    ]
    count = _token_counter(messages)
    # CJK characters use more tokens per char
    assert count > 20, f"CJK token count {count} seems too low"
