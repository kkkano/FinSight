# -*- coding: utf-8 -*-
"""
PM0-2a: trim_messages safety net for conversation history.

This node runs right after build_initial_state to ensure the messages list
never exceeds the token budget.

Strategy:
- Count tokens in current messages
- If over budget: identify messages to remove, return RemoveMessage for each
- Uses RemoveMessage (not list replacement) to work correctly with add_messages reducer
- Always preserves the most recent messages
"""
from __future__ import annotations

import logging
import os

from langchain_core.messages import RemoveMessage, trim_messages

from backend.graph.state import GraphState

logger = logging.getLogger(__name__)

# Default max tokens for conversation history in state.
# ~8k tokens ≈ 6-8 full conversation rounds.
_DEFAULT_MAX_HISTORY_TOKENS = int(os.getenv("LANGGRAPH_MAX_HISTORY_TOKENS", "8000"))


def _token_counter(messages: list) -> int:
    """
    Count tokens using tiktoken (cl100k_base encoding, compatible with GPT-4/4o).

    Falls back to a rough character-based estimate if tiktoken fails.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        total = 0
        for msg in messages:
            content = msg.content if hasattr(msg, "content") else str(msg)
            if isinstance(content, str):
                total += len(enc.encode(content))
            else:
                total += len(enc.encode(str(content)))
            # Overhead per message (role tokens etc.)
            total += 4
        return total
    except Exception:
        # Rough fallback: ~4 chars per token for mixed CJK/English
        total = 0
        for msg in messages:
            content = msg.content if hasattr(msg, "content") else str(msg)
            total += len(str(content)) // 4 + 4
        return total


def trim_conversation_history(state: GraphState) -> dict:
    """
    Trim conversation messages to stay within token budget.

    Uses RemoveMessage to tell the add_messages reducer which messages to delete.
    This is the correct LangGraph-native approach — returning a plain list would
    cause the reducer to APPEND (not replace) messages.
    """
    messages = state.get("messages") or []

    if not messages:
        return {}

    max_tokens = _DEFAULT_MAX_HISTORY_TOKENS
    current_tokens = _token_counter(messages)

    if current_tokens <= max_tokens:
        # Within budget — no trimming needed
        return {}

    logger.info(
        "[trim_conversation_history] Messages exceed budget: %d tokens > %d max. Trimming...",
        current_tokens,
        max_tokens,
    )

    # Use trim_messages to determine which messages to KEEP
    trimmed = trim_messages(
        messages,
        max_tokens=max_tokens,
        token_counter=_token_counter,
        strategy="last",
        allow_partial=False,
        include_system=True,
    )

    # Build a set of message IDs to keep
    keep_ids = set()
    for msg in trimmed:
        if hasattr(msg, "id") and msg.id:
            keep_ids.add(msg.id)

    # Return RemoveMessage for each message NOT in the keep set
    removals = []
    for msg in messages:
        msg_id = getattr(msg, "id", None)
        if msg_id and msg_id not in keep_ids:
            removals.append(RemoveMessage(id=msg_id))

    if not removals:
        return {}

    trimmed_tokens = _token_counter(trimmed)
    logger.info(
        "[trim_conversation_history] Removing %d messages (%d -> %d tokens, keeping %d messages)",
        len(removals),
        current_tokens,
        trimmed_tokens,
        len(trimmed),
    )

    return {"messages": removals}
