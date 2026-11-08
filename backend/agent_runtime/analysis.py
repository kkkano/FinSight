"""确定性分析与声明式图形；开放代码只提交给独立隔离 worker。"""
from __future__ import annotations

import hashlib
import math
import os
from copy import deepcopy
from typing import Any

import httpx

from .context import dumps
from .data import DatasetRowsError, RunData


def analyze_dataset(data: RunData, dataset_ref: str, operation: str, parameters: dict | None = None) -> dict:
    import pandas as pd
    parameters = parameters or {}
    if dataset_ref not in data.records:
        raise ValueError("dataset_not_found_in_this_run")
    supported = ["series_statistics", "historical_drawdown_episodes", "valuation_scenarios", "indexed_comparison", "financial_ratios"]
    if operation not in supported:
        return {"status": "unavailable", "error": "analysis_operation_unsupported",
                "summary": "当前确定性分析不支持该操作，请从 supported_operations 选择。",
                "supported_operations": supported}
    parameter_names = {
        "series_statistics": {"table", "value", "date", "latest_n"},
        "historical_drawdown_episodes": {"frequency", "min_periods", "minimum_loss", "value", "date", "table"},
        "valuation_scenarios": {"eps", "multiples", "currency"},
        "indexed_comparison": {"value", "date", "table", "other_dataset_refs"},
        "financial_ratios": {"table", "other_dataset_refs"},
    }
    unknown = set(parameters) - parameter_names[operation]
    if unknown:
        return {"status": "unavailable", "error": "analysis_parameters_invalid",
                "summary": "这项计算不支持参数：" + "、".join(sorted(unknown)) + "。连续下跌的期数用min_periods，累计跌幅比例用minimum_loss（0.05表示5%）。",
                "supported_parameters": sorted(parameter_names[operation])}
    # 估值情景的 EPS 是显式假设；资料引用仍需有效，但不要求来源恰好是行表。
    if operation != "valuation_scenarios":
        try:
            rows = data.rows(dataset_ref, table=parameters.get("table"))
        except DatasetRowsError as exc:
            return {"status": "unavailable", "error": str(exc), "summary": exc.summary, **exc.details}
        if not rows:
            return {"status": "unavailable", "error": "dataset_has_no_rows",
                    "summary": "该资料或所选数据表没有可分析的行，请回读资料并选择有数据的表。"}
        frame = pd.DataFrame(rows)
    if operation == "series_statistics":
        date_key = parameters.get("date") or next((key for key in ("date", "time", "datetime", "timestamp", "period_end") if key in frame), None)
        value_key = parameters.get("value", "close")
        if not date_key or date_key not in frame or value_key not in frame:
            return {"status": "unavailable", "error": "comparison_columns_missing", "summary": "请指定资料中实际的日期列和数值列。", "available_columns": list(frame.columns)}
        values = pd.to_numeric(frame[value_key], errors="coerce")
        dates = pd.to_datetime(frame[date_key], errors="coerce", utc=True)
        valid = pd.DataFrame({"date": dates, "value": values}).dropna().sort_values("date")
        latest_n = parameters.get("latest_n")
        if latest_n is not None:
            if type(latest_n) is not int or latest_n < 2 or latest_n > len(valid):
                return {"status": "unavailable", "error": "analysis_parameters_invalid",
                        "summary": "latest_n需要至少2个有效观测，且不能超过这份资料的有效观测数。"}
            valid = valid.tail(latest_n)
        if valid.empty:
            raise ValueError("dataset_has_no_rows")
        first, last = float(valid["value"].iloc[0]), float(valid["value"].iloc[-1])
        change = last / first - 1 if first > 0 else None
        output = {"summary": f"{len(valid)} 个观测 · 起点 {first:g}→终点 {last:g}" + (f" · 变化 {change:+.2%}" if change is not None else " · 基期非正，未计算变化率"),
                  "rows": [{"first": first, "last": last, "minimum": float(valid["value"].min()), "maximum": float(valid["value"].max()),
                            "mean": float(valid["value"].mean()), "difference": last - first,
                            "return_ratio": change, "observations": len(valid)}],
                  "method": {"kind": "series_statistics", "field": value_key, "start": valid["date"].iloc[0].isoformat(),
                             "end": valid["date"].iloc[-1].isoformat(), "latest_n": latest_n,
                             "return_definition": "last/first-1 when first>0"}}
    elif operation == "historical_drawdown_episodes":
        date_key = parameters.get("date") or next((key for key in ("date", "time", "datetime", "timestamp") if key in frame), None)
        close_key = parameters.get("value") or next((key for key in ("close", "Close", "price", "value") if key in frame), None)
        if not date_key or not close_key or date_key not in frame or close_key not in frame:
            raise ValueError("date_and_close_required")
        series = pd.Series(pd.to_numeric(frame[close_key], errors="coerce").to_numpy(),
                           index=pd.to_datetime(frame[date_key], utc=True, errors="coerce")).dropna()
        series = series[~series.index.isna()].sort_index()
        series = series[~series.index.duplicated(keep="last")]
        frequency = parameters.get("frequency", "weekly")
        labels = {stamp: stamp for stamp in series.index}
        period_completion = {"latest_period_closed": None, "excluded_incomplete_period": None}
        if frequency == "weekly":
            observations = series.index.to_series().resample("W-FRI").max()
            series = series.resample("W-FRI").last()
            labels = observations.to_dict()
            original = data.records[dataset_ref].get("output") or {}
            asset = original.get("asset") or {} if isinstance(original, dict) else {}
            observed = original.get("observed_at") if isinstance(original, dict) else None
            calendar_name = asset.get("calendar_name")
            if calendar_name and observed and not series.empty:
                import pandas_market_calendars as mcal
                last_label = labels[series.index[-1]]
                start = last_label.date() - pd.Timedelta(days=last_label.weekday())
                schedule = mcal.get_calendar(calendar_name).schedule(start_date=start, end_date=start + pd.Timedelta(days=6))
                if not schedule.empty:
                    close = schedule.iloc[-1]["market_close"]
                    clock = pd.to_datetime(observed, utc=True)
                    closed = bool(clock >= close)
                    period_completion.update(latest_period_closed=closed, latest_period_label=last_label.isoformat(),
                                             latest_period_close=close.isoformat(), observed_at=str(observed))
                    if not closed:
                        period_completion["excluded_incomplete_period"] = last_label.isoformat()
                        series = series.iloc[:-1]
        elif frequency != "daily":
            raise ValueError("analysis_frequency_unsupported")
        minimum = max(1, min(52, int(parameters.get("min_periods", 5))))
        threshold = abs(float(parameters.get("minimum_loss", .0)))
        if not math.isfinite(threshold) or threshold > 1:
            return {"status": "unavailable", "error": "analysis_parameters_invalid",
                    "summary": "minimum_loss必须是0到1之间的跌幅比例，例如5%应传0.05，不能传5。"}
        returns = series.pct_change(fill_method=None)
        episodes, start = [], None
        for index in range(1, len(series) + 1):
            falling = index < len(series) and returns.iloc[index] < 0
            if falling and start is None:
                start = index
            if not falling and start is not None:
                end = index - 1
                loss = float(series.iloc[end] / series.iloc[start - 1] - 1)
                if end - start + 1 >= minimum and -loss >= threshold:
                    episodes.append({"start": labels[series.index[start]].isoformat(), "end": labels[series.index[end]].isoformat(),
                                     "periods": end - start + 1, "return_pct": loss,
                                     "ongoing": index == len(series)})
                start = None
        output = {"rows": [{"date": labels[key].isoformat(), "close": float(value)} for key, value in series.items() if pd.notna(value)],
                  "episodes": episodes, "sample_count": len(episodes),
                  "completed_sample_count": sum(not episode["ongoing"] for episode in episodes),
                  "method": {"kind": "consecutive_decline_streaks", "frequency": frequency, "min_periods": minimum, "minimum_loss": threshold,
                             "definition": "相邻收盘价连续下跌的最大区间，并非所有超过阈值的峰谷回撤", "minimum_loss_unit": "ratio",
                             "return_start": "first declining period's previous close",
                             "overlap": "maximal non-overlapping consecutive streaks",
                             "period_label": "last_observation", "missing_periods": int(series.isna().sum()),
                             "period_label_note": "日期沿用供应商观测标签，不一定是该周收盘日；周线可能以周一标记。",
                             "ongoing_definition": "连续下跌区间延伸到样本末尾，尚无后续上涨或持平使其结束；不表示末根周线未收盘。",
                             **period_completion},
                  "limitations": ["历史类比不构成未来概率；最新未完成周期需按数据来源核验。"]}
    elif operation == "valuation_scenarios":
        eps = float(parameters["eps"])
        multiples = parameters.get("multiples", [20, 30, 40])
        if not math.isfinite(eps) or eps <= 0 or len(multiples) > 20:
            raise ValueError("invalid_valuation_assumptions")
        current = parameters.get("current_price")
        scenarios = []
        for multiple in multiples:
            multiple = float(multiple)
            if not math.isfinite(multiple) or multiple <= 0:
                raise ValueError("invalid_valuation_assumptions")
            price = eps * multiple
            scenarios.append({"multiple": multiple, "eps": eps, "scenario_price": price,
                              "return_pct": price / float(current) - 1 if current and float(current) > 0 else None})
        output = {"rows": scenarios, "method": {"formula": "EPS × PE", "kind": "assumption",
                                                "currency": parameters.get("currency", "unknown")},
                  "limitations": ["情景倍数为假设，不是已实现价格。"]}
    elif operation == "financial_ratios":
        output = _financial_ratios(rows)
        if output.get("status") == "unavailable":
            return output
        other_refs = parameters.get("other_dataset_refs") or []
        if (not isinstance(other_refs, list) or len(other_refs) > 4 or any(not isinstance(ref, str) for ref in other_refs)
                or len(set(other_refs)) != len(other_refs) or dataset_ref in other_refs):
            return {"status": "unavailable", "error": "financial_market_context_invalid",
                    "summary": "附加资料必须是不同的本轮报价或公司信息引用。"}
        market_context = []
        for other_ref in other_refs:
            record = data.records.get(other_ref, {})
            if (record.get("status") != "success" or record.get("tool") not in {"get_company_info", "get_stock_price"}
                    or str(record.get("inputs", {}).get("ticker", "")).upper() != str(output["rows"][0]["ticker"]).upper()):
                return {"status": "unavailable", "error": "financial_market_context_invalid",
                        "summary": "附加资料只能引用同一标的已成功取得的报价或公司信息。"}
            market_context.append({"tool": record["tool"], "data_ref": other_ref, "output": deepcopy(record["output"])})
        if market_context:
            output["market_context"] = market_context
    elif operation == "indexed_comparison":
        other_refs = parameters.get("other_dataset_refs") or []
        if other_refs:
            return _compare_datasets(data, [dataset_ref, *other_refs], parameters)
        value = parameters.get("value", "close")
        date_key = parameters.get("date", "date")
        if value not in frame or date_key not in frame:
            return {"status": "unavailable", "error": "comparison_columns_missing",
                    "summary": "请用 parameters.value 指定数值列、parameters.date 指定期间列；保留原始字段名。",
                    "required_parameters": ["value", "date"], "available_columns": list(frame.columns)}
        numeric = pd.to_numeric(frame[value], errors="coerce")
        valid = frame[numeric.notna()].copy()
        values = numeric.dropna()
        if values.empty or values.iloc[0] == 0:
            raise ValueError("comparison_base_missing")
        valid["indexed"] = values.to_numpy() / values.iloc[0] * 100
        output = {"rows": valid.to_dict("records"), "method": {"base": 100, "field": value, "date_field": date_key,
                                                              "table": parameters.get("table"), "input_order": "preserved"},
                  "limitations": ["跨标的比较应使用相同时间、币种与复权口径。"]}
    inputs = {"dataset_ref": dataset_ref, "operation": operation, **parameters}
    if operation == "financial_ratios":
        inputs["dataset_refs"] = [dataset_ref, *(parameters.get("other_dataset_refs") or [])]
    ref = data.record("analyze_dataset", inputs, output)
    return {"status": "ok", "data_refs": [ref], "summary": str(output.get("sample_count", len(output["rows"]))) + " 个分析结果",
            **output}


