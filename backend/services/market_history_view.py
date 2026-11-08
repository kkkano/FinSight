"""界面/研究历史范围投影，不改变冻结预测使用的原始行情网关。"""
from __future__ import annotations

from datetime import datetime
import re
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta


def clip_history_period(result: dict, period: str, *, now: datetime | None = None) -> dict:
    if result.get("error_code") or period == "max":
        return result
    points = result.get("kline_data") or result.get("data")
    if not isinstance(points, list) or not points:
        return result
    match = re.fullmatch(r"(\d+)(d|wk|mo|y)", period)
    if not match and period != "ytd":
        return result
    zone = ZoneInfo((result.get("asset") or {}).get("timezone") or "UTC")
    end = (now.astimezone(zone) if now else datetime.now(zone)).date()
    if period == "ytd":
        start = end.replace(month=1, day=1)
    else:
        count, unit = int(match.group(1)), match.group(2)
        delta = {"d": "days", "wk": "weeks", "mo": "months", "y": "years"}[unit]
        start = end - relativedelta(**{delta: count})
    date_of = lambda row: str(row.get("time") or row.get("date") or "")[:10]
    selected = [row for row in points if isinstance(row, dict) and start.isoformat() <= date_of(row) <= end.isoformat()]
    if not selected:
        return {**result, "status": "error", "data": [], "kline_data": [], "error": "market_data_unavailable",
                "error_code": "market_data_unavailable", "summary": "所选时间段内没有可用行情。", "reason": "所选时间段内没有可用行情。"}
    return {**result, "data": selected, "kline_data": selected, "period": period,
            "requested_start": start.isoformat(), "requested_end": end.isoformat(),
            "returned_start": date_of(selected[0]) if selected else None, "returned_end": date_of(selected[-1]) if selected else None}
