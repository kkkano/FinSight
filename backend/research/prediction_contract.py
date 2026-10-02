"""Immutable issuance inputs and validated results for prospective forecasts."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


PredictionType = Literal["direction", "drawdown"]
Direction = Literal["up", "down", "flat"]


def parse_utc(value: str) -> datetime:
    """Require an explicit UTC offset rather than silently assuming local time."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("UTC timestamp required")
    return parsed


class ForecastContext(BaseModel):
    """The caller freezes identity and scoring; the model cannot set these fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,9}$")
    batch_date: str
    knowledge_cutoff: str
    window_start: str
    window_end: str
    deadline_at: str
    horizon_sessions: Literal[5] = 5
    direction_threshold: Literal[0.005] = 0.005
    drawdown_threshold: Literal[0.05] = 0.05
    scorer_version: Literal["price-close-v1"] = "price-close-v1"

    @field_validator("batch_date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("batch_date must be YYYY-MM-DD")
        return value

    @field_validator("knowledge_cutoff", "window_start", "window_end", "deadline_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return parse_utc(value).isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def validate_window(self) -> "ForecastContext":
        if not (
            parse_utc(self.knowledge_cutoff)
            < parse_utc(self.deadline_at)
            < parse_utc(self.window_start)
            < parse_utc(self.window_end)
        ):
            raise ValueError("cutoff, deadline, start and end must be ordered")
        return self


class _ForecastPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["predicted", "abstained"]
    reason: str = Field(min_length=1, max_length=600)
    evidence_refs: list[str] = Field(max_length=12)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason cannot be blank")
        return value


class DirectionForecastPayload(_ForecastPayload):
    direction: Direction | None

    @model_validator(mode="after")
    def validate_judgment(self) -> "DirectionForecastPayload":
        if self.status == "predicted" and (self.direction is None or not self.evidence_refs):
            raise ValueError("a prediction requires a direction and evidence")
        if self.status == "abstained" and self.direction is not None:
            raise ValueError("an abstention cannot contain a prediction")
        return self


class DrawdownForecastPayload(_ForecastPayload):
    event_occurs: StrictBool | None

    @model_validator(mode="after")
    def validate_judgment(self) -> "DrawdownForecastPayload":
        if self.status == "predicted" and (self.event_occurs is None or not self.evidence_refs):
            raise ValueError("a prediction requires an event judgment and evidence")
        if self.status == "abstained" and self.event_occurs is not None:
            raise ValueError("an abstention cannot contain a prediction")
        return self


class ForecastResult(BaseModel):
    """One attempt, including failures and deliberate, non-retryable abstentions."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: Literal["predicted", "abstained", "failed"]
    prediction_type: PredictionType
    direction: Direction | None = None
    event_occurs: StrictBool | None = None
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)
    error_code: str | None = None
    retryable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    prompt_version: str
    issued_at: str

    @field_validator("issued_at")
    @classmethod
    def validate_issued_at(cls, value: str) -> str:
        return parse_utc(value).isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def validate_status(self) -> "ForecastResult":
        if self.status == "predicted":
            if not self.evidence_refs:
                raise ValueError("prediction requires input evidence")
            if self.prediction_type == "direction":
                if self.direction is None or self.event_occurs is not None:
                    raise ValueError("direction prediction has incompatible fields")
            elif self.event_occurs is None or self.direction is not None:
                raise ValueError("drawdown prediction has incompatible fields")
        elif self.direction is not None or self.event_occurs is not None:
            raise ValueError("only predictions may contain judgments")
        if self.status == "failed" and not self.error_code:
            raise ValueError("failure requires an error code")
        if self.status != "failed" and (self.retryable or self.error_code is not None):
            raise ValueError("accepted decisions cannot be retried")
        return self
