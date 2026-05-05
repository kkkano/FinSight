# -*- coding: utf-8 -*-
"""
Conversation 模块
包含仍在运行时使用的会话上下文组件。

旧的 ConversationAgent / ConversationRouter / SchemaToolRouter 已归档到
docs/archive/2026-05-04_legacy_conversation_stack。当前用户对话主路径是
backend.graph.runner / backend.graph.nodes.understand_request。
"""

from backend.conversation.context import ContextManager, ConversationTurn, MessageRole

__all__ = [
    'ContextManager',
    'ConversationTurn', 
    'MessageRole',
]
