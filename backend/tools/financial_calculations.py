"""对已核验的同口径两期事实确定性计算，并保留输入来源。"""
from __future__ import annotations

from datetime import date
from typing import Any

from .financial_facts import fact_date, fact_number


def calculate_period_change(current: dict, previous: dict, *, operation: str, baseline: str) -> dict[str, Any] | None:
    values = [fact_number(row.get("value")) for row in (current, previous)]
    if any(value is None for value in values):
        return None
    if any(not row.get("source_url") for row in (current, previous)):
        return None
    if any(not current.get(key) or current.get(key) != previous.get(key) for key in ("subject", "metric", "unit", "frequency")):
        return None
    if current.get("concept") and previous.get("concept") and current["concept"] != previous["concept"]:
        return None
    dates = [fact_date(row.get(key)) for row in (current, previous) for key in ("period_start", "period_end")]
    if not all(dates):
        return None
    start, end, prior_start, prior_end = [date.fromisoformat(value) for value in dates]
    if abs((end - start).days - (prior_end - prior_start).days) > 14:
        return None
    if baseline == "year_ago":
        if not 350 <= (end - prior_end).days <= 380 or not 350 <= (start - prior_start).days <= 380:
            return None
    elif baseline == "previous_period":
        if not 1 <= (start - prior_end).days <= 8:
            return None
    else:
        return None
    current_value, previous_value = values
    if operation in {"growth_rate", "ratio"} and previous_value == 0:
        return None
    # 非正基数的增长率易产生误导，保留原始两期金额而不发布百分比。
    if operation == "growth_rate":
        if previous_value <= 0:
            return None
        value = current_value / previous_value - 1
    elif operation == "difference":
        value = current_value - previous_value
    elif operation == "ratio":
        value = current_value / previous_value
    else:
        return None
    if fact_number(value) is None:
        return None
    return {
        **current, "value": value, "unit": "ratio" if operation != "difference" else current["unit"],
        "operation": operation, "baseline": baseline, "input_unit": current["unit"],
        "derivation_inputs": [dict(current), dict(previous)],
    }
