# -*- coding: utf-8 -*-
"""AI prediction 的最小可信合同。

行情序列属于真实行情数据面，本合同只允许模型提交价位判断与文字 thesis。
租户、运行、Agent 和最终行情锚点均由服务端生成，不属于模型输入。
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


Direction = Literal["long", "short", "neutral"]
EntryType = Literal["market", "limit", "stop"]
PredictionStatus = Literal[
    "waiting", "open", "triggered", "invalidated", "hit_target", "hit_stop",
    "held_range", "broke_range",
]


class PredictionAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeframe: str = Field(min_length=1, max_length=16)
    time: str = Field(min_length=1, max_length=64)
    price: float = Field(gt=0, allow_inf_nan=False)


class PredictionScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    probability: int = Field(ge=0, le=100)
    invalidation: str = Field(min_length=1, max_length=200)


class PredictionDraft(BaseModel):
    """模型可提交字段的白名单；任何行情数组或服务端身份字段都会被拒绝。"""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=32)
    agent: str = Field(min_length=1, max_length=64)
    direction: Direction
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    thesis: str = Field(min_length=1, max_length=400)
    anchor: PredictionAnchor
    entry_type: EntryType | None = None
    entry: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    stop: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    target1: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    target2: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    invalidation_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    range_low: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    range_high: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    scenarios: list[PredictionScenario] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def validate_direction_fields(self) -> "PredictionDraft":
        probability_total = sum(item.probability for item in self.scenarios)
        if not 90 <= probability_total <= 110:
            raise ValueError("prediction scenarios 概率和必须在 90-110 之间")
        directional_values = (self.entry, self.stop, self.target1, self.invalidation_price)
        if self.direction == "neutral":
            if any(value is not None for value in (*directional_values, self.target2, self.entry_type)):
                raise ValueError("neutral prediction 只能提交 range，不得提交方向性价位")
            if self.range_low is None or self.range_high is None:
                raise ValueError("neutral prediction 必须提交 range_low/range_high")
            if not self.range_low < self.range_high:
                raise ValueError("neutral range 必须满足 low < high")
            if not self.range_low <= self.anchor.price <= self.range_high:
                raise ValueError("neutral range 必须包含真实 anchor price")
            return self

        if self.entry_type is None or any(value is None for value in directional_values):
            raise ValueError("long/short prediction 必须提交 entry_type/entry/stop/target1/invalidation_price")
        if self.range_low is not None or self.range_high is not None:
            raise ValueError("long/short prediction 不得提交 neutral range")

        assert self.entry is not None and self.stop is not None
        assert self.target1 is not None and self.invalidation_price is not None
        risk = abs(self.entry - self.stop)
        reward = abs(self.target1 - self.entry)
        if risk <= 0 or reward / risk < 1:
            raise ValueError("prediction target1 风险收益比必须至少为 1")
        if self.direction == "long":
            if not self.stop < self.entry < self.target1:
                raise ValueError("long prediction 必须满足 stop < entry < target1")
            if self.invalidation_price > self.stop:
                raise ValueError("long invalidation_price 不得高于 stop")
            if self.target2 is not None and self.target2 <= self.target1:
                raise ValueError("long target2 必须高于 target1")
        else:
            if not self.target1 < self.entry < self.stop:
                raise ValueError("short prediction 必须满足 target1 < entry < stop")
            if self.invalidation_price < self.stop:
                raise ValueError("short invalidation_price 不得低于 stop")
            if self.target2 is not None and self.target2 >= self.target1:
                raise ValueError("short target2 必须低于 target1")
        return self

    @computed_field
    @property
    def risk_reward(self) -> float | None:
        if self.direction == "neutral" or self.entry is None or self.stop is None or self.target1 is None:
            return None
        risk = abs(self.entry - self.stop)
        reward = abs(self.target1 - self.entry)
        return reward / risk if risk > 0 and math.isfinite(risk) else None


class AgentPrediction(PredictionDraft):
    """通过服务端覆盖并可持久化/鉴权读取的 prediction。"""

    id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=256)
    run_id: str = Field(min_length=1, max_length=256)
    report_id: str | None = Field(default=None, max_length=256)
    status: PredictionStatus = "waiting"
    created_at: datetime
    updated_at: datetime


class PredictionEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PredictionStatus
    entry_time: str | None = None
    entry_price: float | None = None
    resolved_time: str | None = None


__all__ = [
    "AgentPrediction", "Direction", "EntryType", "PredictionAnchor", "PredictionDraft",
    "PredictionEvaluation", "PredictionScenario", "PredictionStatus",
]