def _financial_ratios(rows: list[dict]) -> dict:
    """仅对同主体、同财期、同货币的 SEC 单季事实计算，不年化或预测。"""
    from backend.tools.financial_facts import fact_date, fact_number, duration_frequency
    from backend.tools.financial_calculations import calculate_period_change

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
        frequency = "instant" if metric in {"total_assets", "total_liabilities"} else "quarterly"
        if isinstance(metadata, dict):
            if (metadata.get("subject") != ticker or metadata.get("unit") != currency
                    or metadata.get("frequency") != frequency or fact_date(metadata.get("period_end")) != fact_date(row["period_end"])
                    or fact_number(metadata.get("value")) != value
                    or metadata.get("period_start") and (frequency == "instant" or duration_frequency(metadata["period_start"], metadata["period_end"]) != "quarterly")):
                return None
        else:
            metadata = {"subject": ticker, "metric": metric, "unit": currency, "frequency": frequency,
                        "period_start": row.get("period_start"), "period_end": row["period_end"], "source": "sec_companyfacts",
                        "source_url": row.get("source_url")}
        return {**metadata, "value": value}

    formulas = {
        "gross_margin_pct": ("gross_profit", "revenue"),
        "operating_margin_pct": ("operating_income", "revenue"),
        "net_margin_pct": ("net_income", "revenue"),
        "operating_cash_flow_to_net_income_pct": ("operating_cash_flow", "net_income"),
        "free_cash_flow_margin_pct": ("free_cash_flow", "revenue"),
        "liabilities_to_assets_pct": ("total_liabilities", "total_assets"),
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
            "method": {"kind": "financial_ratios", "unit": "%", "frequency": "quarterly",
                       "growth_baseline": "相邻单季或约一年前同季度，单位、会计概念与区间长度一致且基数为正"},
            "limitations": ["仅计算已披露单季事实；缺失比率保留空值，不推算单季年化、未来 EPS 或 PEG。"]}


