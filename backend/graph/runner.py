# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from backend.graph.checkpointer import aget_graph_checkpointer, get_graph_checkpointer_info
from backend.graph.nodes import (
    build_initial_state,
    decide_output_mode,
    clarify,
    execute_plan_stub,
    normalize_ui_context,
    parse_operation,
    policy_gate,
    planner,
    render_stub,
    resolve_subject,
    synthesize,
)
from backend.graph.nodes.trim_conversation_history import trim_conversation_history
from backend.graph.nodes.summarize_history import summarize_history
from backend.graph.state import GraphState
from backend.graph.trace import with_node_trace
from backend.services.langfuse_tracer import langfuse_observe

_graph_runner: Optional["GraphRunner"] = None
_graph_runner_lock: Optional[asyncio.Lock] = None
_graph_runner_loop_id: Optional[int] = None


def _build_graph(*, checkpointer: Any) -> Any:
    """
    Build the Phase 1 graph skeleton.
    Later phases will replace stub nodes with real planner/executor/templates.
    """
    graph = StateGraph(GraphState)
    graph.add_node("build_initial_state", with_node_trace("build_initial_state", build_initial_state))
    graph.add_node("trim_history", with_node_trace("trim_history", trim_conversation_history))
    graph.add_node("summarize_history", with_node_trace("summarize_history", summarize_history))
    graph.add_node("normalize_ui_context", with_node_trace("normalize_ui_context", normalize_ui_context))
    graph.add_node("decide_output_mode", with_node_trace("decide_output_mode", decide_output_mode))
    graph.add_node("resolve_subject", with_node_trace("resolve_subject", resolve_subject))
    graph.add_node("clarify", with_node_trace("clarify", clarify))
    graph.add_node("parse_operation", with_node_trace("parse_operation", parse_operation))
    graph.add_node("policy_gate", with_node_trace("policy_gate", policy_gate))
    graph.add_node("planner", with_node_trace("planner", planner))
    graph.add_node("execute_plan", with_node_trace("execute_plan", execute_plan_stub))
    graph.add_node("synthesize", with_node_trace("synthesize", synthesize))
    graph.add_node("render", with_node_trace("render", render_stub))

    graph.add_edge(START, "build_initial_state")
    graph.add_edge("build_initial_state", "trim_history")
    graph.add_edge("trim_history", "summarize_history")
    graph.add_edge("summarize_history", "normalize_ui_context")
    graph.add_edge("normalize_ui_context", "decide_output_mode")
    graph.add_edge("decide_output_mode", "resolve_subject")
    graph.add_edge("resolve_subject", "clarify")

    def _route_after_clarify(state: GraphState) -> str:
        clarify_state = state.get("clarify") or {}
        if isinstance(clarify_state, dict) and clarify_state.get("needed") is True:
            return END
        return "parse_operation"

    graph.add_conditional_edges(
        "clarify",
        _route_after_clarify,
        {"parse_operation": "parse_operation", END: END},
    )

    graph.add_edge("policy_gate", "planner")
    graph.add_edge("planner", "execute_plan")
    graph.add_edge("execute_plan", "synthesize")
    graph.add_edge("synthesize", "render")
    graph.add_edge("render", END)

    graph.add_edge("parse_operation", "policy_gate")

    return graph.compile(checkpointer=checkpointer)


@dataclass
class GraphRunner:
    """
    Thin wrapper around the compiled LangGraph.
    """

    _graph: Any

    @classmethod
    def create(cls) -> "GraphRunner":
        # Test-friendly factory: deterministic in-memory runner.
        return GraphRunner(_graph=_build_graph(checkpointer=MemorySaver()))

    async def ainvoke(
        self,
        *,
        thread_id: str,
        query: str,
        ui_context: Optional[dict] = None,
        output_mode: Optional[str] = None,
        strict_selection: Optional[bool] = None,
    ) -> dict:
        state: dict = {
            "thread_id": thread_id,
            "query": query,
            "ui_context": ui_context or {},
        }
        if output_mode:
            state["output_mode"] = output_mode
        if strict_selection is not None:
            state["strict_selection"] = bool(strict_selection)

        config = {"configurable": {"thread_id": thread_id}}
        return await self._graph.ainvoke(state, config=config)

    @staticmethod
    def checkpointer_info() -> dict[str, Any]:
        return get_graph_checkpointer_info()


async def aget_graph_runner() -> GraphRunner:
    """
    Async process-wide runner singleton.
    """
    global _graph_runner, _graph_runner_lock, _graph_runner_loop_id
    loop_id = id(asyncio.get_running_loop())
    if _graph_runner is not None and _graph_runner_loop_id == loop_id:
        return _graph_runner
    if _graph_runner_lock is None:
        _graph_runner_lock = asyncio.Lock()
    async with _graph_runner_lock:
        loop_id = id(asyncio.get_running_loop())
        if _graph_runner is not None and _graph_runner_loop_id == loop_id:
            return _graph_runner
        if _graph_runner is None or _graph_runner_loop_id != loop_id:
            checkpointer = await aget_graph_checkpointer()
            _graph_runner = GraphRunner(_graph=_build_graph(checkpointer=checkpointer))
            _graph_runner_loop_id = loop_id
    return _graph_runner


def get_graph_runner() -> GraphRunner:
    if _graph_runner is None:
        raise RuntimeError("Graph runner not initialized yet. Use aget_graph_runner() in async context.")
    return _graph_runner


def graph_runner_ready() -> bool:
    return _graph_runner is not None


def reset_graph_runner() -> None:
    global _graph_runner, _graph_runner_lock, _graph_runner_loop_id
    _graph_runner = None
    _graph_runner_lock = None
    _graph_runner_loop_id = None


# ==================== Langfuse Trace 入口 ====================

def _update_langfuse_trace(*, thread_id: str, query: str, output_mode: str | None) -> None:
    """安全地设置当前 Trace 的 session / input 元数据。"""
    try:
        from backend.services.langfuse_tracer import get_langfuse_client_safe
        lf = get_langfuse_client_safe()
        if lf is not None:
            lf.update_current_trace(
                name=f"research:{query[:80]}",
                session_id=thread_id,
                input={"query": query, "output_mode": output_mode or "auto"},
                metadata={"thread_id": thread_id},
            )
    except Exception:
        pass


@langfuse_observe(name="graph_pipeline")
async def run_graph_traced(
    runner: GraphRunner,
    *,
    thread_id: str,
    query: str,
    ui_context: dict | None = None,
    output_mode: str | None = None,
    strict_selection: bool | None = None,
) -> dict:
    """
    带 Langfuse Trace 的图执行入口。

    @observe 装饰器自动创建 Trace（最外层）/ Span（嵌套场景），
    后续 with_node_trace 中的 langfuse_span 会自动嵌套在此 Trace 下，
    create_llm 中的 CallbackHandler 会自动捕获 LLM Generation。
    """
    _update_langfuse_trace(thread_id=thread_id, query=query, output_mode=output_mode)
    return await runner.ainvoke(
        thread_id=thread_id,
        query=query,
        ui_context=ui_context,
        output_mode=output_mode,
        strict_selection=strict_selection,
    )


__all__ = [
    "GraphRunner",
    "aget_graph_runner",
    "get_graph_runner",
    "graph_runner_ready",
    "reset_graph_runner",
    "run_graph_traced",
]
