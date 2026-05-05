# -*- coding: utf-8 -*-
"""
Architecture Refactor Regression Tests (Phase 5.3)

Validates the "single entry + single router + single clarify" principle:
1. "分析股票" → SchemaRouter triggers clarify for missing ticker
2. "TSLA 分析" → Supervisor executes normally
3. Simple price query → ChatHandler fast-path returns quickly

References:
- docs/Thinking/2026-01-31_architecture_refactor_guide.md
- Phase 5.4 回归测试
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.conversation.agent import ConversationAgent
from backend.conversation import schema_router
from backend.orchestration.forum import ForumOutput
from backend.orchestration.intent_classifier import ClassificationResult, AgentIntent


# ========== Mock Classes ==========

class MockLLM:
    """Mock LLM for deterministic testing - returns tool routing JSON."""

    def __init__(self, tool_response: str = None):
        self._tool_response = tool_response

    def invoke(self, messages):
        """Sync invoke for SchemaRouter."""
        content = self._tool_response or '{"tool_name":"clarify","args":{},"confidence":0.3}'
        return type("Response", (), {"content": content})()


class StubSupervisor:
    """Stub Supervisor that returns predictable results."""

    async def process(
        self,
        query: str,
        tickers=None,
        user_profile=None,
        context_summary=None,
        context_ticker=None,
        on_event=None
    ):
        ticker = tickers[0] if tickers else "AAPL"
        return type("Result", (), {
            "success": True,
            "intent": AgentIntent.REPORT,
            "response": f"Mock analysis for {ticker}",
            "forum_output": ForumOutput(
                consensus=f"{ticker} consensus",
                disagreement="",
                confidence=0.85,
                recommendation="HOLD",
                risks=["mock-risk-1"],
            ),
            "agent_outputs": {},
            "classification": ClassificationResult(
                intent=AgentIntent.REPORT,
                confidence=0.95,
                tickers=[ticker],
                method="stub",
                reasoning="mock classification",
                scores={},
            ),
            "errors": [],
            "budget": None,
        })()

    def _build_report_ir(self, result, ticker, classification):
        return {"ticker": ticker}

    def _build_fallback_report(self, result, ticker, classification):
        return {"ticker": ticker}


class DummyContext:
    """Minimal context for SchemaRouter testing."""

    def __init__(self):
        self.pending_tool_call = None

    def get_summary(self):
        return ""


# ========== T1: Clarify Path Tests ==========

@pytest.mark.skipif(
    not schema_router.LANGCHAIN_AVAILABLE,
    reason="langchain_core not available"
)
class TestClarifyPath:
    """T1-T3: Tests for clarify/追问 path via SchemaRouter."""

    def test_analyze_stock_without_ticker_triggers_clarify(self):
        """
        T1: "分析股票" without ticker should trigger clarify.

        Expected:
        - intent: clarify
        - schema_action: clarify
        - schema_missing contains ticker field
        - pending_tool_call is set
        """
        # Mock LLM returns analyze_stock with null ticker
        llm = MockLLM('{"tool_name":"analyze_stock","args":{"ticker":null},"confidence":0.9}')
        router = schema_router.SchemaToolRouter(llm)
        context = DummyContext()

        result = router.route_query("分析股票", context)

        assert result is not None
        assert result.intent == "clarify"
        assert result.metadata.get("schema_action") == "clarify"

        missing = result.metadata.get("schema_missing") or []
        assert any(item.get("field") == "ticker" for item in missing)
        assert result.metadata.get("source") == "schema_router"
        assert context.pending_tool_call is not None

    def test_company_name_only_needs_intent_clarify(self):
        """
        T2: Company name without action should trigger intent clarification.

        Query: "特斯拉" (Tesla in Chinese)
        Expected: clarify with intent field missing
        """
        llm = MockLLM('{"tool_name":"get_market_sentiment","args":{},"confidence":0.9}')
        router = schema_router.SchemaToolRouter(llm)
        context = DummyContext()

        result = router.route_query("特斯拉", context)

        assert result is not None
        assert result.metadata.get("schema_action") == "clarify"
        missing = result.metadata.get("schema_missing") or []
        assert any(item.get("field") == "intent" for item in missing)

    def test_ticker_only_needs_intent_clarify(self):
        """
        T2b: Ticker only (e.g., "AAPL") should trigger intent clarification.

        This validates the company_name_only rule in SlotCompletenessGate.
        """
        # Even if LLM returns a tool with valid args, short ticker-only query should clarify
        llm = MockLLM('{"tool_name":"get_price","args":{"ticker":"AAPL"},"confidence":0.9}')
        router = schema_router.SchemaToolRouter(llm)
        context = DummyContext()

        result = router.route_query("AAPL", context)

        assert result is not None
        assert result.metadata.get("schema_action") == "clarify"
        assert result.metadata.get("clarify_reason") == "company_name_only"

    def test_company_with_action_verb_executes(self):
        """
        T2c: Company name WITH action verb should execute, not clarify.

        Query: "分析特斯拉" or "特斯拉价格"
        Expected: execute (not clarify)
        """
        llm = MockLLM('{"tool_name":"analyze_stock","args":{"ticker":"TSLA"},"confidence":0.9}')
        router = schema_router.SchemaToolRouter(llm)
        context = DummyContext()

        result = router.route_query("分析特斯拉", context)

        assert result is not None
        assert result.metadata.get("schema_action") == "execute"
        assert "TSLA" in result.metadata.get("tickers", [])

    def test_followup_after_clarify_fills_ticker(self):
        """
        T3: After clarify, providing ticker should execute.

        Step 1: "帮我查一下价格" -> clarify (missing ticker)
        Step 2: "TSLA" -> execute with filled ticker
        """
        llm = MockLLM('{"tool_name":"get_price","args":{"ticker":null},"confidence":0.9}')
        router = schema_router.SchemaToolRouter(llm)
        context = DummyContext()

        # Step 1: Initial query triggers clarify
        result1 = router.route_query("帮我查一下价格", context)
        assert result1.intent == "clarify"
        assert context.pending_tool_call is not None

        # Step 2: Followup with ticker fills the arg
        result2 = router.route_query("TSLA", context)
        assert result2.metadata.get("schema_action") == "execute"
        assert result2.metadata.get("schema_args", {}).get("ticker") == "TSLA"
        assert "TSLA" in result2.metadata.get("tickers", [])


# ========== T4-T6: Supervisor Path Tests ==========

class TestSupervisorPath:
    """T4-T6: Tests for Supervisor execution path."""

    def test_tsla_analysis_uses_supervisor(self):
        """
        T4: "TSLA 分析" should use Supervisor and return report.

        Expected:
        - intent: report
        - method: supervisor
        - report contains ticker
        """
        agent = ConversationAgent(supervisor=StubSupervisor())
        result = agent.chat("TSLA 分析")

        assert result["intent"] == "report"
        assert result.get("method") == "supervisor"
        assert result.get("report") is not None
        assert result["report"]["ticker"] == "TSLA"

    def test_detailed_analysis_uses_supervisor(self):
        """
        T5: "详细分析 AAPL" should route to Supervisor.

        Expected:
        - success: True
        - intent: report
        - agent_used: True
        """
        agent = ConversationAgent(supervisor=StubSupervisor())
        result = agent.chat("详细分析 AAPL")

        assert result.get("success", True) is True
        assert result["intent"] == "report"
        assert result.get("agent_used") is True

    def test_multi_ticker_comparison_uses_supervisor(self):
        """
        T6: Multi-ticker comparison should use Supervisor.

        Query: "对比 AAPL 和 MSFT"
        Expected: Uses comparison or report flow
        """
        agent = ConversationAgent(supervisor=StubSupervisor())
        result = agent.chat("对比 AAPL 和 MSFT")

        # Should succeed and either be comparison or report intent
        assert result.get("success", True) is True
        assert result.get("intent") in ("comparison", "report", "chat")


# ========== T7-T9: Fast Path Tests ==========

class TestFastPath:
    """T7-T9: Tests for ChatHandler fast-path."""

    def test_simple_price_query_fast_path(self):
        """
        T7: Simple price query should use fast-path (ChatHandler).

        Query: "AAPL 价格"
        Expected:
        - Does NOT use Supervisor
        - Returns quickly via ChatHandler
        """
        # No supervisor injected -> must use ChatHandler
        agent = ConversationAgent(supervisor=None)
        result = agent.chat("AAPL 价格")

        # Should succeed without Supervisor
        assert result.get("success", True) is True
        assert result.get("agent_used") is not True

    def test_greeting_skips_supervisor(self):
        """
        T8: Greeting should skip Supervisor entirely.

        Query: "你好"
        Expected:
        - intent: greeting
        - No Supervisor invocation
        """
        agent = ConversationAgent(supervisor=StubSupervisor())
        result = agent.chat("你好")

        assert result["intent"] == "greeting"
        # Greeting should never use supervisor
        assert result.get("agent_used") is not True

    def test_schema_direct_tool_skips_supervisor(self):
        """
        T9: Schema-direct tool (get_price, get_news) should skip Supervisor.

        When SchemaRouter returns execute with a simple tool,
        the agent should use ChatHandler's handle_schema_tool directly.
        """
        # This test validates the schema_direct path in ConversationAgent.chat()
        agent = ConversationAgent(supervisor=StubSupervisor())

        # Simple price query should be handled by ChatHandler
        result = agent.chat("苹果股价多少")

        assert result.get("success", True) is True
        # Should not use full supervisor for simple price
        intent = result.get("intent")
        # Price intent should be chat or price, not report
        assert intent in ("chat", "price", "greeting")


# ========== T10-T12: Edge Cases ==========

class TestEdgeCases:
    """T10-T12: Edge case tests for architecture robustness."""

    @pytest.mark.skipif(
        not schema_router.LANGCHAIN_AVAILABLE,
        reason="langchain_core not available"
    )
    def test_unknown_tool_falls_back_to_clarify(self):
        """
        T10: Unknown tool from LLM should fallback to clarify.
        """
        llm = MockLLM('{"tool_name":"unknown_tool","args":{},"confidence":0.9}')
        router = schema_router.SchemaToolRouter(llm)
        context = DummyContext()

        result = router.route_query("test unknown", context)

        assert result is not None
        assert result.intent == "clarify"
        assert result.metadata.get("clarify_reason") == "unknown_tool"

    @pytest.mark.skipif(
        not schema_router.LANGCHAIN_AVAILABLE,
        reason="langchain_core not available"
    )
    def test_low_confidence_triggers_clarify(self):
        """
        T11: Low confidence (<0.7) should trigger clarify.
        """
        llm = MockLLM('{"tool_name":"get_price","args":{"ticker":"AAPL"},"confidence":0.5}')
        router = schema_router.SchemaToolRouter(llm)
        context = DummyContext()

        result = router.route_query("maybe check price", context)

        assert result is not None
        assert result.intent == "clarify"
        assert result.metadata.get("clarify_reason") == "low_confidence"

    @pytest.mark.skipif(
        not schema_router.LANGCHAIN_AVAILABLE,
        reason="langchain_core not available"
    )
    def test_invalid_json_triggers_clarify(self):
        """
        T12: Invalid JSON from LLM should fallback to clarify.
        """
        llm = MockLLM('not valid json {{{')
        router = schema_router.SchemaToolRouter(llm)
        context = DummyContext()

        result = router.route_query("test invalid", context)

        assert result is not None
        assert result.intent == "clarify"
        assert result.metadata.get("clarify_reason") == "invalid_tool_response"


# ========== Integration Sanity Check ==========

def test_imports_sanity():
    """Verify all imports work correctly."""
    from backend.conversation.agent import ConversationAgent
    from backend.conversation.router import ConversationRouter
    from backend.conversation.schema_router import SchemaToolRouter
    from backend.handlers.chat_handler import ChatHandler

    assert ConversationAgent is not None
    assert ConversationRouter is not None
    assert SchemaToolRouter is not None
    assert ChatHandler is not None
