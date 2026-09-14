# -*- coding: utf-8 -*-
"""环境变量解析的单一入口。"""

import os

_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def env_str(key: str, default: str = "") -> str:
    """读取非空字符串并去除首尾空白。"""
    raw = os.getenv(key)
    return raw.strip() if isinstance(raw, str) and raw.strip() else default


def env_int(key: str, default: int) -> int:
    """读取整数；缺失或解析失败时返回默认值。"""
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def env_float(key: str, default: float) -> float:
    """读取浮点数；缺失或解析失败时返回默认值。"""
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def env_bool(key: str, default: bool = False) -> bool:
    """读取布尔值；仅接受约定的真值集合。"""
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY_VALUES


def env_csv(key: str, default: str = "") -> list[str]:
    """读取逗号分隔列表，去除空白项。"""
    return [item.strip() for item in env_str(key, default).split(",") if item.strip()]
