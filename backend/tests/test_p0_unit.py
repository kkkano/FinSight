# -*- coding: utf-8 -*-
"""
P0 unit tests for the graph pipeline refactoring.

Covers:
  - parse_operation: compare keywords, CJK vs boundary, multi-ticker
    default compare, guardrail A, trace auditability
  - reset_turn_state: all ephemeral fields nullified
  - _match_any: boundary matching for short ASCII tokens
"""
import pytest

from backend.graph.nodes.parse_operation import parse_operation, _match_any
from backend.graph.nodes.reset_turn_state import reset_turn_state


# =========================================================================
# _match_any helper tests
# =========================================================================

class TestMatchAny:
    """Verify keyword matching with non-alphanumeric boundary logic."""

    def test_vs_cjk_adjacency(self):
        """'vs' between CJK chars should match (non-alphanumeric boundary)."""
        hits = _match_any(("vs",), "苹果vs特斯拉")
        assert "vs" in hits

    def test_vs_space_delimited(self):
        """'vs' with spaces should match."""
        hits = _match_any(("vs",), "aapl vs msft")
        assert "vs" in hits

    def test_vs_no_false_positive_in_word(self):
        """'vs' inside 'invest' should NOT match (alphanumeric boundary)."""
        hits = _match_any(("vs",), "invest in stocks")
        assert hits == []

    def test_ma_no_false_positive_in_macro(self):
        """'ma' inside 'macro' should NOT match."""
        hits = _match_any(("ma",), "macro economics")
        assert hits == []

    def test_ma_standalone_match(self):
        """'ma' as standalone token should match."""
        hits = _match_any(("ma",), "看看 ma 走势")
        assert "ma" in hits

    def test_rsi_standalone_match(self):
        """'rsi' as standalone short ASCII token should match."""
        hits = _match_any(("rsi",), "rsi 超买了")
        assert "rsi" in hits

    def test_long_chinese_keyword_substring_match(self):
        """Chinese keywords longer than 3 chars use simple substring match."""
        hits = _match_any(("技术分析",), "做个技术分析看看")
        assert "技术分析" in hits

    def test_empty_query_returns_empty(self):
        hits = _match_any(("vs", "compare"), "")
        assert hits == []

    def test_multiple_hits_returned(self):
        """Multiple matching keywords should all be returned."""
        hits = _match_any(("对比", "比较"), "对比一下，比较看看")
        assert "对比" in hits
        assert "比较" in hits


# =========================================================================
# parse_operation: compare keyword detection
# =========================================================================

class TestParseOperationCompare:
    """Verify compare keyword detection (priority 1)."""

    @pytest.mark.parametrize("query,expected_hit", [
        ("AAPL vs MSFT", "vs"),
        ("苹果vs特斯拉", "vs"),
        ("AAPL versus MSFT", "versus"),
        ("compare AAPL and MSFT", "compare"),
        ("comparison of AAPL and MSFT", "comparison"),
        ("苹果和特斯拉对比", "对比"),
        ("AAPL和MSFT比较", "比较"),
        ("苹果和特斯拉相比如何", "相比"),
        ("两只股票有什么区别", "区别"),
        ("看看差异在哪", "差异"),
        ("哪个更好 AAPL MSFT", "哪个更"),
    ])
    def test_compare_keywords(self, query, expected_hit):
        result = parse_operation({
            "query": query,
            "subject": {"subject_type": "company", "tickers": ["AAPL", "MSFT"]},
        })
        op = result["operation"]
        assert op["name"] == "compare"
        assert op["confidence"] == 0.85

        trace = result["trace"]["operation_decision"]
        assert trace["source"] == "keyword"
        assert expected_hit in trace["keyword_hits"]

    def test_compare_keyword_overrides_multi_ticker(self):
        """Explicit compare keyword should set source='keyword', not 'multi_ticker_default'."""
        result = parse_operation({
            "query": "对比 AAPL 和 TSLA",
            "subject": {"subject_type": "company", "tickers": ["AAPL", "TSLA"]},
        })
        trace = result["trace"]["operation_decision"]
        assert trace["source"] == "keyword"
        assert trace["op"] == "compare"


