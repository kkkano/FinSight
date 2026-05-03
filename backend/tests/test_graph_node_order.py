# -*- coding: utf-8 -*-
"""
Graph node-order invariant tests (P0-03).

These tests protect against accidental reordering of the graph pipeline.
Any change to node registration, edge wiring, or conditional routing
must explicitly update these assertions — no silent drift allowed.
"""
import asyncio

import pytest


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Expected node order for different execution paths
# ---------------------------------------------------------------------------

# Full happy-path: query with known ticker, no clarification needed
_FULL_HAPPY_PATH = [
    "build_initial_state",
    "reset_turn_state",
    "prepare_context",
    "understand_request",
    "policy_gate",
    "planner",
    "confirmation_gate",
    "execute_plan",
    "synthesize",
    "render",
]

# Early-stop at clarify: unknown subject → clarify.needed=True → END
_CLARIFY_STOP_PATH = [
    "build_initial_state",
    "reset_turn_state",
    "prepare_context",
    "understand_request",
]

# The prefix that MUST appear at the start of every execution path
_INVARIANT_PREFIX = [
    "build_initial_state",
    "reset_turn_state",
    "prepare_context",
    "understand_request",
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _extract_node_order(result: dict) -> list[str]:
    """Extract ordered node names from trace spans."""
    trace = result.get("trace") or {}
    spans = trace.get("spans") or []
    return [s.get("node") for s in spans]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGraphNodeOrderInvariant:
    """Ensure the graph pipeline node ordering is stable."""

    def test_full_happy_path_order(self):
        """Full execution path must match the expected runtime sequence."""
        from backend.graph import GraphRunner

        runner = GraphRunner.create()
        result = _run(runner.ainvoke(
            thread_id="t-order-happy",
            query="分析 AAPL",
            ui_context={"active_symbol": "AAPL"},
        ))
        nodes = _extract_node_order(result)
        assert nodes == _FULL_HAPPY_PATH, (
            f"Full happy-path node order drifted!\n"
            f"  Expected: {_FULL_HAPPY_PATH}\n"
            f"  Got:      {nodes}"
        )

    def test_clarify_stop_path_order(self):
        """Clarify early-stop must match the expected runtime sequence."""
        from backend.graph import GraphRunner

        runner = GraphRunner.create()
        result = _run(runner.ainvoke(
            thread_id="t-order-clarify",
            query="分析影响",
            ui_context={},
        ))
        nodes = _extract_node_order(result)
        assert nodes == _CLARIFY_STOP_PATH, (
            f"Clarify-stop path node order drifted!\n"
            f"  Expected: {_CLARIFY_STOP_PATH}\n"
            f"  Got:      {nodes}"
        )

    def test_invariant_prefix_always_present(self):
        """Every execution path must start with the 7-node invariant prefix."""
        from backend.graph import GraphRunner

        runner = GraphRunner.create()
        # Test with two different paths
        for tid, query, ctx in [
            ("t-prefix-1", "分析 TSLA", {"active_symbol": "TSLA"}),
            ("t-prefix-2", "你好", {}),
        ]:
            result = _run(runner.ainvoke(
                thread_id=tid, query=query, ui_context=ctx,
            ))
            nodes = _extract_node_order(result)
            prefix = nodes[: len(_INVARIANT_PREFIX)]
            assert prefix == _INVARIANT_PREFIX, (
                f"Invariant prefix violated for query={query!r}!\n"
                f"  Expected prefix: {_INVARIANT_PREFIX}\n"
                f"  Got prefix:      {prefix}"
            )

    def test_reset_turn_state_immediately_after_build(self):
        """reset_turn_state must be the second node, right after build_initial_state."""
        from backend.graph import GraphRunner

        runner = GraphRunner.create()
        result = _run(runner.ainvoke(
            thread_id="t-reset-pos",
            query="NVDA 股价",
            ui_context={"active_symbol": "NVDA"},
        ))
        nodes = _extract_node_order(result)
        assert len(nodes) >= 2
        assert nodes[0] == "build_initial_state"
        assert nodes[1] == "reset_turn_state"

    def test_understand_request_before_policy(self):
        """understand_request must be the single runtime front-half node before policy."""
        from backend.graph import GraphRunner

        runner = GraphRunner.create()
        result = _run(runner.ainvoke(
            thread_id="t-parse-pos",
            query="分析 MSFT 技术面",
            ui_context={"active_symbol": "MSFT"},
        ))
        nodes = _extract_node_order(result)
        idx_understand = nodes.index("understand_request")
        assert "policy_gate" in nodes[idx_understand + 1:], "policy_gate must run after understand_request"
        assert "resolve_subject" not in nodes
        assert "parse_operation" not in nodes

    def test_expected_node_count(self):
        """Graph must register the new understanding node plus legacy compatibility nodes."""
        from backend.graph.runner import _build_graph
        from langgraph.checkpoint.memory import MemorySaver

        graph = _build_graph(checkpointer=MemorySaver())
        # compiled graph has .nodes attribute with all registered node names
        node_names = set(graph.nodes.keys()) - {"__start__", "__end__"}
        expected_nodes = {
            "build_initial_state", "reset_turn_state",
            "prepare_context",
            "trim_history", "summarize_history",
            "normalize_ui_context", "decide_output_mode",
            "chat_respond", "resolve_subject", "clarify",
            "parse_operation", "policy_gate", "planner",
            "confirmation_gate", "execute_plan", "synthesize", "render",
            "alert_extractor", "alert_action", "understand_request",
        }
        assert node_names == expected_nodes, (
            f"Node set mismatch!\n"
            f"  Missing: {expected_nodes - node_names}\n"
            f"  Extra:   {node_names - expected_nodes}"
        )
