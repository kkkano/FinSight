# -*- coding: utf-8 -*-
"""
Per-run LLM token usage accumulator.

设计：与 ``graph/event_bus.py`` 同构，用 ContextVar 在单次请求（run）内累加每次
LLM 调用的 token。统一在 LLM 调用入口 ``llm_retry.ainvoke_llm``
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
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Accumulator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMAttribution:
    agent: str
    layer: str
    prediction_id: str | None = None


class TokenUsageAccumulator:
    """单次 run 的 token 累加器（线程内顺序累加，无需锁）。"""

    def __init__(self, *, user_id: str = "public") -> None:
        self.user_id = str(user_id or "public").strip() or "public"
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.call_count: int = 0
        self.failed_call_count: int = 0
        self.reported_usage_calls: int = 0
        self.unreported_usage_calls: int = 0
        self.selection_failed_call_count: int = 0
        # model -> {"prompt": int, "completion": int, "calls": int}
        self.by_model: dict[str, dict[str, int]] = {}
        self.by_attribution: dict[tuple[str, str, str | None, str], dict[str, Any]] = {}

    def add(self, model: str | None, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.call_count += 1
        key = model or "unknown"
        entry = self.by_model.setdefault(key, {"prompt": 0, "completion": 0, "calls": 0})
        entry["prompt"] += prompt
        entry["completion"] += completion
        entry["calls"] += 1

    def add_attributed_attempt(
        self,
        *,
        model: str | None,
        status: str,
        duration_ms: int,
        prompt: int = 0,
        completion: int = 0,
        attribution: LLMAttribution | None = None,
        usage_reported: bool | None = None,
    ) -> None:
        key_model = model or "unknown"
        identity = attribution or LLMAttribution(agent="unattributed", layer="unknown")
        key = (identity.agent, identity.layer, identity.prediction_id, key_model)
        entry = self.by_attribution.setdefault(key, {
            "agent": identity.agent,
            "layer": identity.layer,
            "prediction_id": identity.prediction_id,
            "model": key_model,
            "prompt": 0,
            "completion": 0,
            "calls": 0,
            "failed_calls": 0,
            "duration_ms": 0,
        })
        entry["prompt"] += max(0, int(prompt))
        entry["completion"] += max(0, int(completion))
        entry["calls"] += 1
        entry["failed_calls"] += int(status != "success")
        entry["duration_ms"] += max(0, int(duration_ms))
        self.failed_call_count += int(status != "success")
        if status == "success":
            if usage_reported:
                self.reported_usage_calls += 1
            else:
                self.unreported_usage_calls += 1

    def bind_prediction(self, *, agent: str, prediction_id: str) -> None:
        """提交成功后，把本 Agent 本 run 尚未关联的调用层绑定到该 prediction。"""
        normalized_id = str(prediction_id or "").strip()
        if not normalized_id:
            return
        for key in list(self.by_attribution):
            key_agent, layer, current_prediction_id, model = key
            if key_agent != agent or current_prediction_id is not None:
                continue
            source = self.by_attribution.pop(key)
            target_key = (key_agent, layer, normalized_id, model)
            target = self.by_attribution.get(target_key)
            source["prediction_id"] = normalized_id
            if target is None:
                self.by_attribution[target_key] = source
                continue
            for field in ("prompt", "completion", "calls", "failed_calls", "duration_ms"):
                target[field] += source[field]

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def summary(self) -> dict[str, Any]:
        cost = estimate_cost(self.by_model)
        if self.reported_usage_calls == 0:
            usage_state = "not_reported"
        elif self.unreported_usage_calls == 0 and self.failed_call_count == 0:
            usage_state = "reported"
        else:
            usage_state = "partial"
        return {
            "total_prompt_tokens": self.prompt_tokens,
            "total_completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "llm_token_calls": self.call_count,
            "failed_llm_calls": self.failed_call_count,
            "selection_failed_llm_calls": self.selection_failed_call_count,
            "reported_usage_calls": self.reported_usage_calls,
            "unreported_usage_calls": self.unreported_usage_calls,
            "usage_state": usage_state,
            "total_cost_usd": round(cost, 6) if cost else 0.0,
            "tokens_by_model": self.by_model,
            "usage_by_attribution": list(self.by_attribution.values()),
        }


_ACC: contextvars.ContextVar[TokenUsageAccumulator | None] = contextvars.ContextVar(
    "_LLM_TOKEN_ACC", default=None
)
_ATTRIBUTION: contextvars.ContextVar[LLMAttribution | None] = contextvars.ContextVar(
    "_LLM_ATTRIBUTION", default=None
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


def set_llm_attribution(attribution: LLMAttribution) -> contextvars.Token:
    return _ATTRIBUTION.set(attribution)


def reset_llm_attribution(token: contextvars.Token) -> None:
    try:
        _ATTRIBUTION.reset(token)
    except Exception:
        return


def get_llm_attribution() -> LLMAttribution | None:
    return _ATTRIBUTION.get()


def bind_current_llm_usage_prediction(*, agent: str, prediction_id: str) -> None:
    acc = get_token_accumulator()
    if acc is not None:
        acc.bind_prediction(agent=agent, prediction_id=prediction_id)


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


def has_reported_token_usage(response: Any) -> bool:
    """Return true when the provider explicitly supplied usage, including 0/0."""
    usage_metadata = getattr(response, "usage_metadata", None)
    if isinstance(usage_metadata, dict) and any(
        key in usage_metadata for key in ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens")
    ):
        return True
    response_metadata = getattr(response, "response_metadata", None)
    if not isinstance(response_metadata, dict):
        return False
    usage = response_metadata.get("token_usage") or response_metadata.get("usage")
    return isinstance(usage, dict) and any(
        key in usage for key in ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens")
    )


def record_llm_usage(response: Any, model: str | None = None, *, count_call: bool = True) -> None:
    """统一入口调用：提取 token 并累加到当前 run 的 accumulator（无 accumulator 时静默）。"""
    acc = get_token_accumulator()
    if acc is None:
        return
    try:
        prompt, completion = extract_token_usage(response)
        if prompt or completion:
            acc.add(model, prompt, completion)
            if not count_call:
                acc.call_count -= 1
                acc.by_model[model or "unknown"]["calls"] -= 1
    except Exception:
        return


def record_llm_attempt(
    *,
    model: str | None,
    status: str,
    duration_ms: int,
    response: Any | None = None,
) -> None:
    """记录一次真正发往模型的调用；限流令牌等待不属于模型调用。"""
    acc = get_token_accumulator()
    if acc is None:
        return
    prompt, completion = extract_token_usage(response) if response is not None else (0, 0)
    acc.call_count += 1
    model_entry = acc.by_model.setdefault(model or "unknown", {"prompt": 0, "completion": 0, "calls": 0})
    model_entry["calls"] += 1
    acc.add_attributed_attempt(
        model=model,
        status=status,
        duration_ms=duration_ms,
        prompt=prompt,
        completion=completion,
        attribution=get_llm_attribution(),
        usage_reported=has_reported_token_usage(response) if status == "success" and response is not None else False,
    )


def record_llm_selection_failure() -> None:
    acc = get_token_accumulator()
    if acc is not None:
        acc.selection_failed_call_count += 1


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


# ---------------------------------------------------------------------------
# P1-5: 单请求 token 预算上限
# ---------------------------------------------------------------------------

_DEFAULT_REQUEST_TOKEN_BUDGET = 300_000


class TokenBudgetExceededError(RuntimeError):
    """P1-5: 单请求 token 预算超限，后续 LLM 调用被拒绝。"""

    def __init__(self, used: int, budget: int):
        self.used = used
        self.budget = budget
        super().__init__(
            f"Request token budget exceeded: used={used}, budget={budget}. "
            "请缩小请求范围或联系管理员调高 LLM_REQUEST_TOKEN_BUDGET。"
        )


def _request_token_budget() -> int:
    """单请求 token 预算（环境变量 LLM_REQUEST_TOKEN_BUDGET，0 = 不限制）。"""
    try:
        return int(os.getenv("LLM_REQUEST_TOKEN_BUDGET", str(_DEFAULT_REQUEST_TOKEN_BUDGET)))
    except (TypeError, ValueError):
        return _DEFAULT_REQUEST_TOKEN_BUDGET


def check_token_budget() -> None:
    """在每次 LLM 调用前检查当前请求是否已超 token 预算。

    无 accumulator（非请求上下文，如启动脚本/测试）或预算为 0 时不检查。
    超限抛 TokenBudgetExceededError，由调用方（执行管线）转换为用户可见错误。
    """
    acc = get_token_accumulator()
    if acc is None:
        return
    budget = _request_token_budget()
    if budget <= 0:
        return
    if acc.total_tokens >= budget:
        raise TokenBudgetExceededError(acc.total_tokens, budget)