# =========================================================================
# parse_operation: multi-ticker default compare (priority 3)
# =========================================================================

class TestParseOperationMultiTickerDefault:
    """Verify multi-ticker default compare when no keywords match."""

    def test_two_tickers_no_keywords_defaults_to_compare(self):
        """2+ tickers with no keyword hits → compare via multi_ticker_default."""
        result = parse_operation({
            "query": "那苹果和特斯拉呢",
            "subject": {"subject_type": "company", "tickers": ["AAPL", "TSLA"]},
        })
        op = result["operation"]
        assert op["name"] == "compare"
        assert op["confidence"] == 0.7

        trace = result["trace"]["operation_decision"]
        assert trace["source"] == "multi_ticker_default"
        assert trace["multi_ticker"] is True

    def test_single_ticker_no_keywords_falls_to_qa(self):
        """Single ticker with no keyword hits → qa fallback."""
        result = parse_operation({
            "query": "聊聊苹果吧",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        })
        assert result["operation"]["name"] == "qa"


# =========================================================================
# parse_operation: guardrail A (priority 2 blocks default compare)
# =========================================================================

class TestParseOperationGuardrailA:
    """Verify guardrail A prevents multi-ticker default compare."""

    def test_price_keyword_with_two_tickers_gives_price_not_compare(self):
        """'股价' with 2 tickers → price (guardrail A), NOT compare."""
        result = parse_operation({
            "query": "AAPL 和 TSLA 股价",
            "subject": {"subject_type": "company", "tickers": ["AAPL", "TSLA"]},
        })
        op = result["operation"]
        assert op["name"] == "price"

        trace = result["trace"]["operation_decision"]
        assert trace["guardrail_a_hit"] == "price"
        assert trace["multi_ticker"] is True

    def test_impact_keyword_with_two_tickers_gives_impact_not_compare(self):
        """'影响' with 2 tickers → analyze_impact (guardrail A)."""
        result = parse_operation({
            "query": "对 AAPL 和 TSLA 的影响",
            "subject": {"subject_type": "company", "tickers": ["AAPL", "TSLA"]},
        })
        assert result["operation"]["name"] == "analyze_impact"
        assert result["trace"]["operation_decision"]["guardrail_a_hit"] == "analyze_impact"

    def test_technical_keyword_with_two_tickers_gives_technical(self):
        """'技术面' with 2 tickers → technical (guardrail A)."""
        result = parse_operation({
            "query": "AAPL TSLA 技术面",
            "subject": {"subject_type": "company", "tickers": ["AAPL", "TSLA"]},
        })
        assert result["operation"]["name"] == "technical"
        assert result["trace"]["operation_decision"]["guardrail_a_hit"] == "technical"

    def test_news_keyword_with_two_tickers_gives_fetch(self):
        """'新闻' with 2 tickers → fetch (guardrail A)."""
        result = parse_operation({
            "query": "AAPL 和 TSLA 最新新闻",
            "subject": {"subject_type": "company", "tickers": ["AAPL", "TSLA"]},
        })
        assert result["operation"]["name"] == "fetch"
        assert result["trace"]["operation_decision"]["guardrail_a_hit"] == "fetch"

    def test_summarize_keyword_with_two_tickers_gives_summarize(self):
        """'总结' with 2 tickers → summarize (guardrail A)."""
        result = parse_operation({
            "query": "总结 AAPL 和 TSLA",
            "subject": {"subject_type": "company", "tickers": ["AAPL", "TSLA"]},
        })
        assert result["operation"]["name"] == "summarize"
        assert result["trace"]["operation_decision"]["guardrail_a_hit"] == "summarize"


# =========================================================================
# parse_operation: compare keyword wins over guardrail A
# =========================================================================

