"""隔离作业可导入的纯 DataFrame 数学；不读取文件、网络或业务运行状态。

函数返回可直接赋给 result 的 JSON 对象：rows、method、units，以及样本统计。
比例使用 ratio（0.05 表示 5%）；compare_series 的累计涨跌使用 %（5 表示 5%）。
"""
from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

if __package__:
    from .financial_math import fact_number, financial_ratios_from_rows
else:
    from financial_math import fact_number, financial_ratios_from_rows


def valuation_scenarios(eps: float, multiples=(20, 30, 40), *, currency: str = "unknown") -> dict:
    """显式 EPS 与市盈率假设；不读取报价，不年化，不生成目标价事实。"""
    eps = fact_number(eps)
    multiples = list(multiples)
    if eps is None or eps <= 0 or len(multiples) > 20:
        raise ValueError("invalid_valuation_assumptions")
    scenarios = []
    for multiple in multiples:
        multiple = fact_number(multiple)
        price = fact_number(eps * multiple) if multiple is not None else None
        if multiple is None or multiple <= 0 or price is None:
            raise ValueError("invalid_valuation_assumptions")
        # 旧公开入口没有 current_price 参数；不在迁移中扩展报价/收益功能。
        scenarios.append({"multiple": multiple, "eps": eps, "scenario_price": price, "return_pct": None})
    return {"rows": scenarios,
            "units": {"multiple": "multiple", "eps": currency + "/share" if currency != "unknown" else "unknown",
                      "scenario_price": currency, "return_pct": "ratio"},
            "method": {"formula": "EPS × PE", "kind": "assumption", "currency": currency,
                       "eps_basis": "explicit_assumption"},
            "limitations": ["情景倍数为假设，不是已实现价格。"]}


def financial_ratios(frame: pd.DataFrame) -> dict:
    """只组合已披露同主体单季事实；原币种、期间与每项来源随衍生计算保留。"""
    return financial_ratios_from_rows(_rows(frame))


def _series(frame: pd.DataFrame, value: str, date: str) -> pd.Series:
    if date not in frame or value not in frame:
        raise ValueError("date_and_value_columns_required")
    series = pd.Series(pd.to_numeric(frame[value], errors="coerce").to_numpy(),
                       index=pd.to_datetime(frame[date], errors="coerce", utc=True))
    series = series[~series.index.isna()].sort_index(kind="stable")
    return series[~series.index.duplicated(keep="last")].replace([np.inf, -np.inf], np.nan)


def _rows(frame: pd.DataFrame) -> list[dict]:
    return [{key: value.isoformat() if isinstance(value, pd.Timestamp) else value
             for key, value in row.items()}
            for row in frame.astype(object).where(pd.notna(frame), None).to_dict("records")]


def series_statistics(frame: pd.DataFrame, *, value: str = "close", date: str = "date",
                      latest_n: int | None = None, unit: str = "unknown") -> dict:
    """按日期统计有效值；变化率只在基期为正时计算。"""
    series = _series(frame, value, date)
    valid = series.dropna()
    if latest_n is not None:
        if type(latest_n) is not int or not 2 <= latest_n <= len(valid):
            raise ValueError("latest_n_requires_available_observations")
        valid = valid.tail(latest_n)
    if valid.empty:
        raise ValueError("series_has_no_valid_observations")
    first, last = float(valid.iloc[0]), float(valid.iloc[-1])
    return {"rows": [{"first": first, "last": last, "minimum": float(valid.min()),
                      "maximum": float(valid.max()), "mean": float(valid.mean()),
                      "difference": last - first, "return_ratio": last / first - 1 if first > 0 else None,
                      "observations": len(valid)}],
            "units": {**dict.fromkeys(("first", "last", "minimum", "maximum", "mean", "difference"), unit),
                      "return_ratio": "ratio", "observations": "count"},
            "method": {"kind": "series_statistics", "field": value, "start": valid.index[0].isoformat(),
                       "end": valid.index[-1].isoformat(), "latest_n": latest_n,
                       "return_definition": "last/first-1 when first>0", "missing_values": int(series.isna().sum()),
                       "missing_policy": "exclude_missing_observations_without_imputation"}}


def moving_averages(frame: pd.DataFrame, *, windows=(20, 50, 200), value: str = "close",
                    date: str = "date", unit: str = "unknown") -> dict:
    """简单移动均线需要完整窗口，窗口不足或其中缺值均返回 null。"""
    windows = list(windows)
    if not windows or any(type(window) is not int or window < 1 for window in windows) or len(set(windows)) != len(windows):
        raise ValueError("moving_average_windows_invalid")
    series = _series(frame, value, date)
    result = pd.DataFrame({"date": series.index, value: series.to_numpy()})
    for window in windows:
        result[f"ma{window}"] = series.rolling(window=window, min_periods=window).mean().to_numpy()
    return {"rows": _rows(result), "units": dict.fromkeys([value, *(f"ma{window}" for window in windows)], unit),
            "method": {"kind": "simple_moving_averages", "field": value, "windows": windows,
                       "window_unit": "observations", "min_periods": "full_window",
                       "missing_values": int(series.isna().sum()), "missing_policy": "preserve_without_imputation"}}


