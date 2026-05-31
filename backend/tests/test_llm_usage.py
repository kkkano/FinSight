# -*- coding: utf-8 -*-
"""Tests for backend.services.llm_usage — token 提取 / 累加 / 成本估算。"""
from backend.services.llm_usage import (
    TokenUsageAccumulator,
    estimate_cost,
    extract_token_usage,
    record_llm_usage,
    set_token_accumulator,
)


class _NewResp:
    """LangChain 新版 AIMessage.usage_metadata。"""
    usage_metadata = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}


class _OldTokenUsageResp:
    """旧版 response_metadata.token_usage。"""
    response_metadata = {"token_usage": {"prompt_tokens": 200, "completion_tokens": 80}}


class _OldUsageResp:
    """旧版 response_metadata.usage。"""
    response_metadata = {"usage": {"prompt_tokens": 30, "completion_tokens": 20}}


class _EmptyResp:
    pass


# --- extract_token_usage 兼容性 -------------------------------------------


def test_extract_new_usage_metadata():
    assert extract_token_usage(_NewResp()) == (100, 50)


def test_extract_old_token_usage():
    assert extract_token_usage(_OldTokenUsageResp()) == (200, 80)


def test_extract_old_usage():
    assert extract_token_usage(_OldUsageResp()) == (30, 20)


def test_extract_empty_returns_zero():
    assert extract_token_usage(_EmptyResp()) == (0, 0)


# --- accumulator ----------------------------------------------------------


def test_accumulator_summary_aggregates():
    acc = TokenUsageAccumulator()
    acc.add("mimo-v2.5-pro", 100, 50)
    acc.add("mimo-v2.5-pro", 60, 40)
    summary = acc.summary()
    assert summary["total_prompt_tokens"] == 160
    assert summary["total_completion_tokens"] == 90
    assert summary["total_tokens"] == 250
    assert summary["llm_token_calls"] == 2
    assert summary["tokens_by_model"]["mimo-v2.5-pro"]["calls"] == 2


def test_record_llm_usage_with_accumulator():
    acc = TokenUsageAccumulator()
    set_token_accumulator(acc)
    record_llm_usage(_NewResp(), "gpt-4o")
    record_llm_usage(_EmptyResp(), "gpt-4o")  # 0 token 不增加 call
    assert acc.total_tokens == 150
    assert acc.call_count == 1


# --- cost -----------------------------------------------------------------


def test_estimate_cost_known_model():
    # gpt-4o: 1000/1000*0.0025 + 1000/1000*0.01 = 0.0125
    cost = estimate_cost({"gpt-4o": {"prompt": 1000, "completion": 1000}})
    assert abs(cost - 0.0125) < 1e-9


def test_estimate_cost_unknown_model_is_zero():
    assert estimate_cost({"totally-unknown-xyz": {"prompt": 1000, "completion": 1000}}) == 0.0


def test_estimate_cost_prefix_match():
    # mimo-v2.5-pro-xxx 应匹配到 mimo-v2.5-pro（默认 0 单价）
    cost = estimate_cost({"mimo-v2.5-pro-instruct": {"prompt": 1000, "completion": 1000}})
    assert cost == 0.0