class TestCompareKeywordWinsOverGuardrail:
    """Compare keyword (priority 1) must override guardrail A (priority 2)."""

    def test_compare_with_price_keyword_gives_compare(self):
        """'对比' + '股价' → compare (compare keyword is highest priority)."""
        result = parse_operation({
            "query": "对比 AAPL 和 TSLA 的股价",
            "subject": {"subject_type": "company", "tickers": ["AAPL", "TSLA"]},
        })
        assert result["operation"]["name"] == "compare"
        assert result["trace"]["operation_decision"]["guardrail_a_hit"] is None


# =========================================================================
# parse_operation: trace auditability
# =========================================================================

class TestParseOperationTrace:
    """Verify trace.operation_decision is always emitted."""

    def test_trace_has_all_required_fields(self):
        result = parse_operation({
            "query": "分析 AAPL",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        })
        decision = result["trace"]["operation_decision"]
        required_keys = {
            "op", "confidence", "source", "keyword_hits",
            "multi_ticker", "comparison_hint_used", "guardrail_a_hit",
        }
        assert required_keys.issubset(decision.keys())

    def test_trace_preserves_existing_trace_data(self):
        """Existing trace data should not be overwritten."""
        existing_trace = {"spans": [{"node": "prev"}], "some_key": "value"}
        result = parse_operation({
            "query": "test",
            "subject": {},
            "trace": existing_trace,
        })
        trace = result["trace"]
        assert trace["some_key"] == "value"
        assert "operation_decision" in trace

    def test_trace_qa_fallback_confidence_boost_for_question(self):
        """Question-mark queries should get boosted qa confidence (0.55)."""
        result = parse_operation({
            "query": "这只股票怎么样？",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        })
        assert result["operation"]["name"] == "qa"
        assert result["operation"]["confidence"] == 0.55

    def test_trace_qa_fallback_default_confidence(self):
        """Non-question queries with no keyword → qa at 0.4."""
        result = parse_operation({
            "query": "随便看看",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        })
        assert result["operation"]["name"] == "qa"
        assert result["operation"]["confidence"] == 0.4

    def test_comparison_hint_tracked(self):
        """is_comparison from subject should be tracked in trace."""
        result = parse_operation({
            "query": "分析",
            "subject": {"subject_type": "company", "tickers": ["AAPL"], "is_comparison": True},
        })
        assert result["trace"]["operation_decision"]["comparison_hint_used"] is True


# =========================================================================
# reset_turn_state
# =========================================================================

