#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Async Supervisor path test for ConversationAgent.
"""

import asyncio

from backend.conversation.agent import ConversationAgent
from backend.orchestration.forum import ForumOutput


class StubSupervisor:
    async def analyze(self, query: str, ticker: str, user_profile=None):
        return {
            "forum_output": ForumOutput(
                consensus=f"{ticker} consensus",
                disagreement="",
                confidence=0.8,
                recommendation="HOLD",
                risks=["risk-1"],
            ),
            "agent_outputs": {},
            "errors": [],
        }


def test_chat_async_uses_supervisor():
    agent = ConversationAgent(supervisor=StubSupervisor())
    result = asyncio.run(agent.chat_async("Analyze AAPL"))

    assert result["intent"] == "report"
    assert result.get("method") == "supervisor"
    assert result.get("report")
    assert result["report"]["ticker"] == "AAPL"
