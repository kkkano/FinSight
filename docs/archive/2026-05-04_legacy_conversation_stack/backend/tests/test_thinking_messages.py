#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for thinking trace messages.
"""

import asyncio

from backend.conversation.agent import ConversationAgent


def test_chat_async_thinking_messages_are_readable():
    agent = ConversationAgent(llm=None, orchestrator=None, report_agent=None, supervisor=None)
    result = asyncio.run(agent.chat_async("\u4f60\u597d", capture_thinking=True))
    thinking = result.get("thinking", [])
    messages = [step.get("message", "") for step in thinking if step.get("message")]
    assert any("\u6b63\u5728\u89e3\u6790\u4e0a\u4e0b\u6587" in msg for msg in messages)
