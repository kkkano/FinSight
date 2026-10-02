"""One source and explicit price adjustment policy for all benchmark prices."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import numpy as np

from backend.services.prediction_calendar import NY, timestamp, utc_now, iso

SOURCE = "yahoo/yfinance-0.2.66"


class PredictionDataError(ValueError):
    pass


def load_bars(ticker: str, start: date, end: date) -> list[dict[str, Any]]:
    from backend.tools.yfinance_client import create_ticker
    frame = create_ticker(ticker).history(
        start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), interval="1d",
        auto_adjust=False, back_adjust=False, repair=False, actions=True,
        prepost=False, timeout=20, raise_errors=True,
    )
    if frame.empty:
        raise PredictionDataError("market_data_unavailable")
    bars = []
    for index, row in frame.iterrows():
        day = index.date()
        if not start <= day <= end:
            continue
        values = {key: float(row[column]) for key, column in (
            ("open", "Open"), ("high", "High"), ("low", "Low"), ("close", "Close"))}
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            raise PredictionDataError("invalid_market_prices")
        bars.append({"time": day.isoformat(), **values,
                     "volume": float(row.get("Volume", 0)),
                     "dividends": float(row.get("Dividends", 0)),
                     "stock_splits": float(row.get("Stock Splits", 0))})
    if not bars:
        raise PredictionDataError("market_data_unavailable")
    return sorted(bars, key=lambda item: item["time"])


def build_snapshot(ticker: str, knowledge_cutoff: str, *, loader=load_bars) -> dict:
    day = timestamp(knowledge_cutoff).astimezone(NY).date()
    bars = loader(ticker, day - timedelta(days=380), day)
    if len(bars) < 60 or bars[-1]["time"] != day.isoformat():
        raise PredictionDataError("history_missing_or_stale")
    from backend.agents.technical_agent import TechnicalAgent
    agent = TechnicalAgent(None, None, None)
    features = dict(agent._compute_indicators(bars) or {})
    closes = np.asarray([item["close"] for item in bars], dtype=float)
    recent = closes[-60:]
    features.update({
        "last_close": float(closes[-1]),
        "return_5d": float(closes[-1] / closes[-6] - 1),
        "return_20d": float(closes[-1] / closes[-21] - 1),
        "realized_vol20": float(np.std(np.diff(np.log(closes[-21:])), ddof=1) * np.sqrt(252)),
        "max_drawdown60": float(np.max(1 - recent / np.maximum.accumulate(recent))),
    })
    features = {k: (None if isinstance(v, (int, float)) and not math.isfinite(v) else v) for k, v in features.items()}
    return {"as_of": knowledge_cutoff, "source": SOURCE, "fetched_at": iso(utc_now()),
            "features": features, "bars": bars, "adjustment": "split_adjusted_no_cash_dividends"}