def comparison_crossovers(rows: list[dict], series: list[dict], date_key: str = "date") -> list[dict]:
    """纯计算：初次分离不计交叉，平局不会重置上个领先方。"""
    crossovers = []
    for left_index, left in enumerate(series):
        for right in series[left_index + 1:]:
            dates, previous_sign = [], None
            for row in rows:
                a, b = row.get(left["field"]), row.get(right["field"])
                if type(a) not in (int, float) or type(b) not in (int, float) or not math.isfinite(a) or not math.isfinite(b):
                    continue
                sign = 1 if a > b else -1 if a < b else 0
                if not sign:
                    continue
                if previous_sign is not None and sign != previous_sign:
                    dates.append(row[date_key])
                previous_sign = sign
            crossovers.append({"left": left["name"], "right": right["name"], "count": len(dates),
                               "dates": dates[-24:], "dates_truncated": len(dates) > 24})
    return crossovers


def _compare_datasets(data: RunData, refs: list[str], parameters: dict) -> dict:
    import pandas as pd
    if len(refs) > 6 or len(set(refs)) != len(refs):
        raise ValueError("comparison_requires_unique_datasets")
    frames, series, currencies, bases, dividends = [], [], [], [], []
    for index, ref in enumerate(refs):
        if ref not in data.records:
            raise ValueError("dataset_not_found_in_this_run")
        record = data.records[ref]
        output = record["output"] if isinstance(record["output"], dict) else {}
        ticker = record.get("inputs", {}).get("ticker") or output.get("ticker")
        if not ticker:
            raise ValueError("comparison_ticker_required")
        rows = data.rows(ref)
        frame = pd.DataFrame(rows)
        date_key = next((key for key in (parameters.get("date"), "date", "time", "datetime") if key and key in frame), None)
        field = parameters.get("value", "close")
        if date_key is None or field not in frame:
            raise ValueError("date_and_close_required")
        frame = frame.assign(date=pd.to_datetime(frame[date_key], utc=True, errors="coerce").dt.strftime("%Y-%m-%d"),
                             value=pd.to_numeric(frame[field], errors="coerce"))[["date", "value"]].dropna()
        frame = frame.drop_duplicates("date").sort_values("date")
        key = "series_" + str(index + 1)
        frames.append(frame.rename(columns={"value": key}))
        series.append({"field": key, "name": str(ticker), "unit": "%"})
        currencies.append(output.get("currency"))
        bases.append(output.get("price_basis"))
        dividends.append(output.get("dividends_included"))
    if len(set(item for item in currencies if item)) > 1 or len(set(item for item in bases if item)) > 1 or len(set(item for item in dividends if item is not None)) > 1:
        return {"status": "unavailable", "error": "comparison_basis_mismatch", "summary": "标的币种或价格复权口径不同，不能直接合并比较。"}
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on="date", how="inner", validate="one_to_one")
    if len(merged) < 2:
        raise ValueError("comparison_common_dates_missing")
    totals = []
    for item in series:
        field = item["field"]
        base = float(merged[field].iloc[0])
        if base <= 0:
            raise ValueError("comparison_base_missing")
        merged[field] = (merged[field] / base - 1) * 100
        totals.append(f"{item['name']} {float(merged[field].iloc[-1]):+.2f}%")
    result = {"summary": " · ".join(totals), "rows": merged.to_dict("records"), "series": series,
              "method": {"kind": "price_return_comparison", "date_join": "intersection", "baseline_date": merged['date'].iloc[0],
                         "end_date": merged['date'].iloc[-1], "base_value": 0, "unit": "%", "price_basis": bases[0] if all(bases) else "unknown",
                         "currency": currencies[0] if all(currencies) else "unknown", "dividends_included": dividends[0] if all(item is not None for item in dividends) else None},
              "limitations": ["按共同日期比较所提供价格的涨跌；复权和股息调整未全部提供时保持未知，不冒充总回报。"]}
    leaders = merged[[item["field"] for item in series]].max(axis=1)
    tied = merged[[item["field"] for item in series]].eq(leaders, axis=0).sum(axis=1) > 1
    result["comparison_stats"] = {
        "observations": len(merged),
        "series": {item["name"]: {
            "declining_periods": int((merged[item["field"]].diff() < 0).sum()),
            "negative_return_periods": int((merged[item["field"]] < 0).sum()),
            "end_return_pct": float(merged[item["field"]].iloc[-1]),
        } for item in series},
        "lead_days": {**{item["name"]: int((merged[item["field"]].eq(leaders) & ~tied).sum()) for item in series}, "tie": int(tied.sum())},
        "strictly_increasing": {item["name"]: bool((merged[item["field"]].diff().iloc[1:] > 0).all()) for item in series},
    }
    result["comparison_stats"]["crossovers"] = comparison_crossovers(result["rows"], series)
    result["method"]["crossover_definition"] = "两条累计涨跌曲线的领先方发生交换；基准日持平后的首次分离不计，中间持平后原领先方不变也不计。日期为新领先方首次出现的观测日。"
    ref = data.record("analyze_dataset", {"dataset_ref": refs[0], "dataset_refs": refs, "operation": "indexed_comparison"}, result)
    return {"status": "ok", "data_refs": [ref], **result}


