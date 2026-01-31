#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Async Supervisor path test for ConversationAgent.
"""

import asyncio

from backend.conversation.agent import ConversationAgent
from backend.orchestration.forum import ForumOutput
from backend.orchestration.intent_classifier import ClassificationResult, AgentIntent


class StubSupervisor:
    async def process(self, query: str, tickers=None, user_profile=None, context_summary=None, context_ticker=None, on_event=None):
        ticker = tickers[0] if tickers else "AAPL"
        return type("Result", (), {
            "success": True,
            "intent": AgentIntent.REPORT,
            "response": f"{ticker} consensus",
            "forum_output": ForumOutput(
                consensus=f"{ticker} consensus",
                disagreement="",
                confidence=0.8,
                recommendation="HOLD",
                risks=["risk-1"],
            ),
            "agent_outputs": {},
            "classification": ClassificationResult(
                intent=AgentIntent.REPORT,
                confidence=1.0,
                tickers=[ticker],
                method="test",
                reasoning="forced",
                scores={},
            ),
            "errors": [],
            "budget": None,
        })()

    def _build_report_ir(self, result, ticker, classification):
        return {"ticker": ticker}

    def _build_fallback_report(self, result, ticker, classification):
        return {"ticker": ticker}


def test_chat_async_uses_supervisor():
    agent = ConversationAgent(supervisor=StubSupervisor())
    result = asyncio.run(agent.chat_async("Analyze AAPL"))

    assert result["intent"] == "report"
    assert result.get("method") == "supervisor"
    assert result.get("report")
    assert result["report"]["ticker"] == "AAPL"
