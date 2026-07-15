# -*- coding: utf-8 -*-
"""实时监控的确定性触发函数；不做 I/O、不调用 LLM、不写库。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from backend.agents.prediction_contract import AgentPrediction


@dataclass(frozen=True)
class MonitorTrigger:
    kind: str
    detail: str
    observed_at: str
    severity: str
    escalates_prediction: bool = False


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    observed_at: str
    price: float | None
    volume: float | None = None
    average_volume20: float | None = None
    macd_hist: float | None = None
    flow_value: float | None = None
    flow_peak_abs: float | None = None
    previous_day_high: float | None = None
    previous_day_low: float | None = None
    levels: Mapping[str, float] = field(default_factory=dict)
    zones: Mapping[str, tuple[float, float]] = field(default_factory=dict)


def heartbeat_due(
    *,
    last_comment_at: datetime | None,
    now: datetime,
    interval_seconds: int = 300,
) -> bool:
    if last_comment_at is None:
        return True
    return (now - last_comment_at).total_seconds() >= max(1, int(interval_seconds))


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _cross_direction(before: float, after: float, level: float) -> str | None:
    if before < level <= after:
        return "上穿"
    if before > level >= after:
        return "下穿"
    return None


def _level_detail(name: str, direction: str, before: float, after: float, level: float) -> str:
    return f"{name} {direction}：{before:.4f} → {after:.4f}，命中价位 {level:.4f}"


def _prediction_levels(prediction: AgentPrediction | None) -> list[tuple[str, float]]:
    if prediction is None or prediction.direction == "neutral":
        return []
    result: list[tuple[str, float]] = []
    for name in ("entry", "stop", "target1", "target2", "invalidation_price"):
        value = _finite_number(getattr(prediction, name, None))
        if value is not None:
            result.append((name, value))
    return result


def _named_levels(snapshot: MarketSnapshot) -> list[tuple[str, float]]:
    result: list[tuple[str, float]] = []
    for name in sorted(snapshot.levels):
        value = _finite_number(snapshot.levels[name])
        if value is not None:
            result.append((str(name), value))
    return result


def _named_zones(
    previous: MarketSnapshot,
    current: MarketSnapshot,
    prediction: AgentPrediction | None,
) -> list[tuple[str, float, float, bool]]:
    zones: dict[str, tuple[float, float, bool]] = {}
    for source in (previous.zones, current.zones):
        for name, raw_range in source.items():
            if not isinstance(raw_range, (tuple, list)) or len(raw_range) != 2:
                continue
            low, high = _finite_number(raw_range[0]), _finite_number(raw_range[1])
            if low is not None and high is not None and low < high:
                zones[str(name)] = (low, high, False)
    if prediction is not None and prediction.direction == "neutral":
        low, high = _finite_number(prediction.range_low), _finite_number(prediction.range_high)
        if low is not None and high is not None and low < high:
            zones["prediction_range"] = (low, high, True)
    return [(name, *zones[name]) for name in sorted(zones)]


def detect_triggers(
    *,
    previous: MarketSnapshot,
    current: MarketSnapshot,
    prediction: AgentPrediction | None,
) -> list[MonitorTrigger]:
    previous_symbol = str(previous.symbol or "").strip().upper()
    current_symbol = str(current.symbol or "").strip().upper()
    prediction_symbol = str(prediction.symbol or "").strip().upper() if prediction is not None else current_symbol
    if not previous_symbol or previous_symbol != current_symbol or prediction_symbol != current_symbol:
        return [MonitorTrigger(
            kind="data_gap",
            detail=(
                "行情标的不一致："
                f"previous={previous_symbol or 'missing'}, current={current_symbol or 'missing'}, "
                f"prediction={prediction_symbol or 'missing'}"
            ),
            observed_at=current.observed_at,
            severity="warn",
        )]
    before, after = _finite_number(previous.price), _finite_number(current.price)
    if before is None or after is None:
        missing = []
        if before is None:
            missing.append("previous.price")
        if after is None:
            missing.append("current.price")
        return [MonitorTrigger(
            kind="data_gap",
            detail=f"行情字段缺失：{', '.join(missing)}",
            observed_at=current.observed_at,
            severity="warn",
        )]

    triggers: list[MonitorTrigger] = []
    observed_at = current.observed_at

    for name, level in _prediction_levels(prediction):
        direction = _cross_direction(before, after, level)
        if direction:
            triggers.append(MonitorTrigger(
                kind="prediction_level_break",
                detail=_level_detail(name, direction, before, after, level),
                observed_at=observed_at,
                severity="alert",
                escalates_prediction=True,
            ))

    for name, level in _named_levels(current):
        direction = _cross_direction(before, after, level)
        if direction:
            triggers.append(MonitorTrigger(
                kind="level_break",
                detail=_level_detail(name, direction, before, after, level),
                observed_at=observed_at,
                severity="alert",
            ))

    for name, level in (
        ("previous_day_high", _finite_number(current.previous_day_high)),
        ("previous_day_low", _finite_number(current.previous_day_low)),
    ):
        if level is None:
            continue
        direction = _cross_direction(before, after, level)
        if direction:
            triggers.append(MonitorTrigger(
                kind="day_level_break",
                detail=_level_detail(name, direction, before, after, level),
                observed_at=observed_at,
                severity="alert",
            ))

    for name, low, high, prediction_related in _named_zones(previous, current, prediction):
        was_inside = low <= before <= high
        is_inside = low <= after <= high
        if was_inside == is_inside:
            continue
        action = "进入" if is_inside else "离开"
        triggers.append(MonitorTrigger(
            kind="prediction_range_break" if prediction_related else "zone_break",
            detail=(
                f"{action} {name}：{before:.4f} → {after:.4f}，"
                f"区间 [{low:.4f}, {high:.4f}]"
            ),
            observed_at=observed_at,
            severity="warn",
            escalates_prediction=prediction_related,
        ))

    previous_macd = _finite_number(previous.macd_hist)
    current_macd = _finite_number(current.macd_hist)
    if previous_macd is not None and current_macd is not None:
        direction = _cross_direction(previous_macd, current_macd, 0.0)
        if direction:
            triggers.append(MonitorTrigger(
                kind="macd_cross",
                detail=f"MACD 柱 {direction}零轴：{previous_macd:.6f} → {current_macd:.6f}",
                observed_at=observed_at,
                severity="warn",
            ))

    previous_flow = _finite_number(previous.flow_value)
    current_flow = _finite_number(current.flow_value)
    if previous_flow is not None and current_flow is not None:
        direction = _cross_direction(previous_flow, current_flow, 0.0)
        peak = max(
            abs(previous_flow),
            abs(current_flow),
            abs(_finite_number(previous.flow_peak_abs) or 0.0),
            abs(_finite_number(current.flow_peak_abs) or 0.0),
        )
        jitter = peak > 0 and abs(current_flow) < peak * 0.05
        if direction and not jitter:
            triggers.append(MonitorTrigger(
                kind="flow_flip",
                detail=(
                    f"资金流 {direction}零轴：{previous_flow:.4f} → {current_flow:.4f}，"
                    f"峰值绝对值 {peak:.4f}"
                ),
                observed_at=observed_at,
                severity="warn",
            ))

    volume = _finite_number(current.volume)
    average_volume = _finite_number(current.average_volume20)
    if volume is not None and average_volume is not None and average_volume > 0:
        ratio = volume / average_volume
        if ratio > 3.0:
            triggers.append(MonitorTrigger(
                kind="volume_spike",
                detail=(
                    f"量能放大：{volume:.4f} / 前20根均量 {average_volume:.4f} = {ratio:.4f}x"
                ),
                observed_at=observed_at,
                severity="warn",
            ))

    return triggers


__all__ = ["MarketSnapshot", "MonitorTrigger", "detect_triggers", "heartbeat_due"]
