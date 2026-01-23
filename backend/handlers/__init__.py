# -*- coding: utf-8 -*-
"""
Handlers 模块
包含不同意图的处理器
"""

from backend.handlers.chat_handler import ChatHandler
from backend.handlers.followup_handler import FollowupHandler

__all__ = [
    'ChatHandler',
    'FollowupHandler',
]
