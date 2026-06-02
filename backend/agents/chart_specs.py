# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "").replace("%", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _row_label(row: dict[str, Any], fallback: int) -> str:
    for key in ("time", "date", "datetime", "timestamp", "period"):
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if "T" in text:
            text = text.split("T", 1)[0]
        return text
    return str(fallback + 1)


def _kline_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("kline_data") or payload.get("data") or payload.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and _safe_float(row.get("close") or row.get("Close")) is not None]


def _ohlc_from_rows(rows: list[dict[str, Any]], *, limit: int = 60) -> dict[str, Any] | None:
    clean_rows = rows[-limit:]
    labels: list[str] = []
    values: list[float] = []
    ohlc: list[list[float]] = []
    volume: list[float] = []

    for index, row in enumerate(clean_rows):
        close = _safe_float(row.get("close") or row.get("Close"))
        if close is None:
            continue
        open_value = _safe_float(row.get("open") or row.get("Open")) or close
        high_value = _safe_float(row.get("high") or row.get("High")) or max(open_value, close)
        low_value = _safe_float(row.get("low") or row.get("Low")) or min(open_value, close)
        labels.append(_row_label(row, index))
        values.append(round(close, 4))
        ohlc.append([
            round(open_value, 4),
            round(close, 4),
            round(low_value, 4),
            round(high_value, 4),
        ])
        vol = _safe_float(row.get("volume") or row.get("Volume"))
        if vol is not None:
            volume.append(round(vol, 4))

    if not labels or len(labels) != len(ohlc):
        return None

    data: dict[str, Any] = {
        "labels": labels,
        "values": values,
        "ohlc": ohlc,
    }
    if len(volume) == len(labels):
        data["volume"] = volume
    return data


def _event_specs(snapshot: dict[str, Any], labels: list[str], values: list[float]) -> list[dict[str, Any]]:
    if not labels:
        return []
    event = snapshot.get("event_explanation") if isinstance(snapshot.get("event_explanation"), dict) else {}
    if not event:
        return []
    label = str(event.get("summary") or event.get("todo") or event.get("trigger") or "").strip()
    if not label:
        return []
    return [
        {
            "label": label[:80],
            "index": len(labels) - 1,
            "value": values[-1] if values else None,
            "kind": "catalyst" if event.get("source") else "event",
        }
    ]


def _series_from_rows(name: str, rows: list[dict[str, Any]], labels: list[str]) -> dict[str, Any] | None:
    if not labels:
        return None
    by_label: dict[str, float] = {}
    for index, row in enumerate(rows):
        close = _safe_float(row.get("close") or row.get("Close"))
        if close is None:
            continue
        by_label[_row_label(row, index)] = round(close, 4)

    values = [by_label.get(label) for label in labels]
    if any(value is None for value in values):
        closes = [
            round(close, 4)
            for close in (_safe_float(row.get("close") or row.get("Close")) for row in rows[-len(labels):])
            if close is not None
        ]
        if len(closes) != len(labels):
            return None
        values = closes

    numeric_values = [float(value) for value in values if value is not None]
    if not numeric_values or all(value == 0 for value in numeric_values):
        return None
    return {"name": name, "values": numeric_values}


