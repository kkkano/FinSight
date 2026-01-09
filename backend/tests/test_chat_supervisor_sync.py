#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Supervisor path test for ConversationAgent.chat().
"""

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


def test_chat_sync_uses_supervisor_when_no_loop():
    agent = ConversationAgent(supervisor=StubSupervisor())
    result = agent.chat("Analyze AAPL")

    assert result["intent"] == "report"
    assert result.get("method") == "supervisor"
    assert result.get("report")
    assert result["report"]["ticker"] == "AAPL"
