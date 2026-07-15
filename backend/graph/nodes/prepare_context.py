# -*- coding: utf-8 -*-
"""请求理解前的确定性上下文准备节点。"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import RemoveMessage

from backend.graph.nodes.build_initial_state import build_initial_state
from backend.graph.nodes.normalize_ui_context import normalize_ui_context
from backend.graph.nodes.reset_turn_state import reset_turn_state
from backend.graph.nodes.summarize_history import summarize_history
from backend.graph.nodes.trim_conversation_history import trim_conversation_history
from backend.graph.state import GraphState


def _apply_message_delta(messages: list[Any], delta: list[Any]) -> list[Any]:
    """在单节点内模拟 LangGraph add_messages 对 RemoveMessage 的处理。"""
    if not delta:
        return list(messages)

    next_messages = list(messages)
    for item in delta:
        if isinstance(item, RemoveMessage):
            remove_id = getattr(item, "id", None)
            if remove_id:
                next_messages = [msg for msg in next_messages if getattr(msg, "id", None) != remove_id]
            continue
        next_messages.append(item)
    return next_messages


def prepare_context(state: GraphState) -> dict[str, Any]:
    """初始化当前轮次并规范化历史与 UI 上下文。"""
    initial = build_initial_state(state)
    initial_messages = list(initial.get("messages") or [])

    working: dict[str, Any] = dict(state)
    working.update({key: value for key, value in initial.items() if key != "messages"})
    working["messages"] = _apply_message_delta(
        list(state.get("messages") or []),
        initial_messages,
    )

    reset = reset_turn_state(working)  # type: ignore[arg-type]
    working.update(reset)

    result: dict[str, Any] = {
        **{key: value for key, value in initial.items() if key != "messages"},
        **reset,
    }
    if initial_messages:
        result["messages"] = list(initial_messages)

    trim_delta = trim_conversation_history(working)  # type: ignore[arg-type]
    trim_messages = list(trim_delta.get("messages") or [])
    if trim_messages:
        result.setdefault("messages", []).extend(trim_messages)
        working["messages"] = _apply_message_delta(working["messages"], trim_messages)

    summarize_delta = summarize_history(working)  # type: ignore[arg-type]
    summarize_messages = list(summarize_delta.get("messages") or [])
    if summarize_messages:
        result.setdefault("messages", []).extend(summarize_messages)
        working["messages"] = _apply_message_delta(working["messages"], summarize_messages)

    normalize_delta = normalize_ui_context(working)  # type: ignore[arg-type]
    if normalize_delta:
        result.update(normalize_delta)

    return result


__all__ = ["prepare_context"]
