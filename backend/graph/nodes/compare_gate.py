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

import re

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
      - The step's ``status_reason`` is not a skip/error sentinel.
      - Output is not a "unable to fetch" total-failure message.
      - The table contains at least one non-N/A metric value.
    """
    result_item = _get_comparison_tool_result(state)
    if result_item is None:
        return False

    # Check status_reason — reject skipped / escalation_not_needed
    status_reason = result_item.get("status_reason", "done")
    if status_reason in _REJECT_STATUS_REASONS:
        return False

    output = result_item.get("output")
    if output is None:
        return False

    text = str(output).strip()
    if not text:
        return False

    text_lower = text.lower()

    # The executor wraps failures as "get_performance_comparison failed: ..."
    if text_lower.startswith("get_performance_comparison failed"):
        return False

    # The tool returns this when no ticker data could be fetched at all
    if "unable to fetch" in text_lower:
        return False

    # Reject all-N/A tables: if every metric cell is N/A, there's no real data
    if _is_all_na_table(text):
        return False

    return True


# Status reasons that indicate the step didn't produce real evidence.
_REJECT_STATUS_REASONS = frozenset({"skipped", "escalation_not_needed"})


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


def _is_all_na_table(text: str) -> bool:
    """
    Return True when the comparison table has data rows but every metric
    cell (Current Price, YTD %, 1-Year %) is N/A.

    Heuristic: skip header/separator lines, then for each data row check
    whether it contains at least one numeric value (digit or +/- sign
    followed by digit).  If no data row has a real number, it's all-N/A.
    """
    lines = text.strip().splitlines()
    data_rows = 0
    rows_with_real_data = 0
    for line in lines:
        stripped = line.strip()
        # Skip empty, header-like, or separator lines
        if not stripped or stripped.startswith("---") or stripped.startswith("==="):
            continue
        if stripped.lower().startswith("performance comparison"):
            continue
        if stripped.lower().startswith("ticker"):
            continue
        if stripped.startswith("Note:") or stripped.startswith("注"):
            continue
        # This is a data row
        data_rows += 1
        # Check if it contains at least one real numeric value
        # (not just N/A or labels)
        if re.search(r"[+-]?\d+\.?\d*%?", stripped):
            rows_with_real_data += 1

    # If there are data rows but none have real numbers → all N/A
    return data_rows > 0 and rows_with_real_data == 0


def _get_comparison_tool_result(state: GraphState) -> dict | None:
    """
    Extract the full ``get_performance_comparison`` step result dict
    from step_results, including ``output`` and ``status_reason``.

    Returns None if the tool step cannot be found.
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
            return item

    return None


__all__ = [
    "is_compare_operation",
    "has_compare_evidence",
    "should_render_compare",
]
