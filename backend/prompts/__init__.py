# -*- coding: utf-8 -*-
"""
Prompts Module - 提示词模板
管理所有 SYSTEM_PROMPT 和模板
"""

from .system_prompts import (
    CHAT_SYSTEM_PROMPT,
    REPORT_SYSTEM_PROMPT,
    ALERT_SYSTEM_PROMPT,
    CLASSIFICATION_PROMPT,
)

__all__ = [
    'CHAT_SYSTEM_PROMPT',
    'REPORT_SYSTEM_PROMPT', 
    'ALERT_SYSTEM_PROMPT',
    'CLASSIFICATION_PROMPT',
]

