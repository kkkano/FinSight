# -*- coding: utf-8 -*-
from __future__ import annotations

from langchain_core.messages import HumanMessage

from backend.contracts import GRAPH_STATE_SCHEMA_VERSION, TRACE_SCHEMA_VERSION
from backend.graph.confirmation_policy import parse_confirmation_mode
from backend.graph.store import load_memory_context
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

    memory_context = load_memory_context(thread_id=thread_id)
    if memory_context:
        updates["memory_context"] = memory_context

    confirmation_mode = parse_confirmation_mode(state.get("confirmation_mode"))
    if confirmation_mode is not None:
        updates["confirmation_mode"] = confirmation_mode

    if query:
        updates["messages"] = [HumanMessage(content=query)]
    else:
        # No-op; Clarify node may interrupt with a prompt.
        updates["messages"] = []

    return updates
