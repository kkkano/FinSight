"""沙箱财务纯函数；不导入后台工具、运行状态、文件或网络。

数值/日期/期间变化函数机械移自 tools/financial_facts.py 与 financial_calculations.py；
比率核心机械移自 agent_runtime/analysis.py，仅改函数名及同文件依赖。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import math
from typing import Any


def fact_date(value: Any) -> str | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10]).isoformat()
    except ValueError:
        return None


def fact_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def duration_frequency(start: Any, end: Any) -> str:
    start_date, end_date = fact_date(start), fact_date(end)
    if not start_date or not end_date:
        return "unknown"
    days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1
    if 70 <= days <= 110:
        return "quarterly"
    if 330 <= days <= 380:
        return "annual"
    if 150 <= days <= 210:
        return "semiannual"
    return "unknown"


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


def financial_ratios_from_rows(rows: list[dict]) -> dict:
    """仅对同主体、同财期、同货币的 SEC 单季事实计算，不年化或预测。"""

    periods = [row for row in rows if fact_date(row.get("period_end"))]
    if not periods or any(row.get("source") != "sec_companyfacts" or row.get("frequency") != "quarterly" for row in periods):
        return {"status": "unavailable", "error": "financial_quarterly_facts_required",
                "summary": "这项比率计算需要带真实财期和币种的 SEC 单季事实。"}
    latest = max(periods, key=lambda row: fact_date(row["period_end"]))
    ticker, currency = latest.get("ticker"), latest.get("currency")
    if not ticker or not currency or any(row.get("ticker") != ticker or row.get("currency") != currency for row in periods):
        return {"status": "unavailable", "error": "financial_fact_context_mismatch",
                "summary": "财报主体或币种不一致，不能合并计算比率。"}

    def fact(row, metric):
        value = fact_number(row.get(metric))
        if value is None:
            return None
        metadata = (row.get("fact_metadata") or {}).get(metric)
        frequency = "instant" if metric in {"total_assets", "total_liabilities", "long_term_debt", "cash_and_equivalents"} else "quarterly"
        if isinstance(metadata, dict):
            if (metadata.get("subject") != ticker or metadata.get("unit") != currency
                    or metadata.get("frequency") != frequency or fact_date(metadata.get("period_end")) != fact_date(row["period_end"])
                    or fact_number(metadata.get("value")) != value
                    or metadata.get("period_start") and (frequency == "instant" or duration_frequency(metadata["period_start"], metadata["period_end"]) != "quarterly")):
                return None
        else:
            metadata = {"subject": ticker, "metric": metric, "unit": currency, "frequency": frequency,
                        "period_start": None if frequency == "instant" else row.get("period_start"), "period_end": row["period_end"], "source": "sec_companyfacts",
                        "source_url": row.get("source_url")}
        return {**metadata, "value": value}

    formulas = {
        "gross_margin_pct": ("gross_profit", "revenue"),
        "operating_margin_pct": ("operating_income", "revenue"),
        "net_margin_pct": ("net_income", "revenue"),
        "operating_cash_flow_to_net_income_pct": ("operating_cash_flow", "net_income"),
        "free_cash_flow_margin_pct": ("free_cash_flow", "revenue"),
        "liabilities_to_assets_pct": ("total_liabilities", "total_assets"),
        "capital_expenditures_to_revenue_pct": ("capital_expenditures", "revenue"),
    }
    result = {"ticker": ticker, "period_end": fact_date(latest["period_end"]), "currency": currency, "frequency": "quarterly"}
    calculations, gaps = [], {}
    for metric, (numerator_name, denominator_name) in formulas.items():
        numerator, denominator = fact(latest, numerator_name), fact(latest, denominator_name)
        result[metric] = None
        if numerator is None or denominator is None:
            gaps[metric] = "missing_or_incompatible_fact"
            continue
        if denominator["value"] <= 0:
            gaps[metric] = "non_positive_denominator"
            continue
        if numerator.get("period_start") != denominator.get("period_start"):
            gaps[metric] = "period_start_mismatch"
            continue
        value = fact_number(numerator["value"] / denominator["value"] * 100)
        if value is None:
            gaps[metric] = "non_finite_ratio"
            continue
        result[metric] = value
        calculations.append({"metric": metric, "value": value, "unit": "%", "period_end": result["period_end"],
            "formula": f"{numerator_name}/{denominator_name}*100", "derivation_inputs": [numerator, denominator]})

    key = "net_income_less_operating_income_margin_pp"
    net, operating, revenue = (fact(latest, metric) for metric in ("net_income", "operating_income", "revenue"))
    result[key] = None
    if (all(item is not None for item in (net, operating, revenue)) and revenue["value"] > 0
            and len({item.get("period_start") for item in (net, operating, revenue)}) == 1):
        result[key] = fact_number((net["value"] - operating["value"]) / revenue["value"] * 100)
        if result[key] is not None:
            calculations.append({"metric": key, "value": result[key], "unit": "pp", "period_end": result["period_end"],
                "formula": "(net_income-operating_income)/revenue*100", "derivation_inputs": [net, operating, revenue]})
    if result[key] is None:
        gaps[key] = "missing_or_incompatible_fact"

    key = "long_term_debt_less_cash_amount"
    debt, cash = fact(latest, "long_term_debt"), fact(latest, "cash_and_equivalents")
    result[key] = None
    if debt is not None and cash is not None and debt.get("period_start") == cash.get("period_start"):
        result[key] = fact_number(debt["value"] - cash["value"])
        if result[key] is not None:
            calculations.append({"metric": key, "value": result[key], "unit": currency, "period_end": result["period_end"],
                "formula": "long_term_debt-cash_and_equivalents", "derivation_inputs": [debt, cash],
                "basis": "仅长期债务减现金及等价物；不含短期债务、商业票据等，不代表总净债务。"})
    if result[key] is None:
        gaps[key] = "missing_or_incompatible_fact"

    for metric in ("revenue", "net_income"):
        current = fact(latest, metric)
        for suffix, baseline in (("qoq", "previous_period"), ("yoy", "year_ago")):
            key = f"{metric}_{suffix}_pct"
            result[key] = None
            candidates = []
            if current is not None:
                for previous_row in periods:
                    if previous_row["period_end"] >= latest["period_end"]:
                        continue
                    previous = fact(previous_row, metric)
                    if previous is not None and (change := calculate_period_change(current, previous, operation="growth_rate", baseline=baseline)) is not None:
                        candidates.append(change)
            if len(candidates) != 1:
                gaps[key] = "comparable_positive_baseline_unavailable" if not candidates else "ambiguous_baseline"
                continue
            change = candidates[0]
            result[key] = change["value"] * 100
            result[f"{metric}_{suffix}_baseline_period_end"] = change["derivation_inputs"][1]["period_end"]
            calculations.append({**change, "metric": key, "value": result[key], "unit": "%",
                                 "formula": "(current/previous-1)*100"})

    if not calculations:
        return {"status": "unavailable", "error": "financial_ratios_unavailable", "metric_gaps": gaps,
                "summary": "当前单季事实缺少可计算的同口径分子和正分母，未生成比率。"}
    return {"rows": [result], "calculations": calculations, "metric_gaps": gaps,
            "financial_context": {key: deepcopy(value) for key, value in latest.items()
                                  if key != "fact_metadata" and not isinstance(value, (dict, list))},
            "method": {"kind": "financial_ratios", "unit": "%", "frequency": "quarterly",
                       "growth_baseline": "相邻单季或约一年前同季度，单位、会计概念与区间长度一致且基数为正"},
            "limitations": ["仅计算已披露单季事实；缺失比率保留空值，不推算单季年化、未来 EPS 或 PEG。",
                            "净利与营业利润率差额不单独归因于非经营收益或税费；长期债务减现金及等价物不代表总净债务。"]}
