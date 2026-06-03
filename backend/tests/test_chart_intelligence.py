# -*- coding: utf-8 -*-
"""
图表智能选型（LLM 决策）单元测试。

覆盖：
- LLM 返回各类型 JSON → 正确解析
- LLM 超时 / 失败 → 回退关键词匹配（detector=keyword_fallback）
- LLM 返回非法 JSON → 回退
- LLM 返回不支持的 chart_type → 回退或修正
- 寒暄类 query → should_generate=False
- _extract_json / _normalize_llm_result 等纯函数行为
"""

from __future__ import annotations

import asyncio

import pytest

from backend.api import chart_intelligence as ci
from backend.api.chart_intelligence import (
    SUPPORTED_CHART_TYPES,
    _extract_json,
    _normalize_llm_result,
    decide_chart,
)


class _FakeResponse:
    """模拟 LLM 返回对象（带 .content）。"""

    def __init__(self, content: str):
        self.content = content


def _patch_llm(monkeypatch, content: str | None = None, *, raise_exc: Exception | None = None,
               timeout: bool = False):
    """把 _llm_decide 依赖的 create_llm / ainvoke_with_rate_limit_retry 打桩。

    通过替换 chart_intelligence 模块内 import 的目标符号实现。
    由于这些符号在函数内部 import，这里改为直接替换 _llm_decide 用到的
    底层调用：patch create_llm 返回哑对象，patch retry 返回内容。
    """
    import backend.llm_config as llm_config
    import backend.services.llm_retry as llm_retry

    monkeypatch.setattr(llm_config, "create_llm", lambda **_kwargs: object())

    async def _fake_ainvoke(*_args, **_kwargs):
        if timeout:
            await asyncio.sleep(ci._LLM_DECIDE_TIMEOUT_SEC + 1)
        if raise_exc is not None:
            raise raise_exc
        return _FakeResponse(content or "")

    monkeypatch.setattr(llm_retry, "ainvoke_with_rate_limit_retry", _fake_ainvoke)


# ──────────────────────────────────────────────────────────────────────────
# 纯函数：_extract_json
# ──────────────────────────────────────────────────────────────────────────

def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_code_fence():
    text = "```json\n{\"chart_type\": \"pie\"}\n```"
    assert _extract_json(text) == {"chart_type": "pie"}


def test_extract_json_with_surrounding_text():
    text = '好的，结果是 {"should_generate": true, "chart_type": "bar"} 谢谢'
    assert _extract_json(text) == {"should_generate": True, "chart_type": "bar"}


def test_extract_json_invalid_returns_none():
    assert _extract_json("this is not json at all") is None
    assert _extract_json("") is None


# ──────────────────────────────────────────────────────────────────────────
# 纯函数：_normalize_llm_result
# ──────────────────────────────────────────────────────────────────────────

def test_normalize_pie_composition():
    parsed = {
        "should_generate": True,
        "chart_type": "pie",
        "data_kind": "composition",
        "confidence": 0.9,
        "title": "AAPL 营收构成",
        "reason": "构成占比",
    }
    result = _normalize_llm_result(parsed, "AAPL 营收构成", "AAPL")
    assert result is not None
    assert result["should_generate"] is True
    assert result["chart_type"] == "pie"
    assert result["data_kind"] == "composition"
    assert result["detector"] == "llm"
    assert result["title"] == "AAPL 营收构成"


def test_normalize_unsupported_type_returns_none():
    parsed = {"should_generate": True, "chart_type": "sankey", "confidence": 0.8}
    assert _normalize_llm_result(parsed, "q", "AAPL") is None


def test_normalize_missing_data_kind_falls_back_by_type():
    parsed = {"should_generate": True, "chart_type": "candlestick", "confidence": 0.8}
    result = _normalize_llm_result(parsed, "NVDA 技术指标", "NVDA")
    assert result is not None
    assert result["chart_type"] == "candlestick"
    assert result["data_kind"] == "technical"  # 由 _CHART_TYPE_TO_DATA_KIND 推断


def test_normalize_should_not_generate():
    parsed = {"should_generate": False, "chart_type": None, "reason": "寒暄"}
    result = _normalize_llm_result(parsed, "最近怎么样", "TSLA")
    assert result is not None
    assert result["should_generate"] is False
    assert result["chart_type"] is None
    assert result["data_kind"] == "none"
    assert result["detector"] == "llm"


