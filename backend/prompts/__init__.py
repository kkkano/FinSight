# -*- coding: utf-8 -*-
"""
Prompts Module - 提示词模板
管理所有 SYSTEM_PROMPT 和模板

注意: 大部分 prompts 已整合到各自组件中:
- Report Synthesis: FORUM_SYNTHESIS_PROMPT (backend/prompts/system_prompts.py)
- 旧 Followup prompt 已随 legacy conversation stack 归档
"""

from .system_prompts import (
    FORUM_SYNTHESIS_PROMPT,
)

__all__ = [
    'FORUM_SYNTHESIS_PROMPT',
]

