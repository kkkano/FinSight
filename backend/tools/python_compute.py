# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import html
import json
import time
from typing import Any

from .python_sandbox import PythonComputeRejected, validate_compute_request, run_with_timeout


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _code_hash(operation: str, params: dict[str, Any] | None) -> str:
    payload = {"operation": operation, "params": params or {}, "version": 1}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _coerce_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("quarterly", "quarters", "rows", "data", "facts", "results"):
        value = payload.get(key)
        rows = _coerce_rows(value)
        if rows:
            return rows
    return []


def _datasets_rows(datasets: dict[str, Any], ref: str) -> list[dict[str, Any]]:
    return _coerce_rows(datasets.get(ref))


def _pick_number(payload: Any, keys: tuple[str, ...]) -> float | None:
    if isinstance(payload, dict):
        for key in keys:
            value = _safe_float(payload.get(key))
            if value is not None:
                return value
        for item in payload.values():
            nested = _pick_number(item, keys)
            if nested is not None:
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = _pick_number(item, keys)
            if nested is not None:
                return nested
    return None


def _growth_pct(previous: float | None, current: float | None) -> float | None:
    if previous is None or current is None or previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100.0


def _compute_growth_rates(
    *,
    dataset_refs: list[str],
    params: dict[str, Any],
    datasets: dict[str, Any],
) -> dict[str, Any]:
    metric = str(params.get("metric") or "revenue").strip()
    rows: list[dict[str, Any]] = []
    for ref in dataset_refs:
        rows.extend(_datasets_rows(datasets, ref))
    if len(rows) < 2:
        return {
            "metrics": {},
            "tables": [],
            "warnings": ["not enough quarterly rows to compute growth"],
        }
    previous = rows[-2]
    current = rows[-1]
    previous_value = _safe_float(previous.get(metric))
    current_value = _safe_float(current.get(metric))
    growth = _round(_growth_pct(previous_value, current_value), 4)
    metric_name = f"{metric}_growth_pct"
    table = {
        "name": "growth_rates",
        "columns": ["period", metric, "growth_pct"],
        "rows": [
            {
                "period": previous.get("period") or previous.get("date") or "previous",
                metric: previous_value,
                "growth_pct": None,
            },
            {
                "period": current.get("period") or current.get("date") or "current",
                metric: current_value,
                "growth_pct": growth,
            },
        ],
    }
    return {"metrics": {metric_name: growth}, "tables": [table], "warnings": []}


def _compute_valuation_sanity(
    *,
    dataset_refs: list[str],
    params: dict[str, Any],
    datasets: dict[str, Any],
) -> dict[str, Any]:
    quote = datasets.get("step:get_stock_price")
    company = datasets.get("step:get_company_info")
    facts = datasets.get("step:get_sec_company_facts_quarterly")
    rows = _coerce_rows(facts)

    price = _pick_number(quote, ("price", "current_price", "regularMarketPrice", "close"))
    market_cap = _pick_number(company, ("marketCap", "market_cap", "marketCapitalization"))
    shares = _safe_float(params.get("shares_outstanding"))
    if market_cap is None and price is not None and shares is not None:
        market_cap = price * shares

    latest = rows[-1] if rows else {}
    previous = rows[-2] if len(rows) >= 2 else {}
    revenue = _safe_float(latest.get("revenue") or latest.get("revenues"))
    net_income = _safe_float(latest.get("net_income") or latest.get("netIncome"))
    previous_revenue = _safe_float(previous.get("revenue") or previous.get("revenues"))
    annualized_revenue = revenue * 4 if revenue is not None else None
    annualized_net_income = net_income * 4 if net_income is not None else None
    ps = market_cap / annualized_revenue if market_cap is not None and annualized_revenue else None
    pe = market_cap / annualized_net_income if market_cap is not None and annualized_net_income else None
    revenue_growth = _round(_growth_pct(previous_revenue, revenue), 4)

    warnings: list[str] = []
    if market_cap is None:
        warnings.append("market_cap missing")
    if annualized_revenue is None:
        warnings.append("annualized_revenue missing")
    if annualized_net_income is None:
        warnings.append("annualized_net_income missing")

    metrics = {
        "price": _round(price, 4),
        "market_cap": _round(market_cap, 4),
        "annualized_revenue": _round(annualized_revenue, 4),
        "annualized_net_income": _round(annualized_net_income, 4),
        "price_to_sales": _round(ps, 4),
        "price_to_earnings": _round(pe, 4),
        "revenue_growth_pct": revenue_growth,
    }
    table = {
        "name": "valuation_sanity",
        "columns": ["metric", "value"],
        "rows": [{"metric": key, "value": value} for key, value in metrics.items()],
    }
    return {"metrics": metrics, "tables": [table], "warnings": warnings}


def _compute_surprise_impact(
    *,
    dataset_refs: list[str],
    params: dict[str, Any],
    datasets: dict[str, Any],
) -> dict[str, Any]:
    del dataset_refs, datasets
    actual = _safe_float(params.get("actual"))
    expected = _safe_float(params.get("expected"))
    surprise_pct = _round(_growth_pct(expected, actual), 4)
    return {
        "metrics": {"surprise_pct": surprise_pct},
        "tables": [{"name": "surprise_impact", "columns": ["actual", "expected", "surprise_pct"], "rows": [{"actual": actual, "expected": expected, "surprise_pct": surprise_pct}]}],
        "warnings": [] if surprise_pct is not None else ["actual/expected missing"],
    }


