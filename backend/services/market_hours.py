"""按证券市场的交易日历判断时段，包含午休和提前收市。"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from backend.services.data_contract import AssetContext
from backend.services.prediction_calendar import calendar

MarketSession = str


@lru_cache(maxsize=256)
def _session_schedule(calendar_name: str, day: date) -> dict | None:
    schedule = calendar(calendar_name).schedule(start_date=day, end_date=day)
    return None if schedule.empty else schedule.iloc[0].to_dict()


def get_market_session(
    now: datetime | None = None, *, symbol: str | None = None, asset: AssetContext | None = None,
) -> MarketSession:
    context = asset or AssetContext.from_symbol(symbol or "")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if context.calendar_name is None:
        return "regular" if context.market == "CRYPTO" else "closed"
    local = now.astimezone(ZoneInfo(context.timezone))
    schedule = _session_schedule(context.calendar_name, local.date())
    if schedule is None:
        return "closed"
    opening, closing = schedule["market_open"], schedule["market_close"]
    if opening <= now < closing:
        break_start, break_end = schedule.get("break_start"), schedule.get("break_end")
        if break_start is not None and break_end is not None and break_start <= now < break_end:
            return "closed"
        return "regular"
    if context.market == "US":
        if time(4) <= local.time() and now < opening:
            return "pre_market"
        if now >= closing and local.time() < time(20):
            return "after_hours"
    return "closed"


def is_completed_session(day: date, *, asset: AssetContext, as_of: datetime) -> bool:
    if asset.market == "CRYPTO":
        return datetime.combine(day + timedelta(days=1), time(), tzinfo=timezone.utc) <= as_of
    if asset.calendar_name is None:
        return False
    schedule = _session_schedule(asset.calendar_name, day)
    return schedule is not None and schedule["market_close"] <= as_of


__all__ = ["MarketSession", "get_market_session", "is_completed_session"]
