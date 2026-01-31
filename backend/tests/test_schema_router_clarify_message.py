# -*- coding: utf-8 -*-
"""
Test: SchemaRouter clarify message pass-through

Bug: When LLM returns tool_name='clarify' with a dynamic message in args,
the router was discarding it and using a fixed template instead.

Fix: Use args.get('message') if available, fallback to CLARIFY_TEMPLATES['default'].
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def schema_router():
    """Create a SchemaToolRouter with a mock LLM."""
    from backend.conversation.schema_router import SchemaToolRouter
    mock_llm = MagicMock()
    return SchemaToolRouter(llm=mock_llm, confidence_threshold=0.7)


@pytest.fixture
def mock_context():
    """Create a minimal mock context."""
    ctx = MagicMock()
    ctx.pending_tool_call = None
    ctx.get_summary.return_value = ""
    return ctx


class TestClarifyMessagePassThrough:
    """Verify that LLM-generated clarify messages are passed to frontend."""

    def test_clarify_with_llm_message(self, schema_router, mock_context):
        """LLM returns clarify with a custom message → question should use it."""
        llm_response_payload = {
            "tool_name": "clarify",
            "args": {
                "message": "您是想了解特斯拉（TSLA）的实时股价、深度分析报告，还是最新的公司新闻？"
            },
            "confidence": 0.40,
        }

        with patch.object(
            schema_router, "_call_llm_for_tool", return_value=llm_response_payload
        ):
            result = schema_router.route_query("特斯拉", mock_context)

        assert result is not None
        assert result.intent == "clarify"
        assert result.metadata["schema_action"] == "clarify"
        # The key assertion: question should be the LLM message, not the template
        assert result.metadata["schema_question"] == (
            "您是想了解特斯拉（TSLA）的实时股价、深度分析报告，还是最新的公司新闻？"
        )

    def test_clarify_without_message_uses_template(self, schema_router, mock_context):
        """LLM returns clarify without a message → fallback to default template."""
        from backend.conversation.schema_router import CLARIFY_TEMPLATES

        llm_response_payload = {
            "tool_name": "clarify",
            "args": {"reason": "ambiguous_query"},
            "confidence": 0.30,
        }

        with patch.object(
            schema_router, "_call_llm_for_tool", return_value=llm_response_payload
        ):
            result = schema_router.route_query("什么东西", mock_context)

        assert result is not None
        assert result.intent == "clarify"
        assert result.metadata["schema_question"] == CLARIFY_TEMPLATES["default"]

    def test_clarify_with_empty_message_uses_template(self, schema_router, mock_context):
        """LLM returns clarify with empty message → fallback to default template."""
        from backend.conversation.schema_router import CLARIFY_TEMPLATES

        llm_response_payload = {
            "tool_name": "clarify",
            "args": {"message": ""},
            "confidence": 0.35,
        }

        with patch.object(
            schema_router, "_call_llm_for_tool", return_value=llm_response_payload
        ):
            result = schema_router.route_query("嗯", mock_context)

        assert result is not None
        assert result.intent == "clarify"
        # Empty string is falsy → should fall back to template
        assert result.metadata["schema_question"] == CLARIFY_TEMPLATES["default"]

    def test_clarify_reason_preserved(self, schema_router, mock_context):
        """Verify that args.reason is correctly extracted."""
        llm_response_payload = {
            "tool_name": "clarify",
            "args": {
                "message": "请提供更多信息",
                "reason": "missing_action",
            },
            "confidence": 0.45,
        }

        with patch.object(
            schema_router, "_call_llm_for_tool", return_value=llm_response_payload
        ):
            result = schema_router.route_query("谷歌", mock_context)

        assert result is not None
        assert result.metadata["clarify_reason"] == "missing_action"
        assert result.metadata["schema_question"] == "请提供更多信息"

    def test_low_confidence_non_clarify_uses_template(self, schema_router, mock_context):
        """Low confidence non-clarify tool → should use low_confidence template."""
        from backend.conversation.schema_router import CLARIFY_TEMPLATES

        llm_response_payload = {
            "tool_name": "get_price",
            "args": {"ticker": "AAPL"},
            "confidence": 0.30,
        }

        with patch.object(
            schema_router, "_call_llm_for_tool", return_value=llm_response_payload
        ):
            result = schema_router.route_query("苹果怎么样", mock_context)

        assert result is not None
        assert result.intent == "clarify"
        assert result.metadata["schema_question"] == CLARIFY_TEMPLATES["low_confidence"]
        assert result.metadata["clarify_reason"] == "low_confidence"
