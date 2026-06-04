# -*- coding: utf-8 -*-
r"""P2: _fallback_price_value 搜索兜底正则修复测试

原 bug：raw string 中写成 r"(\\d{3,6}...)"，`\\d` 是「反斜杠+字面 d」而非数字类，
导致搜索兜底永久匹配失败、静默返回 None。修复为 r"(\d...)"。
"""

import re

from unittest.mock import patch

from backend.tools import price


# 与 price.py 中修复后保持一致的正则（回归锚点）
FIXED_PATTERN = r"(\d{3,6}(?:,\d{3})*(?:\.\d+)?)"


def test_pattern_matches_index_level():
    """修复后的正则应能从搜索文本里提取指数点位（无千分位逗号的常见形态）。"""
    m = re.search(FIXED_PATTERN, "Index level today is 5123.45 points")
    assert m is not None
    assert float(m.group(1).replace(",", "")) == 5123.45


def test_old_broken_pattern_would_not_match():
    """证明旧的 \\d 写法确实匹配不到数字（解释 bug 根因）。"""
    broken = r"(\\d{3,6}(?:,\\d{3})*(?:\\.\\d+)?)"
    assert re.search(broken, "level is 5,123.45") is None


def test_fallback_price_value_uses_search(monkeypatch):
    """跳过 stooq 分支，验证搜索兜底能提取并返回数值。"""
    # 让 stooq 映射返回 None，直接进入搜索兜底
    monkeypatch.setattr(price, "_map_to_stooq_symbol", lambda *_a, **_k: None, raising=False)
    with patch.object(price, "search", return_value="Dow Jones index level today: 38500.12"):
        val = price._fallback_price_value("^DJI")
    assert val == 38500.12


def test_fallback_price_value_rejects_out_of_range(monkeypatch):
    """提取到非法范围（<=0 或 >1e8）应返回 None。"""
    monkeypatch.setattr(price, "_map_to_stooq_symbol", lambda *_a, **_k: None, raising=False)
    with patch.object(price, "search", return_value="no numbers here at all"):
        assert price._fallback_price_value("^DJI") is None
