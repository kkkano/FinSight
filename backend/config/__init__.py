# -*- coding: utf-8 -*-
"""
FinSight Config Module
集中化配置管理
"""

from .keywords import KeywordsConfig, config as _config
from ..llm_config import get_llm_config


def get_keywords():
	"""Compatibility shim: return the global `config` instance."""
	return _config


# Expose expected names for older imports
KeywordConfig = KeywordsConfig  # keep legacy name for compatibility

__all__ = ['KeywordsConfig', 'KeywordConfig', 'get_keywords', 'get_llm_config']