def _compute_ratio_table(
    *,
    dataset_refs: list[str],
    params: dict[str, Any],
    datasets: dict[str, Any],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    numerator_key = str(params.get("numerator") or "net_income")
    denominator_key = str(params.get("denominator") or "revenue")
    for ref in dataset_refs:
        for item in _datasets_rows(datasets, ref):
            numerator = _safe_float(item.get(numerator_key))
            denominator = _safe_float(item.get(denominator_key))
            ratio = numerator / denominator if numerator is not None and denominator else None
            rows.append({"period": item.get("period") or item.get("date"), "ratio": _round(ratio, 4)})
    return {
        "metrics": {"row_count": len(rows)},
        "tables": [{"name": "ratio_table", "columns": ["period", "ratio"], "rows": rows}],
        "warnings": [] if rows else ["no rows available for ratio_table"],
    }


def _compute_growth_chart(
    *,
    dataset_refs: list[str],
    params: dict[str, Any],
    datasets: dict[str, Any],
) -> dict[str, Any]:
    metric = str(params.get("metric") or "revenue").strip()
    rows: list[dict[str, Any]] = []
    for ref in dataset_refs:
        rows.extend(_datasets_rows(datasets, ref))
    points: list[tuple[str, float]] = []
    for idx, row in enumerate(rows[:12]):
        value = _safe_float(row.get(metric))
        if value is None:
            continue
        label = str(row.get("period") or row.get("date") or f"P{idx + 1}")
        points.append((label, value))
    if not points:
        return {"metrics": {}, "tables": [], "warnings": ["no chartable rows"], "charts": []}

    width = 480
    height = 220
    pad = 32
    values = [value for _, value in points]
    min_value = min(values)
    max_value = max(values)
    span = max(max_value - min_value, 1.0)
    x_step = (width - pad * 2) / max(len(points) - 1, 1)
    coords: list[tuple[float, float, str, float]] = []
    for idx, (label, value) in enumerate(points):
        x = pad + idx * x_step
        y = height - pad - ((value - min_value) / span) * (height - pad * 2)
        coords.append((x, y, label, value))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in coords)
    circles = "\n".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3"><title>{html.escape(label)}: {value:.2f}</title></circle>'
        for x, y, label, value in coords
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="white"/>'
        f'<polyline points="{polyline}" fill="none" stroke="#2563eb" stroke-width="2"/>'
        f"{circles}</svg>"
    )
    return {
        "metrics": {"point_count": len(points), f"{metric}_latest": _round(points[-1][1], 4)},
        "tables": [{"name": "growth_chart_points", "columns": ["period", metric], "rows": [{"period": label, metric: value} for label, value in points]}],
        "warnings": [],
        "charts": [
            {
                "name": "growth_chart",
                "format": "svg",
                "metric": metric,
                "svg": svg,
                "input_refs": list(dataset_refs),
            }
        ],
    }


_OPERATIONS = {
    "growth_rates": _compute_growth_rates,
    "valuation_sanity": _compute_valuation_sanity,
    "surprise_impact": _compute_surprise_impact,
    "ratio_table": _compute_ratio_table,
    "growth_chart": _compute_growth_chart,
}


def run_python_compute(
    *,
    dataset_refs: list[str],
    operation: str,
    params: dict[str, Any] | None = None,
    datasets: dict[str, Any] | None = None,
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    start = time.perf_counter()
    refs = [str(ref or "").strip() for ref in (dataset_refs or []) if str(ref or "").strip()]
    op_name = str(operation or "").strip()
    clean_params = params if isinstance(params, dict) else {}
    clean_datasets = datasets if isinstance(datasets, dict) else {}

    try:
        validate_compute_request(dataset_refs=refs, operation=op_name, params=clean_params)
        compute_fn = _OPERATIONS[op_name]
        payload = run_with_timeout(
            lambda: compute_fn(dataset_refs=refs, params=clean_params, datasets=clean_datasets),
            timeout_s=timeout_s,
        )
        result = {
            "metrics": payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {},
            "tables": payload.get("tables") if isinstance(payload.get("tables"), list) else [],
            "charts": payload.get("charts") if isinstance(payload.get("charts"), list) else [],
            "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
            "code_hash": _code_hash(op_name, clean_params),
            "input_refs": refs,
            "duration_ms": int((time.perf_counter() - start) * 1000),
        }
        return result
    except PythonComputeRejected as exc:
        return {
            "error": "python_compute_rejected",
            "metrics": {},
            "tables": [],
            "charts": [],
            "warnings": [str(exc)],
            "code_hash": _code_hash(op_name, clean_params),
            "input_refs": refs,
            "duration_ms": int((time.perf_counter() - start) * 1000),
        }
    except Exception as exc:  # pragma: no cover - defensive runtime boundary
        return {
            "error": "python_compute_failed",
            "metrics": {},
            "tables": [],
            "charts": [],
            "warnings": [str(exc)],
            "code_hash": _code_hash(op_name, clean_params),
            "input_refs": refs,
            "duration_ms": int((time.perf_counter() - start) * 1000),
        }