def _price_periods(frame, value, date, frequency, latest_period_closed):
    series = _series(frame, value, date)
    series = series.where(series > 0)
    labels = {stamp: stamp for stamp in series.index}
    if frequency == "weekly":
        observations = series.index.to_series().resample("W-FRI").max()
        labels = observations.to_dict()
        series = series.resample("W-FRI").last()
    elif frequency != "daily":
        raise ValueError("analysis_frequency_unsupported")
    if latest_period_closed not in (True, False, None):
        raise ValueError("latest_period_closed_invalid")
    excluded = None
    if latest_period_closed is False and not series.empty:
        excluded = labels[series.index[-1]].isoformat()
        series = series.iloc[:-1]
    return series, labels, {"latest_period_closed": latest_period_closed,
                           "excluded_incomplete_period": excluded,
                           "missing_periods": int(series.isna().sum())}


def _minimum_loss(value):
    threshold = float(value)
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("minimum_loss_requires_ratio_between_zero_and_one")
    return threshold


def consecutive_declines(frame: pd.DataFrame, *, frequency: str = "daily", min_periods: int = 5,
                         minimum_loss: float = 0, value: str = "close", date: str = "date",
                         unit: str = "unknown", latest_period_closed: bool | None = None) -> dict:
    """与旧历史分析相同的最大非重叠连续下跌段，缺失周期会中断序列。"""
    if type(min_periods) is not int or min_periods < 1:
        raise ValueError("min_periods_requires_positive_integer")
    threshold = _minimum_loss(minimum_loss)
    series, labels, completion = _price_periods(frame, value, date, frequency, latest_period_closed)
    returns = series.pct_change(fill_method=None)
    episodes, start = [], None
    for index in range(1, len(series) + 1):
        falling = index < len(series) and returns.iloc[index] < 0
        if falling and start is None:
            start = index
        if not falling and start is not None:
            end = index - 1
            loss = float(series.iloc[end] / series.iloc[start - 1] - 1)
            if end - start + 1 >= min_periods and -loss >= threshold:
                episodes.append({"start": labels[series.index[start]].isoformat(),
                                 "end": labels[series.index[end]].isoformat(), "periods": end - start + 1,
                                 "return_ratio": loss, "ongoing": index == len(series),
                                 "interrupted_by_missing": index < len(series) and bool(pd.isna(series.iloc[index]))})
            start = None
    rows = [{"date": labels[key].isoformat() if pd.notna(labels[key]) else key.isoformat(),
             "close": float(number) if pd.notna(number) else None} for key, number in series.items()]
    return {"rows": rows, "episodes": episodes, "sample_count": len(episodes),
            "completed_sample_count": sum(not item["ongoing"] and not item["interrupted_by_missing"] for item in episodes),
            "units": {"close": unit, "return_ratio": "ratio", "minimum_loss": "ratio", "periods": "count"},
            "method": {"kind": "consecutive_decline_streaks", "frequency": frequency,
                       "min_periods": min_periods, "minimum_loss": threshold,
                       "return_start": "first declining period's previous close",
                       "overlap": "maximal non-overlapping consecutive streaks", "period_label": "last_observation",
                       "missing_policy": "break_streak_without_imputation", **completion},
            "limitations": ["连续下跌区间并非所有峰谷回撤；历史频次不代表未来概率。",
                            "周期是否完成由调用方依据交易日历确认；未提供时保持未知。"]}