# ──────────────────────────────────────────────────────────────────────────
# decide_chart：LLM 各类型解析
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "content,expected_type,expected_kind",
    [
        ('{"should_generate": true, "chart_type": "pie", "data_kind": "composition", "confidence": 0.9, "title": "营收构成", "reason": "x"}', "pie", "composition"),
        ('{"should_generate": true, "chart_type": "candlestick", "data_kind": "technical", "confidence": 0.8, "title": "K线", "reason": "x"}', "candlestick", "technical"),
        ('{"should_generate": true, "chart_type": "bar", "data_kind": "comparison", "confidence": 0.7, "title": "对比", "reason": "x"}', "bar", "comparison"),
        ('{"should_generate": true, "chart_type": "radar", "data_kind": "financial", "confidence": 0.7, "title": "风险", "reason": "x"}', "radar", "financial"),
        ('{"should_generate": true, "chart_type": "line", "data_kind": "kline", "confidence": 0.6, "title": "走势", "reason": "x"}', "line", "kline"),
    ],
)
def test_decide_chart_llm_types(monkeypatch, content, expected_type, expected_kind):
    _patch_llm(monkeypatch, content=content)
    result = asyncio.run(decide_chart("某查询", "AAPL"))
    assert result["detector"] == "llm"
    assert result["should_generate"] is True
    assert result["chart_type"] == expected_type
    assert result["data_kind"] == expected_kind


def test_decide_chart_llm_greeting_no_chart(monkeypatch):
    content = '{"should_generate": false, "chart_type": null, "data_kind": "none", "confidence": 0.9, "title": "", "reason": "寒暄"}'
    _patch_llm(monkeypatch, content=content)
    result = asyncio.run(decide_chart("特斯拉最近怎么样", "TSLA"))
    assert result["detector"] == "llm"
    assert result["should_generate"] is False
    assert result["chart_type"] is None


# ──────────────────────────────────────────────────────────────────────────
# decide_chart：回退路径
# ──────────────────────────────────────────────────────────────────────────

def test_decide_chart_llm_timeout_falls_back(monkeypatch):
    _patch_llm(monkeypatch, timeout=True)
    # 关键词命中"走势"+"趋势"（2 个，置信度 0.667 ≥ 0.35）→ 期望回退到 line
    result = asyncio.run(decide_chart("AAPL 走势趋势如何", "AAPL"))
    assert result["detector"] == "keyword_fallback"
    assert result["should_generate"] is True
    assert result["chart_type"] == "line"


def test_decide_chart_llm_exception_falls_back(monkeypatch):
    _patch_llm(monkeypatch, raise_exc=RuntimeError("boom"))
    result = asyncio.run(decide_chart("AAPL K线技术分析", "AAPL"))
    assert result["detector"] == "keyword_fallback"
    assert result["chart_type"] == "candlestick"


def test_decide_chart_invalid_json_falls_back(monkeypatch):
    _patch_llm(monkeypatch, content="完全不是 JSON 的一段话")
    result = asyncio.run(decide_chart("各行业占比分布", "AAPL"))
    assert result["detector"] == "keyword_fallback"
    # "占比/分布" → pie
    assert result["chart_type"] == "pie"
    assert result["data_kind"] == "composition"


def test_decide_chart_unsupported_type_falls_back(monkeypatch):
    content = '{"should_generate": true, "chart_type": "sankey", "confidence": 0.9}'
    _patch_llm(monkeypatch, content=content)
    # 回退到关键词：query 含"对比"+"比较"+"排名"（≥2，置信度 ≥0.35）→ bar
    result = asyncio.run(decide_chart("AAPL 和 MSFT 对比比较排名", "AAPL"))
    assert result["detector"] == "keyword_fallback"
    assert result["chart_type"] == "bar"


def test_decide_chart_empty_query():
    result = asyncio.run(decide_chart("", "AAPL"))
    assert result["should_generate"] is False
    assert result["chart_type"] is None
    assert result["data_kind"] == "none"


def test_decide_chart_fallback_keyword_greeting(monkeypatch):
    """LLM 失败 + 寒暄无关键词 → 关键词回退也不出图。"""
    _patch_llm(monkeypatch, raise_exc=RuntimeError("down"))
    result = asyncio.run(decide_chart("你好呀", None))
    assert result["detector"] == "keyword_fallback"
    assert result["should_generate"] is False
    assert result["chart_type"] is None


# ──────────────────────────────────────────────────────────────────────────
# 一致性：所有 SUPPORTED_CHART_TYPES 都有 data_kind 兜底映射
# ──────────────────────────────────────────────────────────────────────────

def test_all_supported_types_have_data_kind_mapping():
    for chart_type in SUPPORTED_CHART_TYPES:
        assert chart_type in ci._CHART_TYPE_TO_DATA_KIND
        assert ci._CHART_TYPE_TO_DATA_KIND[chart_type] in ci.DATA_KINDS
