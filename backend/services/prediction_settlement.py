"""Deterministic five-session price and close-to-close drawdown scoring."""
from __future__ import annotations

from datetime import date, timedelta

from backend.services.prediction_calendar import iso, utc_now
from backend.services.prediction_market import SOURCE, PredictionDataError, load_bars


def score_window(prediction: dict, bars: list[dict], sessions: list[str]) -> dict:
    by_date = {row["time"]: row for row in bars}
    if len(sessions) != 5 or any(day not in by_date for day in sessions):
        raise PredictionDataError("settlement_prices_missing")
    import math
    p0 = float(by_date[sessions[0]]["open"])
    closes = [float(by_date[day]["close"]) for day in sessions]
    if not all(math.isfinite(price) and price > 0 for price in [p0, *closes]):
        raise PredictionDataError("invalid_market_prices")
    # Arithmetic comparisons preserve equality at the published thresholds.
    change = closes[-1] / p0 - 1
    delta = closes[-1] - p0
    direction = "up" if delta > p0 * .005 + 1e-10 else "down" if delta < -p0 * .005 - 1e-10 else "flat"
    peak = p0
    drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        drawdown = max(drawdown, 1 - close / peak)
    event = drawdown >= .05 - 1e-12
    if prediction["prediction_type"] == "direction":
        hit, baseline = prediction["direction"] == direction, direction == "up"
    elif prediction["prediction_type"] == "drawdown":
        hit, baseline = prediction["event_occurs"] is event, not event
    else:
        raise ValueError("unsupported prediction type")
    return {"p0": p0, "p5": closes[-1], "return_pct": change,
            "max_drawdown": drawdown, "actual_direction": direction, "actual_event": event,
            "hit": hit, "baseline_hit": baseline, "source": SOURCE}


def settle_due(store, *, now=None, loader=load_bars) -> dict:
    now = now or utc_now()
    settled = missing = 0
    market_cache = {}
    for record in store.due_records(iso(now - timedelta(minutes=20))):
        sessions = record["sessions"]
        try:
            key = (record["batch_id"], record["ticker"])
            if key not in market_cache:
                frozen = store.settled_market(*key)
                market_cache[key] = frozen if frozen is not None else loader(record["ticker"], date.fromisoformat(sessions[0]), date.fromisoformat(sessions[-1]))
            bars = market_cache[key]
            outcome = score_window(record["prediction"], bars, sessions)
            outcome["settled_at"] = iso(now)
            if store.settle(record["id"], outcome, bars):
                settled += 1
        except Exception as exc:
            # Provider messages can contain identifiers. Only persist our own codes.
            error = str(exc) if isinstance(exc, PredictionDataError) else "market_data_unavailable"
            store.mark_awaiting_data(record["id"], error)
            missing += 1
    return {"settled": settled, "awaiting_data": missing}
