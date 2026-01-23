# -*- coding: utf-8 -*-
"""
Prompts Module - 提示词模板
管理所有 SYSTEM_PROMPT 和模板

注意: 大部分 prompts 已整合到各自组件中:
- Intent Classification: backend/orchestration/intent_classifier.py
- Report Synthesis: backend/orchestration/forum.py (FORUM_SYNTHESIS_PROMPT)
- Followup: backend/prompts/system_prompts.py (FOLLOWUP_SYSTEM_PROMPT)
"""

from .system_prompts import (
    FORUM_SYNTHESIS_PROMPT,
    FOLLOWUP_SYSTEM_PROMPT,
)

__all__ = [
    'FORUM_SYNTHESIS_PROMPT',
    'FOLLOWUP_SYSTEM_PROMPT',
]

