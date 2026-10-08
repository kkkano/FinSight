"""完成交易日窗口的量价计算；保留收盘路径及可复核公式。"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Any

from .financial_facts import fact_number
from .yfinance_client import create_ticker


def _request_time(as_of: str | None) -> datetime:
    if as_of and len(as_of) == 10:
        return datetime.combine(date.fromisoformat(as_of), time.max, timezone.utc)
    point = datetime.fromisoformat(as_of.replace("Z", "+00:00")) if as_of else datetime.now(timezone.utc)
    if point.tzinfo is None:
        raise ValueError("as_of_requires_timezone")
    return point.astimezone(timezone.utc)


@lru_cache(maxsize=3)
def _exchange_calendar(name: str):
    import pandas_market_calendars as mcal
    return mcal.get_calendar(name)


def _completed_dates(ticker: str, now: datetime, count: int) -> list[str]:
    if ticker.endswith("-USD"):
        return [(now.date() - timedelta(days=day)).isoformat() for day in range(count, 0, -1)]
    exchange = "HKEX" if ticker.endswith(".HK") else "SSE" if ticker.endswith((".SS", ".SZ", ".BJ")) else "NYSE"
    try:
        schedule = _exchange_calendar(exchange).schedule(
            start_date=now.date() - timedelta(days=count * 3 + 30), end_date=now.date() + timedelta(days=1))
        dates = [index.date().isoformat() for index, row in schedule.iterrows() if row["market_close"].to_pydatetime() <= now]
    except Exception as exc:
        raise ValueError("session_calendar_unavailable") from exc
    if len(dates) < count:
        raise ValueError("insufficient_calendar_sessions")
    return dates[-count:]


def get_price_window_metrics(
    ticker: str, sessions: int = 20, metrics: list[str] | None = None,
    as_of: str | None = None, price_basis: str = "close",
) -> dict[str, Any]:
    """按完成交易日计算价格回报、窗口最大回撤与量价突破；不包含现金股息。"""
    symbol = str(ticker or "").strip().upper()
    requested = list(dict.fromkeys(metrics or ["cumulative_return", "max_drawdown", "volume_breakout"]))
    result: dict[str, Any] = {
        "ticker": symbol, "subject": symbol, "kind": "price_window", "metric": "price_window",
        "sessions": sessions, "frequency": "daily", "source": "yfinance",
        "source_url": f"https://finance.yahoo.com/quote/{symbol}/history/",
        "price_basis": "split_adjusted_close", "dividends_included": False,
        "completed_only": True,
        "metrics": {}, "bars": [], "missing_metrics": [], "error": None,
        "warnings": ["Close 已按拆股调整，不含现金股息；股票窗口按交易所日历校验完成时段与逐日收盘完整性。"],
    }
    try:
        if not symbol or not 1 <= sessions <= 252 or price_basis != "close" or not set(requested) <= {"cumulative_return", "max_drawdown", "volume_breakout"}:
            raise ValueError("invalid_window_request")
        now = _request_time(as_of)
        expected = _completed_dates(symbol, now, sessions + ("cumulative_return" in requested))
        result["expected_session_dates"] = expected
        stock = create_ticker(symbol)
        frame = stock.history(start=(now - timedelta(days=sessions * 3 + 30)).date().isoformat(),
            end=(now + timedelta(days=1)).date().isoformat(), interval="1d", auto_adjust=False,
            actions=True, timeout=20, raise_errors=True)
        metadata = stock.get_history_metadata() or {}
        result["currency"] = metadata.get("currency")
        result["unit"] = metadata.get("currency")
        result["request_as_of"] = now.isoformat()
        bars = []
        result["bars"] = bars
        if frame is not None:
            for index, row in frame.sort_index().iterrows():
                day = index.date()
                if day.isoformat() not in expected:
                    continue
                close, high, low, volume = (fact_number(row.get(key)) for key in ("Close", "High", "Low", "Volume"))
                if close is None or close <= 0:
                    # 仅有公司行动的空行情行不算收盘点；缺少真实收盘仍由交易日完整性检查拒绝。
                    if close is None and high is None and low is None and (volume is None or volume == 0):
                        result.setdefault("empty_session_dates", []).append(day.isoformat())
                        continue
                    result["invalid_session_date"] = day.isoformat()
                    result["invalid_close_reason"] = "missing_or_nonfinite" if close is None else "nonpositive"
                    raise ValueError("invalid_close_path")
                if bars and bars[-1]["date"] == day.isoformat():
                    raise ValueError("duplicate_session")
                bars.append({"date": day.isoformat(), "close": close, "high": high, "low": low, "volume": volume})
        selected = bars
        result["bars"] = selected
        dates = {bar["date"] for bar in bars}
        result["missing_session_dates"] = [day for day in expected if day not in dates]
        if any(day not in dates for day in expected[-sessions:]):
            raise ValueError("insufficient_completed_sessions")
        window = bars[-sessions:]
        result.update(period_start=selected[0]["date"], period_end=window[-1]["date"],
            source_timestamp=window[-1]["date"], source_time_precision="date", source_time_status="provided",
            as_of=window[-1]["date"], market_session="continuous_close" if symbol.endswith("-USD") else "regular_close",
            end_close=window[-1]["close"], observation_count=len(window))
        if "cumulative_return" in requested:
            if not result["missing_session_dates"]:
                base, end = bars[-sessions - 1], bars[-1]
                result["metrics"]["cumulative_return"] = {"value": end["close"] / base["close"] - 1,
                    "base_date": base["date"], "base_close": base["close"], "end_date": end["date"],
                    "end_close": end["close"], "intervals": sessions, "formula": "end_close / base_close - 1"}
            else:
                result["missing_metrics"].append("cumulative_return")
        if "max_drawdown" in requested:
            peak = window[0]
            best = {"value": 0.0, "peak_date": peak["date"], "peak_close": peak["close"],
                "trough_date": peak["date"], "trough_close": peak["close"], "formula": "min(close / running_max_close - 1)"}
            for bar in window:
                if bar["close"] > peak["close"]:
                    peak = bar
                value = bar["close"] / peak["close"] - 1
                if value < best["value"]:
                    best.update(value=value, peak_date=peak["date"], peak_close=peak["close"],
                        trough_date=bar["date"], trough_close=bar["close"])
            result["metrics"]["max_drawdown"] = best
        if "volume_breakout" in requested:
            prior, end = window[:-1], window[-1]
            if prior and all(bar["high"] is not None and bar["low"] is not None and bar["volume"] is not None and bar["volume"] > 0 for bar in window):
                high, low = max(bar["high"] for bar in prior), min(bar["low"] for bar in prior)
                mean_volume = sum(bar["volume"] for bar in prior) / len(prior)
                relative_volume = end["volume"] / mean_volume
                result["metrics"]["volume_breakout"] = {"range_high": high, "range_low": low,
                    "range_start": prior[0]["date"], "range_end": prior[-1]["date"], "close": end["close"],
                    "volume": end["volume"], "prior_mean_volume": mean_volume, "relative_volume": relative_volume,
                    "breakout": end["close"] > high, "volume_confirmed": relative_volume >= 1.5,
                    "confirmation_threshold": 1.5, "invalidation_close_below": high,
                    "formula": "latest_close > prior_range_high; latest_volume / prior_mean_volume >= 1.5"}
            else:
                result["missing_metrics"].append("volume_breakout")
        if not result.get("currency"):
            result["missing_metrics"].append("currency")
    except Exception as exc:
        result["error"] = str(exc) if isinstance(exc, ValueError) else "price_window_unavailable"
        result["missing_metrics"] = list(dict.fromkeys(result["missing_metrics"] + requested))
    result["structured_data"] = dict(result)
    return result