def render_chart(data: RunData, dataset_ref: str, title: str, chart_type: str,
                 x: str, series: list[dict], scale: str = "linear", annotations: list | None = None, table: str | None = None) -> dict:
    if chart_type not in {"line", "bar", "scatter", "candlestick", "line_with_event_windows"}:
        raise ValueError("chart_type_unsupported")
    rows = data.rows(dataset_ref, table=table)
    if not rows:
        raise ValueError("chart_dataset_empty")
    if len(rows) > 5000 or len(series) > 12:
        raise ValueError("chart_dataset_too_large")
    if scale not in {"linear", "log"} or not series:
        raise ValueError("invalid_chart_spec")
    if chart_type == "candlestick":
        for row in rows:
            values = [row.get(key) for key in ("open", "close", "low", "high")]
            if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
                raise ValueError("candle_input_ohlc_required")
            opening, close, low, high = values
            if not low <= min(opening, close) <= max(opening, close) <= high:
                raise ValueError("candle_ohlc_inconsistent")
    fields = {str(row.get("field") or "") for row in series}
    if not x or any(x not in row for row in rows) or not all(any(field in row for row in rows) for field in fields):
        raise DatasetRowsError("chart_columns_missing", "图表指定的列不存在，请按 available_columns 修改 x 和 series.field。",
                               available_columns=list(dict.fromkeys(key for row in rows[:10] for key in row)))
    normalized_annotations = []
    for annotation in (annotations or [])[:50]:
        annotation = dict(annotation)
        for key in ("start", "end"):
            boundary = annotation.get(key)
            if isinstance(boundary, str) and len(boundary) == 10:
                matches = [row[x] for row in rows if str(row.get(x, ""))[:10] == boundary]
                if not matches:
                    matches = [row[x] for row in rows if (str(row.get(x, ""))[:10] >= boundary if key == "start" else str(row.get(x, ""))[:10] <= boundary)]
                if matches:
                    annotation[key] = matches[0] if key == "start" else matches[-1]
        normalized_annotations.append(annotation)
    spec = {"chart_type": chart_type, "x": x, "table": table, "series": [{"field": str(s["field"]), "name": str(s.get("name") or s["field"]),
             "unit": str(s.get("unit") or "")} for s in series], "scale": scale, "annotations": (annotations or [])[:50]}
    spec["annotations"] = normalized_annotations
    # 仅声明式字段；不能携带 formatter/事件处理器或可执行 JS。
    for row in rows:
        for field in fields:
            number = row.get(field)
            if isinstance(number, (float, int)) and (not math.isfinite(number) or (scale == "log" and number <= 0)):
                raise ValueError("invalid_chart_value")
    coverage = {}
    for field in fields:
        valid_indices = [index for index, row in enumerate(rows)
                         if type(row.get(field)) in (int, float) and math.isfinite(row[field])]
        coverage[field] = {"points": len(rows), "valid": len(valid_indices), "missing": len(rows) - len(valid_indices),
                           "leading_missing": valid_indices[0] if valid_indices else len(rows),
                           "first_valid": rows[valid_indices[0]][x] if valid_indices else None,
                           "last_valid": rows[valid_indices[-1]][x] if valid_indices else None}
    artifact = {"artifact_id": "chart_" + hashlib.sha256(dumps([dataset_ref, spec]).encode()).hexdigest()[:16],
                "version": 1, "kind": "chart", "title": title[:200], "dataset_refs": [dataset_ref],
                "source_refs": data.source_refs(dataset_ref), "spec": spec, "data": {"rows": rows},
                "method": data.records[dataset_ref]["output"].get("method", {}) if isinstance(data.records[dataset_ref]["output"], dict) else {},
                "coverage": coverage,
                "limitations": [f"{next(str(s.get('name') or field) for s in series if s['field'] == field)}有{item['missing']}个缺失点，开头{item['leading_missing']}个点为空；缺值未补成零。"
                                for field, item in coverage.items() if item['missing']]}
    if chart_type == "line_with_event_windows":
        panels = []
        for annotation in normalized_annotations[:6]:
            start, end = annotation.get("start"), annotation.get("end")
            if start is None or end is None:
                continue
            subset = [row for row in rows if str(start) <= str(row.get(x, "")) <= str(end)]
            if subset:
                baseline_included = False
                if artifact["method"].get("kind") == "consecutive_decline_streaks":
                    start_index = next((index for index, row in enumerate(rows) if row is subset[0]), 0)
                    if start_index > 0:
                        subset = [rows[start_index - 1], *subset]
                        baseline_included = True
                has_ohlc = all(all(isinstance(row.get(key), (int, float)) for key in ("open", "close", "low", "high")) for row in subset)
                panels.append({"title": str(annotation.get("label") or f"{start} — {end}"), "rows": subset,
                               "chart_type": "candlestick" if has_ohlc else "line", "baseline_included": baseline_included,
                               "periods": len(subset) - 1 if baseline_included else len(subset)})
        artifact["data"]["panels"] = panels
    if not any(a["artifact_id"] == artifact["artifact_id"] for a in data.artifacts):
        data.artifacts.append(artifact)
    return artifact


