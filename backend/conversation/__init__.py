# -*- coding: utf-8 -*-
"""
Conversation 模块
包含对话管理的核心组件
"""

from backend.conversation.context import ContextManager, ConversationTurn, MessageRole
from backend.conversation.router import ConversationRouter, Intent
from backend.conversation.agent import ConversationAgent, create_agent

__all__ = [
    'ContextManager',
    'ConversationTurn', 
    'MessageRole',
    'ConversationRouter',
    'Intent',
    'ConversationAgent',
    'create_agent',
]
