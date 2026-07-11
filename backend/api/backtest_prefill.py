from __future__ import annotations

from datetime import date, datetime
from typing import Any


_BULLISH_VALUES = {
    "bull",
    "bullish",
    "buy",
    "strong buy",
    "strong_buy",
    "outperform",
    "overweight",
    "positive",
    "买入",
    "强烈买入",
    "增持",
    "看多",
}
_BEARISH_VALUES = {
    "bear",
    "bearish",
    "sell",
    "strong sell",
    "strong_sell",
    "underperform",
    "underweight",
    "negative",
    "卖出",
    "强烈卖出",
    "减持",
    "看空",
}
_NEUTRAL_VALUES = {"neutral", "hold", "market perform", "equal weight", "中性", "持有", "观望"}


def _clean_tickers(report: dict[str, Any]) -> list[str]:
    candidates: list[Any] = []
    for key in ("tickers", "ticker", "symbols", "symbol"):
        value = report.get(key)
        candidates.extend(value if isinstance(value, list) else [value])

    subject = report.get("subject")
    if isinstance(subject, dict):
        value = subject.get("tickers") or subject.get("ticker")
        candidates.extend(value if isinstance(value, list) else [value])

    output: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        ticker = str(value or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        output.append(ticker)
    return output


def _extract_stance(report: dict[str, Any]) -> str | None:
    # recommendation/rating 比 report builder 的默认 neutral sentiment 更能代表最终投资观点。
    for key in ("stance", "recommendation", "rating", "sentiment"):
        value = str(report.get(key) or "").strip()
        if value:
            return value
    return None


def _parse_report_date(value: Any) -> date:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("report generated_at is required")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError("report generated_at is invalid") from exc


def _one_year_before(value: date) -> date:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(year=value.year - 1, day=28)


def _strategy_for_stance(stance: str | None) -> tuple[str, list[str]]:
    if stance is None:
        return "buy_and_hold", ["报告缺少明确观点，已默认使用买入并持有策略"]
    normalized = stance.strip().lower().replace("-", " ")
    if normalized in _BULLISH_VALUES:
        return "buy_and_hold", []
    if normalized in _BEARISH_VALUES or normalized in _NEUTRAL_VALUES:
        return "ma_cross", []
    return "buy_and_hold", [f"无法识别报告观点“{stance}”，已默认使用买入并持有策略"]


def build_backtest_prefill(report: dict[str, Any]) -> dict[str, Any]:
    """从已存档报告生成确定性的回测预填配置，不调用 LLM。"""
    if not isinstance(report, dict):
        raise ValueError("report is required")

    tickers = _clean_tickers(report)
    if not tickers:
        raise ValueError("report ticker is required")

    report_date = _parse_report_date(report.get("generated_at"))
    stance = _extract_stance(report)
    strategy, warnings = _strategy_for_stance(stance)
    title = str(report.get("title") or report.get("report_id") or "未命名报告").strip()
    stance_label = stance or "未提供"

    return {
        "config": {
            "tickers": tickers,
            "strategy": strategy,
            "start": _one_year_before(report_date).isoformat(),
            "end": report_date.isoformat(),
            "rationale": f"由报告《{title}》生成：主标的 {', '.join(tickers)}，观点 {stance_label}",
        },
        "warnings": warnings,
    }


__all__ = ["build_backtest_prefill"]