def drawdown_episodes(frame: pd.DataFrame, *, minimum_loss: float = 0, value: str = "close",
                      date: str = "date", unit: str = "unknown") -> dict:
    """从前高到恢复前高的峰谷回撤；缺值处断开，不能假定未知区间已恢复。"""
    threshold = _minimum_loss(minimum_loss)
    series = _series(frame, value, date).where(lambda values: values > 0)
    episodes, rows, peak, active = [], [], None, None

    def close_episode(recovery=None, *, ongoing=False, missing=False):
        if active is not None and -active["return_ratio"] >= threshold:
            episodes.append({**active, "recovery_date": recovery, "ongoing": ongoing,
                             "interrupted_by_missing": missing})

    for stamp, number in series.items():
        label = stamp.isoformat()
        if pd.isna(number):
            close_episode(missing=True)
            peak, active = None, None
            rows.append({"date": label, "close": None, "drawdown_ratio": None})
            continue
        number = float(number)
        if peak is None or number >= peak[1]:
            close_episode(label)
            peak, active = (label, number), None
            ratio = 0.0
        else:
            ratio = number / peak[1] - 1
            if active is None:
                active = {"peak_date": peak[0], "peak": peak[1], "start": label, "end": label,
                          "trough_date": label, "trough": number, "return_ratio": ratio, "periods": 0}
            active["end"], active["periods"] = label, active["periods"] + 1
            if number < active["trough"]:
                active.update(trough_date=label, trough=number, return_ratio=ratio)
        rows.append({"date": label, "close": number, "drawdown_ratio": ratio})
    close_episode(ongoing=True)
    return {"rows": rows, "episodes": episodes, "sample_count": len(episodes),
            "completed_sample_count": sum(item["recovery_date"] is not None for item in episodes),
            "units": {"close": unit, "peak": unit, "trough": unit, "return_ratio": "ratio",
                      "drawdown_ratio": "ratio", "minimum_loss": "ratio", "periods": "count"},
            "method": {"kind": "peak_to_recovery_drawdown", "minimum_loss": threshold,
                       "definition": "price/previous_peak-1; recovery requires price>=previous_peak",
                       "periods_definition": "observations below peak, excluding peak and recovery",
                       "missing_values": int(series.isna().sum()), "missing_policy": "break_episode_without_imputation"}}


def compare_series(frames: Mapping[str, pd.DataFrame], *, value: str = "close", date: str = "date",
                    metadata: Mapping[str, dict] | None = None) -> dict:
    """按共同日期比较累计价格涨跌；元数据可从 DataFrame.attrs 或 metadata 显式传入。"""
    if not 2 <= len(frames) <= 6:
        raise ValueError("comparison_requires_two_to_six_series")
    metadata = metadata or {}
    items, normalized, contexts = [], [], []
    for index, (name, frame) in enumerate(frames.items()):
        field = f"series_{index + 1}"
        series = _series(frame, value, date).dropna()
        normalized.append(pd.DataFrame({"date": series.index.strftime("%Y-%m-%d"), field: series.to_numpy()})
                          .drop_duplicates("date", keep="last"))
        items.append({"field": field, "name": name, "unit": "%"})
        contexts.append({**frame.attrs, **metadata.get(name, {})})
    basis = {}
    for key in ("currency", "price_basis", "dividends_included"):
        known = {item.get(key) for item in contexts if item.get(key) is not None and item.get(key) != "unknown"}
        if len(known) > 1:
            raise ValueError("comparison_basis_mismatch")
        basis[key] = next(iter(known)) if known and all(item.get(key) in known for item in contexts) else None if key == "dividends_included" else "unknown"
    merged = normalized[0]
    for other in normalized[1:]:
        merged = merged.merge(other, on="date", how="inner", validate="one_to_one")
    if len(merged) < 2:
        raise ValueError("comparison_common_dates_missing")
    for item in items:
        field = item["field"]
        base = float(merged[field].iloc[0])
        if base <= 0:
            raise ValueError("comparison_base_must_be_positive")
        merged[field] = (merged[field] / base - 1) * 100
    rows = _rows(merged)
    leaders = merged[[item["field"] for item in items]].max(axis=1)
    tied = merged[[item["field"] for item in items]].eq(leaders, axis=0).sum(axis=1) > 1
    crossovers = []
    for index, left in enumerate(items):
        for right in items[index + 1:]:
            previous, dates = None, []
            for row in rows:
                difference = row[left["field"]] - row[right["field"]]
                sign = 1 if difference > 0 else -1 if difference < 0 else 0
                if not sign:
                    continue
                if previous is not None and sign != previous:
                    dates.append(row["date"])
                previous = sign
            crossovers.append({"left": left["name"], "right": right["name"], "count": len(dates), "dates": dates})
    return {"rows": rows, "series": items, "units": dict.fromkeys((item["field"] for item in items), "%"),
            "comparison_stats": {"observations": len(merged), "crossovers": crossovers,
                "lead_days": {**{item["name"]: int((merged[item["field"]].eq(leaders) & ~tied).sum()) for item in items}, "tie": int(tied.sum())},
                "series": {item["name"]: {"declining_periods": int((merged[item["field"]].diff() < 0).sum()),
                    "negative_return_periods": int((merged[item["field"]] < 0).sum()),
                    "end_return_pct": float(merged[item["field"]].iloc[-1])} for item in items},
                "strictly_increasing": {item["name"]: bool((merged[item["field"]].diff().iloc[1:] > 0).all()) for item in items}},
            "method": {"kind": "price_return_comparison", "date_join": "intersection",
                       "baseline_date": rows[0]["date"], "end_date": rows[-1]["date"], "base_value": 0,
                       "unit": "%", "missing_policy": "common_valid_dates_without_imputation",
                       "crossover_definition": "领先方交换；基准日首次分离不计，中间持平不重置原领先方。", **basis},
            "limitations": ["只比较所提供价格的涨跌，未知的复权或股息口径不当作总回报。"]}
