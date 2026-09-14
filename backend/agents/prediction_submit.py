# -*- coding: utf-8 -*-
"""prediction 的服务端校验、真实行情锚定与确定性逐 bar 判定。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

from pydantic import ValidationError

from backend.agents.prediction_contract import (
    AgentPrediction,
    PredictionAnchor,
    PredictionDraft,
    PredictionEvaluation,
)
from backend.config.ticker_mapping import normalize_ticker


SCORABLE_OPERATIONS = frozenset({
    "investment_opinion", "technical", "earnings_impact", "report_generation",
})
SCORABLE_AGENTS = frozenset({
    "price_agent", "fundamental_agent", "technical_agent", "risk_agent",
    "prediction_analyst",
})
_NON_CONCRETE_SYMBOLS = frozenset({"", "UNKNOWN", "N/A", "NONE", "MARKET", "MACRO"})


def submission_allowed(*, symbol: str, operation: str, agent: str | None = None) -> bool:
    normalized = str(symbol or "").strip().upper()
    agent_allowed = agent is None or str(agent or "").strip() in SCORABLE_AGENTS
    return (
        normalized not in _NON_CONCRETE_SYMBOLS
        and str(operation or "").strip() in SCORABLE_OPERATIONS
        and agent_allowed
    )


def _bar_number(bar: Mapping[str, Any], key: str) -> float:
    value = float(bar[key])
    if value <= 0:
        raise ValueError(f"行情 bar 的 {key} 必须为正数")
    return value


def _normalized_bars(raw: Any) -> tuple[list[dict[str, Any]], str]:
    payload = raw if isinstance(raw, Mapping) else {}
    if payload.get("quality") != "trusted" or payload.get("error_code"):
        raise ValueError("无法取得真实行情锚点：可信行情不可用，prediction 未落库")
    if not str(payload.get("provider") or "").strip() or not str(payload.get("as_of") or "").strip():
        raise ValueError("可信行情缺少 provider/as_of，prediction 未落库")
    bars = payload.get("kline_data")
    if not isinstance(bars, list) or not bars:
        raise ValueError("无法取得真实行情锚点，prediction 未落库")
    normalized: list[dict[str, Any]] = []
    for item in bars:
        if not isinstance(item, Mapping) or not str(item.get("time") or "").strip():
            continue
        try:
            normalized.append({
                "time": str(item["time"]),
                "open": _bar_number(item, "open"),
                "high": _bar_number(item, "high"),
                "low": _bar_number(item, "low"),
                "close": _bar_number(item, "close"),
            })
        except (KeyError, TypeError, ValueError):
            continue
    if not normalized:
        raise ValueError("无法取得真实行情锚点，prediction 未落库")
    return normalized, str(payload.get("interval") or "1d")


def submit_prediction(
    raw_prediction: Mapping[str, Any],
    *,
    symbol: str,
    agent: str,
    user_id: str,
    run_id: str,
    operation: str,
    fetch_bars: Callable[..., Any],
    store: Any,
    prompt_version: str = "legacy",
) -> AgentPrediction:
    """校验模型白名单后，用服务端上下文和最后一根真实 bar 覆盖可信字段。"""
    raw_bars = fetch_bars(normalize_ticker(symbol), period="1mo", interval="1d")
    prediction = build_prediction(
        raw_prediction,
        symbol=symbol,
        agent=agent,
        user_id=user_id,
        run_id=run_id,
        operation=operation,
        raw_bars=raw_bars,
        prompt_version=prompt_version,
    )
    return store.create(prediction)


def build_prediction(
    raw_prediction: Mapping[str, Any],
    *,
    symbol: str,
    agent: str,
    user_id: str,
    run_id: str,
    operation: str,
    raw_bars: Mapping[str, Any],
    prompt_version: str,
) -> AgentPrediction:
    """构建经过服务端锚定的 Prediction；持久化由调用方决定事务边界。"""
    if not submission_allowed(symbol=symbol, operation=operation, agent=agent):
        raise ValueError("当前步骤不允许提交可计分 prediction")
    normalized_user = str(user_id or "").strip()
    if not normalized_user or normalized_user == "public":
        raise ValueError("prediction 需要已鉴权用户")
    normalized_run = str(run_id or "").strip()
    if not normalized_run:
        raise ValueError("prediction 需要服务端 run_id")

    draft = PredictionDraft.model_validate(raw_prediction)
    normalized_symbol = normalize_ticker(symbol)
    bars, timeframe = _normalized_bars(raw_bars)
    anchor_bar = bars[-1]
    submitted_anchor_time = str(draft.anchor.time or "").strip()
    trusted_anchor_time = str(anchor_bar["time"])
    if submitted_anchor_time != trusted_anchor_time:
        raise ValueError(
            f"anchor.time 与最新完整 bar 不一致: current={submitted_anchor_time}, expected={trusted_anchor_time}"
        )
    submitted_price = float(draft.anchor.price)
    trusted_price = float(anchor_bar["close"])
    deviation = abs(submitted_price - trusted_price) / trusted_price
    if deviation > 0.005:
        raise ValueError(
            f"anchor.price 偏离最新完整 bar close 超过 0.5%: current={submitted_price}, expected={trusted_price}"
        )
    trusted_payload = draft.model_dump(exclude={"risk_reward"}) | {
        "symbol": normalized_symbol,
        "agent": str(agent or "").strip(),
        "anchor": PredictionAnchor(
            timeframe=timeframe,
            time=anchor_bar["time"],
            price=anchor_bar["close"],
        ).model_dump(),
    }
    # 覆盖真实 anchor 后重新校验，neutral range 不包含真实价格时必须拒绝。
    trusted_draft = PredictionDraft.model_validate(trusted_payload)
    now = datetime.now(timezone.utc)
    prediction = AgentPrediction.model_validate(trusted_draft.model_dump(exclude={"risk_reward"}) | {
        "id": str(uuid4()),
        "user_id": normalized_user,
        "run_id": normalized_run,
        "status": "waiting",
        "prompt_version": str(prompt_version or "").strip() or "legacy",
        "evidence_provider": str(raw_bars.get("provider") or "").strip() or None,
        "evidence_as_of": str(raw_bars.get("as_of") or "").strip() or None,
        "source_type": "ai",
        "created_at": now,
        "updated_at": now,
    })
    return prediction


def submit_prediction_with_correction(
    generate_prediction: Callable[[str | None], Mapping[str, Any] | None],
    **submit_kwargs: Any,
) -> AgentPrediction | None:
    """只给模型一次基于校验错误的纠正机会；第二次非法时保持零落库。"""
    feedback: str | None = None
    for _attempt in range(2):
        raw = generate_prediction(feedback)
        if raw is None:
            return None
        try:
            return submit_prediction(raw, **submit_kwargs)
        except ValueError as exc:
            feedback = str(exc)[:500]
    return None


def _submission_issues(exc: Exception) -> list[dict[str, Any]]:
    if isinstance(exc, ValidationError):
        issues: list[dict[str, Any]] = []
        for item in exc.errors(include_url=False)[:12]:
            field = ".".join(str(part) for part in item.get("loc") or ()) or "prediction"
            current = item.get("input")
            if any(token in field.lower() for token in ("user_id", "run_id", "token", "secret", "key")):
                current = "[redacted]"
            elif isinstance(current, str):
                current = current[:80]
            elif not isinstance(current, (int, float, bool, type(None))):
                current = None
            issues.append({
                "field": field,
                "rule": str(item.get("type") or "validation_error"),
                "current": current,
                "expected": str(item.get("msg") or "字段必须满足 prediction 合同")[:240],
            })
        return issues
    message = str(exc or "prediction validation failed")[:300]
    field = "anchor" if message.startswith("anchor.") or "行情" in message else "prediction"
    return [{
        "field": field,
        "rule": "domain_validation",
        "current": None,
        "expected": message,
    }]


def validate_prediction_submission(raw_prediction: Mapping[str, Any], **submit_kwargs: Any) -> dict[str, Any]:
    try:
        prediction = submit_prediction(raw_prediction, **submit_kwargs)
    except (ValidationError, ValueError) as exc:
        return {"ok": False, "issues": _submission_issues(exc)}
    return {"ok": True, "issues": [], "prediction": prediction}


async def submit_prediction_with_async_correction(
    generate_prediction: Callable[[list[dict[str, Any]] | None], Any],
    **submit_kwargs: Any,
) -> tuple[AgentPrediction | None, list[dict[str, Any]]]:
    """最多两次结构化提交；仅成功值落库，失败不会阻断 Agent 主摘要。"""
    feedback: list[dict[str, Any]] | None = None
    trace: list[dict[str, Any]] = []
    for attempt in range(1, 3):
        raw = generate_prediction(feedback)
        if hasattr(raw, "__await__"):
            raw = await raw
        if not isinstance(raw, Mapping):
            issues = [{
                "field": "prediction",
                "rule": "missing_submission",
                "current": None,
                "expected": "返回一个 JSON prediction 对象",
            }]
            trace.append({"attempt": attempt, "ok": False, "issues": issues})
            feedback = issues
            continue
        result = await asyncio.to_thread(validate_prediction_submission, raw, **submit_kwargs)
        issues = result.get("issues") if isinstance(result.get("issues"), list) else []
        trace.append({"attempt": attempt, "ok": bool(result.get("ok")), "issues": issues})
        if result.get("ok") and isinstance(result.get("prediction"), AgentPrediction):
            return result["prediction"], trace
        feedback = issues
    return None, trace


def prediction_json_from_llm_content(content: Any) -> dict[str, Any] | None:
    raw = content.content if hasattr(content, "content") else content
    if isinstance(raw, list):
        raw = "".join(
            str(item.get("text") or "") if isinstance(item, dict) else str(item)
            for item in raw
        )
    text_value = str(raw or "").strip()
    if text_value.startswith("```"):
        lines = text_value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text_value = "\n".join(lines).strip()
    try:
        parsed = json.loads(text_value)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _crossed_entry(draft: PredictionDraft, bar: Mapping[str, Any]) -> tuple[bool, float | None]:
    assert draft.entry is not None
    opened = _bar_number(bar, "open")
    high = _bar_number(bar, "high")
    low = _bar_number(bar, "low")
    if draft.entry_type == "market":
        return True, opened
    if draft.entry_type == "limit":
        if low <= draft.entry <= high:
            # 跳空穿过限价时按首个可交易 open 保守成交。
            if draft.direction == "long" and opened < draft.entry:
                return True, opened
            if draft.direction == "short" and opened > draft.entry:
                return True, opened
            return True, draft.entry
        return False, None
    if draft.direction == "long" and high >= draft.entry:
        return True, max(opened, draft.entry) if opened >= draft.entry else draft.entry
    if draft.direction == "short" and low <= draft.entry:
        return True, min(opened, draft.entry) if opened <= draft.entry else draft.entry
    return False, None


def evaluate_prediction_bars(
    raw_prediction: PredictionDraft | Mapping[str, Any],
    bars: Iterable[Mapping[str, Any]],
) -> PredictionEvaluation:
    """从 anchor 后逐 bar 判定；同 bar 止损与止盈并存时固定判 hit_stop。"""
    draft = raw_prediction if isinstance(raw_prediction, PredictionDraft) else PredictionDraft.model_validate(raw_prediction)
    ordered = list(bars)
    future = [bar for bar in ordered if str(bar.get("time") or "") > draft.anchor.time]
    if draft.direction == "neutral":
        status = "waiting"
        resolved_time = None
        assert draft.range_low is not None and draft.range_high is not None
        for bar in future:
            if _bar_number(bar, "low") < draft.range_low or _bar_number(bar, "high") > draft.range_high:
                status, resolved_time = "broke_range", str(bar.get("time"))
                break
            status = "held_range"
        return PredictionEvaluation(status=status, resolved_time=resolved_time)

    entered = False
    entry_time: str | None = None
    entry_price: float | None = None
    assert draft.invalidation_price is not None and draft.stop is not None and draft.target1 is not None
    for bar in future:
        time_value = str(bar.get("time") or "")
        high, low = _bar_number(bar, "high"), _bar_number(bar, "low")
        if not entered:
            invalidated = low <= draft.invalidation_price if draft.direction == "long" else high >= draft.invalidation_price
            touched, fill = _crossed_entry(draft, bar)
            # 同一 bar 既出现入场又越过入场前失效位，按更保守的 invalidated。
            if invalidated and not touched:
                return PredictionEvaluation(status="invalidated", resolved_time=time_value)
            if not touched:
                continue
            entered, entry_time, entry_price = True, time_value, fill

        hit_stop = low <= draft.stop if draft.direction == "long" else high >= draft.stop
        hit_target = high >= draft.target1 if draft.direction == "long" else low <= draft.target1
        if hit_stop:
            return PredictionEvaluation(
                status="hit_stop", entry_time=entry_time, entry_price=entry_price, resolved_time=time_value,
            )
        if hit_target:
            return PredictionEvaluation(
                status="hit_target", entry_time=entry_time, entry_price=entry_price, resolved_time=time_value,
            )

    return PredictionEvaluation(
        status="open" if entered else "waiting",
        entry_time=entry_time,
        entry_price=entry_price,
    )


__all__ = [
    "SCORABLE_AGENTS", "SCORABLE_OPERATIONS", "build_prediction", "evaluate_prediction_bars", "prediction_json_from_llm_content",
    "submission_allowed", "submit_prediction", "submit_prediction_with_async_correction",
    "submit_prediction_with_correction", "validate_prediction_submission",
]