async def run_analysis_code(data: RunData, code: str, dataset_refs: list[str], *, timeout: float) -> dict:
    url = os.getenv("FINSIGHT_ANALYSIS_WORKER_URL", "").strip().rstrip("/")
    key = os.getenv("FINSIGHT_ANALYSIS_WORKER_TOKEN", "")
    if not url or not key:
        return {"status": "unavailable", "error": "analysis_worker_unconfigured",
                "summary": "计算服务还没配置好，仍可使用现有的指标和图表。"}
    if len(code) > 16000 or not dataset_refs or len(dataset_refs) > 8:
        raise ValueError("analysis_request_too_large")
    if any(ref not in data.records for ref in dataset_refs):
        raise ValueError("dataset_not_found_in_this_run")
    payload = {"code": code, "datasets": {ref: data.records[ref]["output"] for ref in dataset_refs},
               "timeout_seconds": min(60.0, timeout)}
    async with httpx.AsyncClient(timeout=min(65, timeout), follow_redirects=False) as client:
        response = await client.post(url + "/jobs", json=payload, headers={"Authorization": "Bearer " + key})
        if response.status_code != 200:
            code = {413: "analysis_request_too_large", 429: "analysis_worker_busy", 503: "analysis_worker_unavailable"}.get(response.status_code, "analysis_worker_failed")
            summaries = {413: "数据量有点大，需要分批计算。", 429: "计算服务正在忙，稍后再试。", 503: "计算服务暂时连不上。"}
            return {"status": "error", "error": code, "summary": summaries.get(response.status_code, "这次计算没成功。")}
        result = response.json()
    if result.get("error") == "analysis_result_missing":
        result.update(summary="代码已执行，但还没有返回计算结果。请查看 logs，并把要返回的内容赋给 result；仅 print 不会生成数据表。", retryable=True)
    if result.get("status") == "error" and result.get("code_error"):
        from backend.analysis_worker.protocol import safe_code_error
        detail = safe_code_error(result["code_error"])
        if detail:
            labels = {"KeyError": "计算用到的字段不存在", "NameError": "计算中有未定义的变量", "TypeError": "数据类型不匹配",
                      "ValueError": "数据格式或数值不符合这项计算", "SyntaxError": "计算代码有语法问题",
                      "ZeroDivisionError": "分母为零，无法计算", "MemoryError": "数据量超过计算内存限制"}
            result["summary"] = (f"计算第 {detail['line']} 行出错：" if detail.get("line") else "计算出错：") + labels.get(detail["type"], "代码未能执行完成") + "。"
            result["code_error"] = detail
            result["retryable"] = True
    if result.get("status") == "ok":
        output = result.get("result")
        if isinstance(output, dict):
            output = {**output, "method": {**(output.get("method") if isinstance(output.get("method"), dict) else {}),
                      "kind": "derived", "code": code, "code_hash": hashlib.sha256(code.encode()).hexdigest(),
                      "input_refs": dataset_refs, "input_hash": result.get("input_hash")}}
        ref = data.record("run_analysis_code", {"dataset_refs": dataset_refs,
                          "code_hash": hashlib.sha256(code.encode()).hexdigest()}, output)
        return {**result, "data_refs": [ref]}
    return result

