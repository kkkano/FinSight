# -*- coding: utf-8 -*-
"""
Unit tests for compare_gate shared helper (P1-01).

Covers:
  - is_compare_operation: operation.name detection
  - has_compare_evidence: step_results extraction and validation
  - should_render_compare: single source of truth predicate
"""
import pytest

from backend.graph.nodes.compare_gate import (
    has_compare_evidence,
    is_compare_operation,
    should_render_compare,
)


# =========================================================================
# is_compare_operation
# =========================================================================

class TestIsCompareOperation:
    def test_true_when_operation_is_compare(self):
        state = {"operation": {"name": "compare", "confidence": 0.85, "params": {}}}
        assert is_compare_operation(state) is True

    def test_false_when_operation_is_qa(self):
        state = {"operation": {"name": "qa", "confidence": 0.4, "params": {}}}
        assert is_compare_operation(state) is False

    def test_false_when_operation_is_price(self):
        state = {"operation": {"name": "price", "confidence": 0.8, "params": {}}}
        assert is_compare_operation(state) is False

    def test_false_when_operation_missing(self):
        assert is_compare_operation({}) is False

    def test_false_when_operation_is_none(self):
        assert is_compare_operation({"operation": None}) is False

    def test_false_when_operation_is_string(self):
        """Defensive: operation should be dict, not string."""
        assert is_compare_operation({"operation": "compare"}) is False


# =========================================================================
# has_compare_evidence
# =========================================================================

def _make_state_with_evidence(tool_output, *, step_name="get_performance_comparison"):
    """Build a minimal state with step_results containing a tool output."""
    return {
        "plan_ir": {
            "steps": [{"id": "s1", "kind": "tool", "name": step_name}],
        },
        "artifacts": {
            "step_results": {
                "s1": {"output": tool_output},
            },
        },
    }


class TestHasCompareEvidence:
    def test_true_with_valid_table_output(self):
        table = "Ticker  Current  YTD  1Y\nAAPL  +12%  +15%  +20%\nMSFT  +8%  +10%  +18%"
        state = _make_state_with_evidence(table)
        assert has_compare_evidence(state) is True

    def test_false_when_output_is_none(self):
        state = _make_state_with_evidence(None)
        assert has_compare_evidence(state) is False

    def test_false_when_output_is_empty_string(self):
        state = _make_state_with_evidence("")
        assert has_compare_evidence(state) is False

    def test_false_when_output_is_whitespace(self):
        state = _make_state_with_evidence("   \n  ")
        assert has_compare_evidence(state) is False

    def test_false_when_output_is_failure_prefix(self):
        state = _make_state_with_evidence(
            "get_performance_comparison failed: API timeout"
        )
        assert has_compare_evidence(state) is False

    def test_false_when_output_is_failure_prefix_with_colon(self):
        state = _make_state_with_evidence(
            "Get_Performance_Comparison Failed: rate limit"
        )
        assert has_compare_evidence(state) is False

    def test_false_when_output_skipped(self):
        state = {
            "plan_ir": {
                "steps": [{"id": "s1", "kind": "tool", "name": "get_performance_comparison"}],
            },
            "artifacts": {
                "step_results": {
                    "s1": {"output": {"skipped": True}},
                },
            },
        }
        assert has_compare_evidence(state) is False

    def test_false_when_no_artifacts(self):
        assert has_compare_evidence({}) is False

    def test_false_when_no_step_results(self):
        state = {"artifacts": {}}
        assert has_compare_evidence(state) is False

    def test_false_when_tool_not_in_steps(self):
        """If step_results exists but no step maps to the comparison tool."""
        state = {
            "plan_ir": {
                "steps": [{"id": "s1", "kind": "tool", "name": "other_tool"}],
            },
            "artifacts": {
                "step_results": {
                    "s1": {"output": "some data"},
                },
            },
        }
        assert has_compare_evidence(state) is False

    def test_true_with_numeric_output(self):
        """Non-string truthy output should be considered valid evidence."""
        state = _make_state_with_evidence({"AAPL": 150.0, "MSFT": 380.0})
        assert has_compare_evidence(state) is True


# =========================================================================
# should_render_compare
# =========================================================================

class TestShouldRenderCompare:
    def test_true_when_compare_operation_with_evidence(self):
        """Requires BOTH operation=compare AND valid tool evidence."""
        state = {
            "operation": {"name": "compare", "confidence": 0.85, "params": {}},
            **_make_state_with_evidence("Ticker Current YTD 1Y\nAAPL +12% +15% +20%"),
        }
        assert should_render_compare(state) is True

    def test_false_when_compare_operation_without_evidence(self):
        """Gap-1 fix: compare intent but no evidence → degrade to QA."""
        state = {"operation": {"name": "compare", "confidence": 0.85, "params": {}}}
        assert should_render_compare(state) is False

    def test_false_when_compare_operation_with_failed_evidence(self):
        """Compare intent but tool returned failure → degrade to QA."""
        state = {
            "operation": {"name": "compare", "confidence": 0.85, "params": {}},
            **_make_state_with_evidence("get_performance_comparison failed: timeout"),
        }
        assert should_render_compare(state) is False

    def test_false_when_qa_with_two_tickers(self):
        """The old bug: 2 tickers + qa → should NOT render as compare."""
        state = {
            "operation": {"name": "qa", "confidence": 0.4, "params": {}},
            "subject": {"tickers": ["AAPL", "TSLA"], "subject_type": "company"},
        }
        assert should_render_compare(state) is False

    def test_false_when_price_with_two_tickers(self):
        """Guardrail A: price intent with 2 tickers → should NOT render as compare."""
        state = {
            "operation": {"name": "price", "confidence": 0.8, "params": {}},
            "subject": {"tickers": ["AAPL", "TSLA"], "subject_type": "company"},
        }
        assert should_render_compare(state) is False

    def test_false_when_fetch_with_two_tickers(self):
        state = {
            "operation": {"name": "fetch", "confidence": 0.65, "params": {}},
            "subject": {"tickers": ["AAPL", "TSLA"], "subject_type": "company"},
        }
        assert should_render_compare(state) is False

    def test_false_when_no_operation(self):
        assert should_render_compare({}) is False
