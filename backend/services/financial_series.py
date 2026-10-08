"""按实际期间投影财务序列；展示端不再猜期间或计算会计指标。"""
from __future__ import annotations

from datetime import date
from typing import Any

from backend.tools.financial_facts import comparison_point, fact_date, fact_number, growth_rate


def derive_financial_series(statement: dict[str, Any]) -> dict[str, Any]:
    ends = statement.get("period_ends") or statement.get("periods") or []
    metadata = statement.get("fact_metadata") or {}
    frequencies = statement.get("metric_frequencies") or {}
    currencies = statement.get("metric_currencies") or {}

    def row_meta(metric: str, index: int) -> dict:
        rows = metadata.get(metric)
        if isinstance(rows, list) and index < len(rows) and isinstance(rows[index], dict):
            return rows[index]
        return {}

    def compatible(metric: str, current: int, prior: int) -> bool:
        rows = [row_meta(metric, idx) for idx in (current, prior)]
        frequency = frequencies.get(metric) or statement.get("frequency")
        if frequency not in {"annual", "quarterly", "semiannual", "instant"}:
            return False
        for key in ("frequency", "unit", "concept", "reporting_basis"):
            if rows[0].get(key) and rows[1].get(key) and rows[0][key] != rows[1][key]:
                return False
        starts = [fact_date(row.get("period_start")) for row in rows]
        if all(starts) and not 350 <= (date.fromisoformat(starts[0]) - date.fromisoformat(starts[1])).days <= 380:
            return False
        return True

    yoy: dict[str, list[float | None]] = {}
    for metric in frequencies:
        values = statement.get(metric) or []
        changes: list[float | None] = []
        for index, end in enumerate(ends):
            current = fact_date(end)
            candidates = [
                {"period": day, "value": values[other] if other < len(values) else None, "index": other}
                for other, raw in enumerate(ends) if other != index and (day := fact_date(raw))
                and current and day < current
            ]
            previous = comparison_point([{"period": current}, *candidates], days=365, tolerance=15)
            value = values[index] if index < len(values) else None
            changes.append(
                growth_rate(value, previous["value"])
                if previous and compatible(metric, index, previous["index"]) else None
            )
        yoy[metric] = changes

    def margin(metric: str, index: int) -> float | None:
        denominator = fact_number((statement.get("revenue") or [])[index])
        numerator = fact_number((statement.get(metric) or [])[index])
        if denominator in {None, 0} or numerator is None:
            return None
        if frequencies.get(metric) != frequencies.get("revenue") or currencies.get(metric) != currencies.get("revenue"):
            return None
        starts = [row_meta(name, index).get("period_start") for name in (metric, "revenue")]
        if all(starts) and starts[0] != starts[1]:
            return None
        return numerator / denominator * 100

    assets, liabilities = statement.get("total_assets") or [], statement.get("total_liabilities") or []
    latest = next((index for index in sorted(range(len(ends)), key=lambda idx: str(ends[idx]), reverse=True)
                   if (index < len(assets) and assets[index] is not None) or (index < len(liabilities) and liabilities[index] is not None)), None)
    summary: dict[str, Any] = {"period": None, "total_assets": None, "total_liabilities": None, "equity": None, "de_ratio": None}
    if latest is not None:
        asset = fact_number(assets[latest]) if latest < len(assets) else None
        liability = fact_number(liabilities[latest]) if latest < len(liabilities) else None
        same_unit = currencies.get("total_assets") == currencies.get("total_liabilities")
        equity = asset - liability if asset is not None and liability is not None and same_unit else None
        summary = {
            "period": statement["periods"][latest], "total_assets": asset, "total_liabilities": liability,
            "equity": equity, "de_ratio": liability / equity if liability is not None and equity not in {None, 0} else None,
        }
    return {
        "yoy": yoy, "gross_margin": [margin("gross_profit", idx) for idx in range(len(ends))],
        "net_margin": [margin("net_income", idx) for idx in range(len(ends))], "balance_summary": summary,
    }