class TestResetTurnState:
    """Verify reset_turn_state nullifies all ephemeral fields."""

    def test_all_decision_fields_nullified(self):
        """All per-turn decision fields must be set to None."""
        result = reset_turn_state({})
        expected_none_keys = [
            "subject", "operation", "clarify", "policy",
            "plan_ir", "artifacts", "chat_responded",
        ]
        for key in expected_none_keys:
            assert key in result, f"Missing key: {key}"
            assert result[key] is None, f"Key {key} should be None, got {result[key]}"

    def test_all_confirmation_fields_nullified(self):
        """All confirmation-gate ephemeral fields must be set to None."""
        result = reset_turn_state({})
        confirmation_keys = [
            "require_confirmation", "confirmation_options",
            "user_confirmation", "confirmation_intent",
            "confirmation_instruction",
        ]
        for key in confirmation_keys:
            assert key in result, f"Missing confirmation key: {key}"
            assert result[key] is None, f"Key {key} should be None, got {result[key]}"

    def test_preserved_fields_not_in_output(self):
        """Fields that should be preserved must NOT appear in reset output."""
        result = reset_turn_state({})
        preserved = [
            "thread_id", "messages", "query", "ui_context",
            "memory_context", "schema_version", "output_mode",
            "strict_selection", "confirmation_mode",
        ]
        for key in preserved:
            assert key not in result, (
                f"Preserved field {key!r} should NOT be in reset output "
                f"(would overwrite the real value)"
            )

    def test_return_type_is_dict(self):
        """reset_turn_state must return a plain dict (partial state update)."""
        result = reset_turn_state({})
        assert isinstance(result, dict)

    def test_exactly_13_keys_returned(self):
        """Exactly 15 keys should be reset (9 decision + 5 confirmation + 1 trace)."""
        result = reset_turn_state({})
        assert len(result) == 15, f"Expected 15 keys, got {len(result)}: {list(result.keys())}"

    def test_trace_runtime_subkeys_cleared(self):
        """Per-turn trace runtime sub-keys must be removed."""
        state = {
            "trace": {
                "events": [{"node": "build_initial_state", "ts": "2026-01-01T00:00:00Z"}],
                "timings": {"build_initial_state": 10},
                "operation_decision": {"rule": "compare_keywords", "hits": ["对比"]},
                "planner_runtime": {"mode": "stub", "steps": 3},
                "synthesize_runtime": {"mode": "stub"},
                "executor": {"steps_executed": 2},
                "rag": {"chunks": 5},
            }
        }
        result = reset_turn_state(state)
        trace = result["trace"]
        # Spans preserved
        assert "events" in trace
        assert "timings" in trace
        assert len(trace["events"]) == 1
        # Runtime sub-keys cleared
        assert "operation_decision" not in trace
        assert "planner_runtime" not in trace
        assert "synthesize_runtime" not in trace
        assert "executor" not in trace
        assert "rag" not in trace

    def test_trace_empty_when_no_prior_trace(self):
        """When no prior trace exists, reset returns empty trace dict."""
        result = reset_turn_state({})
        assert result["trace"] == {}

    def test_trace_spans_capped_at_max(self):
        """Spans exceeding MAX_TRACE_SPANS should be truncated (keep newest)."""
        from backend.graph.trace import MAX_TRACE_SPANS

        oversized_spans = [{"node": f"n{i}", "ts": f"t{i}"} for i in range(MAX_TRACE_SPANS + 50)]
        state = {"trace": {"spans": oversized_spans}}
        result = reset_turn_state(state)
        spans = result["trace"]["spans"]
        assert len(spans) == MAX_TRACE_SPANS
        # Should keep the newest (tail) spans
        assert spans[0]["node"] == "n50"
        assert spans[-1]["node"] == f"n{MAX_TRACE_SPANS + 49}"

    def test_trace_spans_under_limit_untouched(self):
        """Spans under the limit should pass through unchanged."""
        from backend.graph.trace import MAX_TRACE_SPANS

        small_spans = [{"node": f"n{i}"} for i in range(10)]
        state = {"trace": {"spans": small_spans}}
        result = reset_turn_state(state)
        assert len(result["trace"]["spans"]) == 10


# =========================================================================
# with_node_trace: spans cap
# =========================================================================

class TestWithNodeTraceSpansCap:
    """Verify with_node_trace caps spans at MAX_TRACE_SPANS."""

    @pytest.mark.asyncio
    async def test_spans_capped_after_append(self):
        """When existing spans are at the limit, new span should trigger truncation."""
        from unittest.mock import AsyncMock, patch
        from backend.graph.trace import with_node_trace, MAX_TRACE_SPANS

        oversized_spans = [{"node": f"old{i}", "ts": f"t{i}"} for i in range(MAX_TRACE_SPANS)]
        state = {"trace": {"spans": oversized_spans}}

        def dummy_node(s):
            return {}

        with patch("backend.graph.trace.emit_event", new_callable=AsyncMock), \
             patch("backend.graph.trace.langfuse_span") as mock_lf:
            # Make langfuse_span a no-op async context manager
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=None)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_lf.return_value = mock_ctx

            wrapped = with_node_trace("test_node", dummy_node)
            result = await wrapped(state)

        spans = result["trace"]["spans"]
        assert len(spans) == MAX_TRACE_SPANS
        # The newest span (just appended) should be last
        assert spans[-1]["node"] == "test_node"
        # Oldest span should have been dropped
        assert spans[0]["node"] == "old1"
