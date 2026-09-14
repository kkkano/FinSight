# -*- coding: utf-8 -*-
"""六节点主图的注册与运行顺序合同。"""
from __future__ import annotations

import asyncio

from langgraph.checkpoint.memory import MemorySaver


EXPECTED_NODES = [
    "prepare_context",
    "route_request",
    "collect_evidence",
    "analyze",
    "validate",
    "render",
]


def _run(coro):
    return asyncio.run(coro)


def _node_order(result: dict) -> list[str]:
    return [span.get("node") for span in ((result.get("trace") or {}).get("spans") or [])]


def test_graph_registers_exactly_six_public_nodes():
    from backend.graph.runner import _build_graph

    graph = _build_graph(checkpointer=MemorySaver())
    node_names = set(graph.nodes) - {"__start__", "__end__"}
    assert node_names == set(EXPECTED_NODES)


def test_research_path_runs_six_nodes_in_order():
    from backend.graph import GraphRunner

    result = _run(
        GraphRunner.create().ainvoke(
            thread_id="wp6-order-research",
            query="AAPL 最新股价",
            ui_context={"active_symbol": "AAPL"},
        )
    )
    assert _node_order(result) == EXPECTED_NODES


def test_direct_and_clarify_paths_keep_same_six_node_contract():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()
    direct = _run(runner.ainvoke(thread_id="wp6-order-direct", query="你好", ui_context={}))
    clarify = _run(runner.ainvoke(thread_id="wp6-order-clarify", query="分析影响", ui_context={}))

    assert _node_order(direct) == EXPECTED_NODES
    assert _node_order(clarify) == EXPECTED_NODES
    assert (direct.get("trace") or {}).get("collect_evidence", {}).get("status") == "skipped"
    assert (clarify.get("trace") or {}).get("collect_evidence", {}).get("status") == "skipped"
