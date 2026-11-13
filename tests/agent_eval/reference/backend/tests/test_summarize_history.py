# -*- coding: utf-8 -*-
"""
PM0-2b: Verify summarize_history node correctly compresses old messages
when conversation exceeds the threshold.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage

from backend.graph.nodes.summarize_history import (
    _extract_summary_from_messages,
    summarize_history,
)


def test_no_summarization_when_below_threshold():
    """When messages are below threshold, return empty dict."""
    messages = [
        HumanMessage(content="Hello"),
        AIMessage(content="Hi there!"),
    ]
    state = {"messages": messages}
    result = summarize_history(state)
    assert result == {}, "Should not summarize when below threshold"


def test_summarization_triggers_when_over_threshold():
    """When messages exceed threshold, should return RemoveMessage + SystemMessage."""
    # Create 20 messages (10 turns > default threshold of 12)
    messages = []
    for i in range(10):
        msg_h = HumanMessage(content=f"Question {i}", id=f"human-{i}")
        msg_a = AIMessage(content=f"Answer {i}", id=f"ai-{i}")
        messages.append(msg_h)
        messages.append(msg_a)

    state = {"messages": messages}
    result = summarize_history(state)

    assert "messages" in result, "Should return messages with removals + summary"
    result_msgs = result["messages"]

    # Should contain RemoveMessage instances and a SystemMessage
    remove_msgs = [m for m in result_msgs if isinstance(m, RemoveMessage)]
    system_msgs = [m for m in result_msgs if isinstance(m, SystemMessage)]

    assert len(remove_msgs) > 0, "Should have RemoveMessage for old messages"
    assert len(system_msgs) == 1, "Should have exactly 1 SystemMessage summary"
    assert "[对话摘要]" in system_msgs[0].content


def test_summary_contains_user_queries():
    """The summary should contain the user's query text."""
    messages = [
        HumanMessage(content="分析AAPL"),
        AIMessage(content="苹果公司分析结果..."),
        HumanMessage(content="查看TSLA"),
        AIMessage(content="特斯拉分析结果..."),
    ]
    summary = _extract_summary_from_messages(messages)
    assert "AAPL" in summary
    assert "TSLA" in summary


def test_summary_truncates_long_ai_responses():
    """AI responses longer than 100 chars should be truncated in summary."""
    long_content = "这是一个非常长的分析结果" * 20  # > 100 chars
    messages = [
        HumanMessage(content="分析苹果"),
        AIMessage(content=long_content),
    ]
    summary = _extract_summary_from_messages(messages)
    assert "..." in summary, "Long AI responses should be truncated"


def test_empty_messages_returns_empty():
    """Empty messages list should return empty dict."""
    result = summarize_history({"messages": []})
    assert result == {}


def test_keeps_recent_messages():
    """Recent messages (last N) should be preserved, not removed."""
    messages = []
    for i in range(10):
        msg_h = HumanMessage(content=f"Question {i}", id=f"human-{i}")
        msg_a = AIMessage(content=f"Answer {i}", id=f"ai-{i}")
        messages.append(msg_h)
        messages.append(msg_a)

    state = {"messages": messages}
    result = summarize_history(state)

    if "messages" not in result:
        return  # No summarization needed

    result_msgs = result["messages"]
    remove_msgs = [m for m in result_msgs if isinstance(m, RemoveMessage)]
    removed_ids = {m.id for m in remove_msgs}

    # The last 6 messages should NOT be in the removal list
    recent_ids = {
        getattr(m, "id", None)
        for m in messages[-6:]
        if getattr(m, "id", None)
    }
    overlap = removed_ids & recent_ids
    assert len(overlap) == 0, f"Recent messages should not be removed, but {len(overlap)} were"
