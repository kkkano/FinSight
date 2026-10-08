"""NYSE session windows shared by collection, settlement and health checks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from importlib.metadata import version
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("prediction timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


@lru_cache(maxsize=8)
def calendar(name: str = "NYSE"):
    import pandas_market_calendars as mcal
    return mcal.get_calendar(name)


@dataclass(frozen=True)
class PredictionWindow:
    batch_date: str
    collection_at: str
    deadline_at: str
    alert_at: str
    knowledge_cutoff: str
    window_start: str
    window_end: str
    sessions: tuple[str, ...]
    calendar_version: str

    def context(self, ticker: str) -> dict:
        return {"ticker": ticker, "batch_date": self.batch_date,
                "knowledge_cutoff": self.knowledge_cutoff, "window_start": self.window_start,
                "window_end": self.window_end, "deadline_at": self.deadline_at,
                "horizon_sessions": 5, "direction_threshold": .005,
                "drawdown_threshold": .05, "scorer_version": "price-close-v1"}


@lru_cache(maxsize=128)
def window_for_date(day: date) -> PredictionWindow | None:
    schedule = calendar().schedule(start_date=day - timedelta(days=14), end_date=day + timedelta(days=21))
    dates = [index.date() for index in schedule.index]
    if day not in dates:
        return None
    index = dates.index(day)
    if index == 0 or index + 4 >= len(dates):
        raise ValueError("calendar does not cover prediction window")
    selected = schedule.iloc[index:index + 5]
    local = lambda hour, minute: iso(datetime.combine(day, time(hour, minute), tzinfo=NY))
    return PredictionWindow(
        batch_date=day.isoformat(), collection_at=local(8, 45), deadline_at=local(9, 20),
        alert_at=local(9, 25), knowledge_cutoff=iso(schedule.iloc[index - 1]["market_close"].to_pydatetime()),
        window_start=iso(selected.iloc[0]["market_open"].to_pydatetime()),
        window_end=iso(selected.iloc[-1]["market_close"].to_pydatetime()),
        sessions=tuple(item.date().isoformat() for item in selected.index),
        calendar_version="pandas_market_calendars/" + version("pandas_market_calendars"),
    )


def current_window(now: datetime | None = None) -> PredictionWindow | None:
    return window_for_date((now or utc_now()).astimezone(NY).date())
