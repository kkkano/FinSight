# -*- coding: utf-8 -*-
"""
Per-run LLM token usage accumulator.

设计：与 ``graph/event_bus.py`` 同构，用 ContextVar 在单次请求（run）内累加每次
LLM 调用的 token。统一在 LLM 调用入口 ``llm_retry.ainvoke_with_rate_limit_retry``
提取 token 并累加 —— 一处覆盖所有 agent/节点的 LLM 调用，零额外 SSE 流量，且不受
trace-raw 事件过滤影响。done 事件构造时读取总量写入 ``metrics``。

Token 提取兼容 LangChain 新旧响应：
  - 新版 AIMessage.usage_metadata: {input_tokens, output_tokens, total_tokens}
  - 旧版 AIMessage.response_metadata.token_usage / usage: {prompt_tokens, completion_tokens}

成本：按模型的 (input, output) 每 1K token 单价（USD）估算。默认单价可通过
环境变量 LLM_PRICING_JSON 覆盖（JSON: {"model": [input_per_1k, output_per_1k]}）。
"""
from __future__ import annotations

import contextvars
import json
import os
from typing import Any

# ---------------------------------------------------------------------------
# Accumulator
# ---------------------------------------------------------------------------


class TokenUsageAccumulator:
    """单次 run 的 token 累加器（线程内顺序累加，无需锁）。"""

    def __init__(self) -> None:
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.call_count: int = 0
        # model -> {"prompt": int, "completion": int, "calls": int}
        self.by_model: dict[str, dict[str, int]] = {}

    def add(self, model: str | None, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.call_count += 1
        key = model or "unknown"
        entry = self.by_model.setdefault(key, {"prompt": 0, "completion": 0, "calls": 0})
        entry["prompt"] += prompt
        entry["completion"] += completion
        entry["calls"] += 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def summary(self) -> dict[str, Any]:
        cost = estimate_cost(self.by_model)
        return {
            "total_prompt_tokens": self.prompt_tokens,
            "total_completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "llm_token_calls": self.call_count,
            "total_cost_usd": round(cost, 6) if cost else 0.0,
            "tokens_by_model": self.by_model,
        }


_ACC: contextvars.ContextVar[TokenUsageAccumulator | None] = contextvars.ContextVar(
    "_LLM_TOKEN_ACC", default=None
)


def set_token_accumulator(acc: TokenUsageAccumulator) -> contextvars.Token:
    return _ACC.set(acc)


def reset_token_accumulator(token: contextvars.Token) -> None:
    try:
        _ACC.reset(token)
    except Exception:
        return


def get_token_accumulator() -> TokenUsageAccumulator | None:
    return _ACC.get()


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def extract_token_usage(response: Any) -> tuple[int, int]:
    """从 LangChain 响应提取 (prompt_tokens, completion_tokens)，兼容新旧字段。"""
    # 新版 usage_metadata
    um = getattr(response, "usage_metadata", None)
    if isinstance(um, dict):
        prompt = _safe_int(um.get("input_tokens") or um.get("prompt_tokens") or 0)
        completion = _safe_int(um.get("output_tokens") or um.get("completion_tokens") or 0)
        if prompt or completion:
            return prompt, completion
    # 旧版 response_metadata.token_usage / usage
    rm = getattr(response, "response_metadata", None)
    if isinstance(rm, dict):
        tu = rm.get("token_usage") or rm.get("usage") or {}
        if isinstance(tu, dict):
            prompt = _safe_int(tu.get("prompt_tokens") or tu.get("input_tokens") or 0)
            completion = _safe_int(tu.get("completion_tokens") or tu.get("output_tokens") or 0)
            return prompt, completion
    return 0, 0


def record_llm_usage(response: Any, model: str | None = None) -> None:
    """统一入口调用：提取 token 并累加到当前 run 的 accumulator（无 accumulator 时静默）。"""
    acc = get_token_accumulator()
    if acc is None:
        return
    try:
        prompt, completion = extract_token_usage(response)
        if prompt or completion:
            acc.add(model, prompt, completion)
    except Exception:
        return


# ---------------------------------------------------------------------------
# Pricing (USD per 1K tokens: input, output)
# ---------------------------------------------------------------------------

_DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    # 主人按实际单价调整（或用 LLM_PRICING_JSON 环境变量覆盖）。
    # mimo 默认置 0（成本未知时前端不展示成本，仅展示 token）。
    "mimo-v2.5-pro": (0.0, 0.0),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4.1": (0.002, 0.008),
    "gpt-4.1-mini": (0.0004, 0.0016),
    "claude-3-5-sonnet": (0.003, 0.015),
    "gemini-2.0-flash": (0.0001, 0.0004),
}


def _load_pricing() -> dict[str, tuple[float, float]]:
    pricing = dict(_DEFAULT_PRICING)
    raw = os.getenv("LLM_PRICING_JSON", "").strip()
    if raw:
        try:
            override = json.loads(raw)
            for model, rates in override.items():
                if isinstance(rates, (list, tuple)) and len(rates) == 2:
                    pricing[str(model)] = (float(rates[0]), float(rates[1]))
        except Exception:
            pass
    return pricing


def _match_pricing(model: str, pricing: dict[str, tuple[float, float]]) -> tuple[float, float] | None:
    if model in pricing:
        return pricing[model]
    # 前缀/包含匹配（如 mimo-v2.5-pro-xxx → mimo-v2.5-pro）
    low = model.lower()
    for key, rates in pricing.items():
        if key.lower() in low or low in key.lower():
            return rates
    return None


def estimate_cost(by_model: dict[str, dict[str, int]]) -> float:
    """按模型累计成本（USD）。无匹配单价的模型按 0 计。"""
    pricing = _load_pricing()
    total = 0.0
    for model, usage in by_model.items():
        rates = _match_pricing(model, pricing)
        if not rates:
            continue
        input_rate, output_rate = rates
        total += (usage.get("prompt", 0) / 1000.0) * input_rate
        total += (usage.get("completion", 0) / 1000.0) * output_rate
    return total
