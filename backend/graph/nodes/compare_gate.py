# -*- coding: utf-8 -*-
"""
Compare evidence gate — shared helper for synthesize & render.

This module centralises the "should we render as comparison?" decision so
that synthesize and render_stub always agree.  It replaces the old
``len(tickers) > 1`` heuristic that caused the pseudo-comparison bug.

Decision logic:
  1. ``is_compare_operation(state)`` → True iff ``operation.name == "compare"``
  2. ``has_compare_evidence(state)`` → True iff the
     ``get_performance_comparison`` tool returned valid data in step_results.
  3. ``should_render_compare(state)`` → True iff BOTH (1) AND (2) are True.
     When (1) is True but (2) is False, callers should degrade to a
     normal multi-asset QA template and emit a ``compare_evidence_missing``
     decision note.
"""
from __future__ import annotations

from typing import Any

from backend.graph.state import GraphState


# ---------------------------------------------------------------------------
# Core predicates
# ---------------------------------------------------------------------------

def is_compare_operation(state: GraphState) -> bool:
    """Return True when parse_operation resolved the intent as 'compare'."""
    operation = state.get("operation")
    if isinstance(operation, dict):
        return operation.get("name") == "compare"
    return False


def has_compare_evidence(state: GraphState) -> bool:
    """
    Return True when ``get_performance_comparison`` tool returned valid data.

    "Valid" means:
      - The tool was executed (output is not None).
      - Output is not an empty string.
      - Output does not start with a failure prefix.
      - Output is not marked as skipped.
    """
    output = _get_comparison_tool_output(state)
    if output is None:
        return False

    text = str(output).strip()
    if not text:
        return False

    # The executor wraps failures as "get_performance_comparison failed: ..."
    if text.lower().startswith("get_performance_comparison failed"):
        return False

    return True


def should_render_compare(state: GraphState) -> bool:
    """
    Return True when the current request should use a comparison template.

    This is the SINGLE source of truth for both synthesize and render.
    The decision requires BOTH:
      1. ``operation.name == "compare"``  (intent)
      2. ``has_compare_evidence(state)``  (actual data from tool)

    When (1) is True but (2) is False, callers should degrade to a
    normal multi-asset QA template and emit a ``compare_evidence_missing``
    decision note.
    """
    return is_compare_operation(state) and has_compare_evidence(state)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_comparison_tool_output(state: GraphState) -> Any:
    """
    Extract the ``get_performance_comparison`` tool output from step_results.

    Mirrors the lookup logic in ``synthesize._get_tool_output`` but operates
    directly on state so it can be used before synthesize builds its closures.
    """
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        return None

    step_results = artifacts.get("step_results")
    if not isinstance(step_results, dict) or not step_results:
        return None

    # We need the plan steps to identify which step_id maps to the tool.
    plan_ir = state.get("plan_ir")
    steps: list[dict] = []
    if isinstance(plan_ir, dict):
        steps = plan_ir.get("steps") or []

    # Build step_id → step dict index for lookup.
    step_index: dict[str, dict] = {}
    if isinstance(steps, list):
        for s in steps:
            if isinstance(s, dict) and s.get("id"):
                step_index[s["id"]] = s

    for step_id, item in step_results.items():
        if not isinstance(item, dict):
            continue

        output = item.get("output")

        # Skip entries explicitly marked as skipped.
        if isinstance(output, dict) and output.get("skipped"):
            continue

        step = step_index.get(step_id) or {}
        if step.get("kind") == "tool" and step.get("name") == "get_performance_comparison":
            return output

    return None


__all__ = [
    "is_compare_operation",
    "has_compare_evidence",
    "should_render_compare",
]
