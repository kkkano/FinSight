# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.agents.prediction_contract import PredictionAnchor, PredictionDraft


def _long_payload() -> dict:
    return {
        "symbol": "AAPL",
        "agent": "technical_agent",
        "direction": "long",
        "confidence": 0.72,
        "thesis": "突破后延续",
        "anchor": {"timeframe": "1d", "time": "2026-07-10", "price": 210.0},
        "entry_type": "limit",
        "entry": 211.0,
        "stop": 205.0,
        "target1": 223.0,
        "target2": 229.0,
        "invalidation_price": 204.0,
    }


@pytest.mark.parametrize("field", ["bars", "candles", "series", "ohlc", "data", "user_id", "run_id"])
def test_prediction_rejects_extra_or_spoofable_fields(field: str):
    payload = _long_payload()
    payload[field] = [] if field in {"bars", "candles", "series", "ohlc", "data"} else "forged"
    with pytest.raises(ValidationError):
        PredictionDraft.model_validate(payload)


def test_long_and_short_require_ordered_numeric_risk_reward_levels():
    long_prediction = PredictionDraft.model_validate(_long_payload())
    assert long_prediction.risk_reward == pytest.approx(2.0)

    short_payload = _long_payload() | {
        "direction": "short",
        "entry_type": "stop",
        "entry": 205.0,
        "stop": 211.0,
        "target1": 193.0,
        "target2": 188.0,
        "invalidation_price": 212.0,
    }
    short_prediction = PredictionDraft.model_validate(short_payload)
    assert short_prediction.risk_reward == pytest.approx(2.0)

    for key, value in {
        "entry": None,
        "stop": "not-a-number",
        "target1": 210.0,
        "invalidation_price": 212.0,
    }.items():
        invalid = _long_payload()
        invalid[key] = value
        with pytest.raises(ValidationError):
            PredictionDraft.model_validate(invalid)


def test_neutral_requires_only_range_containing_anchor():
    neutral = PredictionDraft.model_validate({
        "symbol": "MSFT",
        "agent": "price_agent",
        "direction": "neutral",
        "confidence": 0.55,
        "thesis": "区间等待",
        "anchor": {"timeframe": "1d", "time": "2026-07-10", "price": 450.0},
        "range_low": 440.0,
        "range_high": 460.0,
    })
    assert neutral.range_low == 440.0

    with pytest.raises(ValidationError):
        PredictionDraft.model_validate(neutral.model_dump() | {"entry": 450.0})
    with pytest.raises(ValidationError):
        PredictionDraft.model_validate(neutral.model_dump() | {"range_high": 445.0})


@pytest.mark.parametrize("entry_type", ["market", "limit", "stop"])
def test_entry_type_is_closed_enum(entry_type: str):
    PredictionDraft.model_validate(_long_payload() | {"entry_type": entry_type})

    with pytest.raises(ValidationError):
        PredictionDraft.model_validate(_long_payload() | {"entry_type": "close"})


def test_anchor_requires_positive_finite_price():
    with pytest.raises(ValidationError):
        PredictionAnchor(timeframe="1d", time="2026-07-10", price=float("nan"))

