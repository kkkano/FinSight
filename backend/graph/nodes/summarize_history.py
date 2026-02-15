# -*- coding: utf-8 -*-
"""
PM0-2b: Conditional summarize_history node.

When conversation messages exceed a threshold (default: 12 messages ≈ 6 turns),
this node compresses older messages into a single SystemMessage summary,
using RemoveMessage for proper add_messages reducer compatibility.

Strategy:
- Count Human+AI messages in state
- If count <= threshold: no-op
- If count > threshold: RemoveMessage for old ones + SystemMessage(summary)
- In stub mode: deterministic text extraction (no LLM)
"""
from __future__ import annotations

import logging
import os

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)

from backend.graph.state import GraphState

logger = logging.getLogger(__name__)

# Trigger summarization when messages exceed this count
_SUMMARIZE_THRESHOLD = int(os.getenv("LANGGRAPH_SUMMARIZE_THRESHOLD", "12"))

# Number of recent messages to always keep (3 turns = 6 messages)
_KEEP_RECENT_COUNT = int(os.getenv("LANGGRAPH_SUMMARIZE_KEEP_RECENT", "6"))


def _extract_summary_from_messages(messages: list) -> str:
    """
    Deterministic summary extraction from messages (no LLM required).

    Extracts user queries and brief AI response snippets to build
    a conversation context summary.
    """
    summary_parts = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content.strip() if isinstance(msg.content, str) else str(msg.content).strip()
            summary_parts.append(f"- 用户询问: {content}")
        elif isinstance(msg, AIMessage):
            content = msg.content.strip() if isinstance(msg.content, str) else str(msg.content).strip()
            # Take first 100 chars of AI response
            if len(content) > 100:
                content = content[:100] + "..."
            summary_parts.append(f"- 助手回复: {content}")

    if not summary_parts:
        return ""

    return "[对话摘要] 以下是之前对话的要点:\n" + "\n".join(summary_parts)


def summarize_history(state: GraphState) -> dict:
    """
    Conditionally summarize conversation history when it exceeds the threshold.

    Uses RemoveMessage for old messages + SystemMessage for summary.
    This is the correct LangGraph-native approach with add_messages reducer.
    """
    messages = state.get("messages") or []

    # Count only Human+AI messages (not system messages)
    conversation_msgs = [
        m for m in messages
        if isinstance(m, (HumanMessage, AIMessage))
    ]

    if len(conversation_msgs) <= _SUMMARIZE_THRESHOLD:
        # Within threshold — no summarization needed
        return {}

    logger.info(
        "[summarize_history] %d conversation messages exceed threshold %d. Summarizing...",
        len(conversation_msgs),
        _SUMMARIZE_THRESHOLD,
    )

    # Split: older messages to summarize, recent messages to keep
    keep_count = min(_KEEP_RECENT_COUNT, len(conversation_msgs))
    msgs_to_summarize = conversation_msgs[:-keep_count] if keep_count > 0 else conversation_msgs

    if not msgs_to_summarize:
        return {}

    # Build deterministic summary
    summary_text = _extract_summary_from_messages(msgs_to_summarize)

    if not summary_text:
        return {}

    # Build RemoveMessage list for old messages
    removals = []
    for msg in msgs_to_summarize:
        msg_id = getattr(msg, "id", None)
        if msg_id:
            removals.append(RemoveMessage(id=msg_id))

    # Add the summary as a new SystemMessage
    summary_msg = SystemMessage(content=summary_text)

    logger.info(
        "[summarize_history] Compressed %d old messages into summary, keeping %d recent",
        len(msgs_to_summarize),
        keep_count,
    )

    # RemoveMessage + SystemMessage: reducer removes old, adds summary
    return {"messages": removals + [summary_msg]}
