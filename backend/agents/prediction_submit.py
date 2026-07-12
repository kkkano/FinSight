# -*- coding: utf-8 -*-
"""prediction 的服务端校验、真实行情锚定与确定性逐 bar 判定。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

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
_NON_CONCRETE_SYMBOLS = frozenset({"", "UNKNOWN", "N/A", "NONE", "MARKET", "MACRO"})


def submission_allowed(*, symbol: str, operation: str) -> bool:
    normalized = str(symbol or "").strip().upper()
    return normalized not in _NON_CONCRETE_SYMBOLS and str(operation or "").strip() in SCORABLE_OPERATIONS


def _bar_number(bar: Mapping[str, Any], key: str) -> float:
    value = float(bar[key])
    if value <= 0:
        raise ValueError(f"行情 bar 的 {key} 必须为正数")
    return value


def _normalized_bars(raw: Any) -> tuple[list[dict[str, Any]], str]:
    payload = raw if isinstance(raw, Mapping) else {}
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
) -> AgentPrediction:
    """校验模型白名单后，用服务端上下文和最后一根真实 bar 覆盖可信字段。"""
    if not submission_allowed(symbol=symbol, operation=operation):
        raise ValueError("当前步骤不允许提交可计分 prediction")
    normalized_user = str(user_id or "").strip()
    if not normalized_user or normalized_user == "public":
        raise ValueError("prediction 需要已鉴权用户")
    normalized_run = str(run_id or "").strip()
    if not normalized_run:
        raise ValueError("prediction 需要服务端 run_id")

    draft = PredictionDraft.model_validate(raw_prediction)
    normalized_symbol = normalize_ticker(symbol)
    raw_bars = fetch_bars(normalized_symbol, period="1mo", interval="1d")
    bars, timeframe = _normalized_bars(raw_bars)
    anchor_bar = bars[-1]
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
        "created_at": now,
        "updated_at": now,
    })
    return store.create(prediction)


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
    "SCORABLE_OPERATIONS", "evaluate_prediction_bars", "submission_allowed", "submit_prediction",
    "submit_prediction_with_correction",
]