def build_price_behavior_chart_specs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict) or snapshot.get("snapshot_type") != "PriceBehaviorSnapshot":
        return []

    raw = snapshot.get("raw") if isinstance(snapshot.get("raw"), dict) else {}
    history = raw.get("history") if isinstance(raw.get("history"), dict) else {}
    rows = _kline_rows(history)
    ohlc_data = _ohlc_from_rows(rows)
    if not ohlc_data:
        return []

    quote = snapshot.get("quote") if isinstance(snapshot.get("quote"), dict) else {}
    ticker = str(snapshot.get("ticker") or quote.get("ticker") or "Price").strip().upper() or "Price"
    currency = str(quote.get("currency") or snapshot.get("currency") or "USD").strip() or "USD"
    labels = ohlc_data["labels"]
    values = ohlc_data["values"]
    base_data = {**ohlc_data, "unit": currency}
    events = _event_specs(snapshot, labels, values)
    if events:
        base_data["events"] = events

    specs: list[dict[str, Any]] = [
        {
            "type": "candlestick",
            "title": f"{ticker} candlestick",
            "data": base_data,
        }
    ]
    if "volume" in ohlc_data:
        specs.append(
            {
                "type": "price_volume",
                "title": f"{ticker} price and volume",
                "data": base_data,
            }
        )

    benchmarks = raw.get("benchmarks") if isinstance(raw.get("benchmarks"), dict) else {}
    series: list[dict[str, Any]] = []
    target_series = _series_from_rows(ticker, rows, labels)
    if target_series:
        series.append(target_series)
    for benchmark in ("SPY", "QQQ"):
        payload = benchmarks.get(benchmark) if isinstance(benchmarks.get(benchmark), dict) else {}
        benchmark_series = _series_from_rows(benchmark, _kline_rows(payload), labels)
        if benchmark_series:
            series.append(benchmark_series)
    if len(series) >= 2:
        specs.append(
            {
                "type": "rs_line",
                "title": f"{ticker} relative strength",
                "data": {
                    "labels": labels,
                    "values": values,
                    "series": series,
                },
            }
        )
    return specs


def build_news_sentiment_chart_specs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    ticker = str(snapshot.get("ticker") or "News").strip().upper() or "News"
    bias = snapshot.get("sentiment_bias") if isinstance(snapshot.get("sentiment_bias"), dict) else {}
    trend = snapshot.get("sentiment_trend") if isinstance(snapshot.get("sentiment_trend"), dict) else {}

    specs: list[dict[str, Any]] = []
    counts = [
        int(_safe_float(bias.get("positive_count")) or 0),
        int(_safe_float(bias.get("neutral_count")) or 0),
        int(_safe_float(bias.get("negative_count")) or 0),
    ]
    if any(counts):
        specs.append(
            {
                "type": "pie",
                "title": f"{ticker} news sentiment mix",
                "data": {
                    "labels": ["Positive", "Neutral", "Negative"],
                    "values": counts,
                },
            }
        )

    previous_avg = _safe_float(trend.get("previous_average"))
    recent_avg = _safe_float(trend.get("recent_average"))
    if previous_avg is not None and recent_avg is not None:
        specs.append(
            {
                "type": "line",
                "title": f"{ticker} sentiment trend",
                "data": {
                    "labels": ["Previous", "Recent"],
                    "values": [round(previous_avg, 4), round(recent_avg, 4)],
                },
            }
        )
    return specs


def build_fundamental_chart_specs(ticker: str, normalized: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(normalized, dict):
        return []
    ticker_label = str(ticker or "Fundamental").strip().upper() or "Fundamental"
    metric_map = normalized.get("metrics") if isinstance(normalized.get("metrics"), dict) else {}
    if not metric_map:
        return []

    preferred_order = (
        "revenue",
        "net_income",
        "operating_income",
        "operating_cash_flow",
        "total_assets",
        "total_liabilities",
    )
    specs: list[dict[str, Any]] = []
    labels: list[str] = []
    values: list[float] = []
    growth_labels: list[str] = []
    growth_values: list[float] = []

    for key in preferred_order:
        metric = metric_map.get(key)
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label") or key).strip() or key
        latest = _safe_float(metric.get("latest"))
        if latest is not None:
            labels.append(label)
            values.append(round(latest / 1_000_000_000.0, 4))
        yoy = _safe_float(metric.get("yoy"))
        if yoy is not None:
            growth_labels.append(f"{label} YoY")
            growth_values.append(round(yoy * 100.0, 4))

    if labels and values:
        specs.append(
            {
                "type": "bar",
                "title": f"{ticker_label} latest fundamentals",
                "data": {
                    "labels": labels,
                    "values": values,
                    "unit": "$B",
                },
            }
        )
    if len(growth_labels) >= 2:
        specs.append(
            {
                "type": "waterfall",
                "title": f"{ticker_label} YoY growth bridge",
                "data": {
                    "labels": growth_labels,
                    "values": growth_values,
                    "unit": "%",
                },
            }
        )
    return specs
