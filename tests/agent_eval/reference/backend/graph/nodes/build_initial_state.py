# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib

from langchain_core.messages import AIMessage, HumanMessage

from backend.contracts import GRAPH_STATE_SCHEMA_VERSION, TRACE_SCHEMA_VERSION
from backend.graph.state import GraphState


def build_initial_state(state: GraphState) -> dict:
    """
    Ensure required fields exist and append the user message.

    The runner should provide at least: thread_id, query, ui_context (optional).
    """
    query = (state.get("query") or "").strip()
    updates: dict = {}

    trace = state.get("trace") or {}
    trace.setdefault("schema_version", TRACE_SCHEMA_VERSION)
    trace.setdefault("routing_chain", ["langgraph"])
    updates["trace"] = trace
    updates["schema_version"] = GRAPH_STATE_SCHEMA_VERSION

    thread_id = str(state.get("thread_id") or "").strip() or "default"
    if not state.get("thread_id"):
        updates["thread_id"] = thread_id

    existing_messages = list(state.get("messages") or [])
    recovered_messages = []
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    raw_history = ui_context.get("session_history") if isinstance(ui_context, dict) else None
    # 仅当 checkpoint 没有任何历史时，才使用客户端恢复历史，避免同一轮重复注入。
    if not existing_messages and isinstance(raw_history, list):
        for index, item in enumerate(raw_history[-12:]):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content or content == query:
                continue
            digest = hashlib.sha1(f"{role}\0{content}".encode("utf-8")).hexdigest()[:16]
            message_id = f"client-history-{index}-{digest}"
            message_cls = HumanMessage if role == "user" else AIMessage
            recovered_messages.append(message_cls(content=content, id=message_id))

    if query:
        updates["messages"] = [*recovered_messages, HumanMessage(content=query)]
    else:
        # No-op; Clarify node may interrupt with a prompt.
        updates["messages"] = []

    return updates
