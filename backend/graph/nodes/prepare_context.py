# -*- coding: utf-8 -*-
"""请求理解前的确定性上下文准备节点。"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import RemoveMessage

from backend.graph.nodes.normalize_ui_context import normalize_ui_context
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
    """
    合并原来的 trim/summarize/normalize 前置节点。

    目标是让主图只有一个确定性的上下文准备入口，避免请求理解前散落多个
    业务可见节点；旧节点仍保留给兼容测试和单独复用。
    """
    result: dict[str, Any] = {}
    messages = list(state.get("messages") or [])

    trim_delta = trim_conversation_history(state)
    trim_messages = list(trim_delta.get("messages") or [])
    if trim_messages:
        result.setdefault("messages", []).extend(trim_messages)
        messages = _apply_message_delta(messages, trim_messages)

    summarize_state = dict(state)
    summarize_state["messages"] = messages
    summarize_delta = summarize_history(summarize_state)  # type: ignore[arg-type]
    summarize_messages = list(summarize_delta.get("messages") or [])
    if summarize_messages:
        result.setdefault("messages", []).extend(summarize_messages)

    normalize_delta = normalize_ui_context(state)
    if normalize_delta:
        result.update(normalize_delta)

    return result


__all__ = ["prepare_context"]
