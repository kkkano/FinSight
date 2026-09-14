# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/report_builder.py（WP3 Task5，零行为变更）。
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from backend.report.util import _safe_str, _sanitize_report_text_block

_PRICE_CLAIM_LABELS: dict[str, str] = {
    "price_momentum": "价格动量",
    "relative_strength": "相对强弱",
    "volume_confirmation": "量价确认",
    "volatility_regime": "波动率结构",
    "key_level_risk": "关键价位风险",
}


def _extract_price_behavior_snapshot(output: dict[str, Any]) -> dict[str, Any] | None:
    evidence = output.get("evidence")
    if not isinstance(evidence, list):
        return None
    for item in evidence:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        snapshot = meta.get("snapshot")
        if isinstance(snapshot, dict) and snapshot.get("snapshot_type") == "PriceBehaviorSnapshot":
            return snapshot
    return None

def _format_price_behavior_snapshot(snapshot: dict[str, Any]) -> str:
    quote = snapshot.get("quote") if isinstance(snapshot.get("quote"), dict) else {}
    trend = snapshot.get("trend") if isinstance(snapshot.get("trend"), dict) else {}
    returns = trend.get("returns") if isinstance(trend.get("returns"), dict) else {}
    momentum = snapshot.get("momentum") if isinstance(snapshot.get("momentum"), dict) else {}
    volume_price = snapshot.get("volume_price") if isinstance(snapshot.get("volume_price"), dict) else {}
    relative_strength = snapshot.get("relative_strength") if isinstance(snapshot.get("relative_strength"), dict) else {}
    benchmarks = relative_strength.get("benchmarks") if isinstance(relative_strength.get("benchmarks"), dict) else {}
    volatility = snapshot.get("volatility_structure") if isinstance(snapshot.get("volatility_structure"), dict) else {}
    key_levels = snapshot.get("key_levels") if isinstance(snapshot.get("key_levels"), dict) else {}
    options = snapshot.get("options") if isinstance(snapshot.get("options"), dict) else {}

    def _fmt_number(value: Any, digits: int = 2) -> str:
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return _safe_str(value).strip() if value is not None else ""

    def _fmt_pct(value: Any, *, signed: bool = True) -> str:
        try:
            prefix = "+" if signed else ""
            return f"{float(value):{prefix}.2f}%"
        except (TypeError, ValueError):
            return _safe_str(value).strip() if value is not None else ""

    def _to_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _add_section(lines: list[str], heading: str, bits: list[str]) -> None:
        clean_bits = [bit for bit in bits if bit]
        if clean_bits:
            lines.append(f"【{heading}】" + "；".join(clean_bits) + "。")

    lines: list[str] = []
    ticker = _safe_str(snapshot.get("ticker") or quote.get("ticker") or "标的").strip()
    price_bits = []
    price = quote.get("price", snapshot.get("price"))
    currency = quote.get("currency", snapshot.get("currency", "USD"))
    price_bits.append(f"{ticker} 当前价格: {currency} {price}" if price is not None else f"{ticker} 当前价格暂缺")
    change_pct = quote.get("change_percent", snapshot.get("change_percent"))
    if change_pct is not None:
        price_bits.append(f"日内变动 {_fmt_pct(change_pct)}")
    if quote.get("source"):
        price_bits.append(f"来源 {quote.get('source')}")
    if quote.get("as_of") or snapshot.get("as_of"):
        price_bits.append(f"时间 {quote.get('as_of') or snapshot.get('as_of')}")
    _add_section(lines, "价格状态", price_bits)

    trend_bits = []
    return_bits = [
        f"{label} {_fmt_pct(returns.get(label))}"
        for label in ("1d", "1w", "1mo", "3mo", "6mo", "1y")
        if returns.get(label) is not None
    ]
    if return_bits:
        trend_bits.append("区间收益 " + " / ".join(return_bits))
    if trend.get("direction"):
        trend_bits.append(f"趋势方向 {trend.get('direction')}")
    if momentum.get("state"):
        trend_bits.append(f"动量状态 {momentum.get('state')}")
    if momentum.get("close_vs_sma20_pct") is not None:
        trend_bits.append(f"相对SMA20 {_fmt_pct(momentum.get('close_vs_sma20_pct'))}")
    _add_section(lines, "趋势与动量", trend_bits)

    volume_bits = []
    if volume_price.get("price_change_1d") is not None:
        volume_bits.append(f"1日价格变动 {_fmt_pct(volume_price.get('price_change_1d'))}")
    if volume_price.get("volume_ratio20") is not None:
        volume_bits.append(f"成交量为20日均量 {_fmt_number(volume_price.get('volume_ratio20'))}x")
    if volume_price.get("signal"):
        volume_bits.append(f"量价信号 {volume_price.get('signal')}")
    _add_section(lines, "量价关系", volume_bits)

    rs_bits = []
    for benchmark in ("SPY", "QQQ"):
        payload = benchmarks.get(benchmark) if isinstance(benchmarks.get(benchmark), dict) else {}
        parts = []
        if payload.get("rs_1mo") is not None:
            parts.append(f"1mo {_fmt_pct(payload.get('rs_1mo')).replace('%', 'pct')}")
        if payload.get("rs_3mo") is not None:
            parts.append(f"3mo {_fmt_pct(payload.get('rs_3mo')).replace('%', 'pct')}")
        if parts:
            rs_bits.append(f"{benchmark}: " + " / ".join(parts))
    _add_section(lines, "相对强弱RS", rs_bits)

    vol_bits = []
    realized_vol = volatility.get("realized_volatility") if isinstance(volatility.get("realized_volatility"), dict) else {}
    for label in ("20d", "60d"):
        if realized_vol.get(label) is not None:
            vol_bits.append(f"实现波动率{label} {_fmt_pct(realized_vol.get(label), signed=False)}")
    if volatility.get("atr14_pct") is not None:
        vol_bits.append(f"ATR14 {_fmt_pct(volatility.get('atr14_pct'), signed=False)}")
    if options.get("iv_atm") is not None:
        try:
            vol_bits.append(f"ATM IV {float(options.get('iv_atm')):.2%}")
        except (TypeError, ValueError):
            vol_bits.append(f"ATM IV {options.get('iv_atm')}")
    if options.get("put_call_ratio") is not None:
        vol_bits.append(f"PCR {_fmt_number(options.get('put_call_ratio'))}")
    _add_section(lines, "波动率与期权结构", vol_bits)

    level_bits = []
    for key, label in (
        ("support_20d", "20日支撑"),
        ("resistance_20d", "20日压力"),
        ("high_52w", "52周高点"),
        ("low_52w", "52周低点"),
    ):
        if key_levels.get(key) is not None:
            level_bits.append(f"{label} {_fmt_number(key_levels.get(key))}")
    if key_levels.get("distance_to_support_20d_pct") is not None:
        level_bits.append(f"距20日支撑 {_fmt_pct(key_levels.get('distance_to_support_20d_pct'))}")
    if key_levels.get("distance_to_resistance_20d_pct") is not None:
        level_bits.append(f"距20日压力 {_fmt_pct(key_levels.get('distance_to_resistance_20d_pct'))}")
    _add_section(lines, "关键价位", level_bits)

    risk_bits = []
    if snapshot.get("fallback_used"):
        risk_bits.append(f"价格数据使用兜底路径，原因: {snapshot.get('fallback_reason') or 'primary_source_unavailable'}")
    volume_signal = _safe_str(volume_price.get("signal") or "")
    volume_ratio = _to_float(volume_price.get("volume_ratio20"))
    if volume_signal == "price_down_distribution":
        risk_bits.append(f"放量下跌信号，成交量约为20日均量 {volume_ratio:.2f}x" if volume_ratio is not None else "放量下跌信号")
    elif volume_signal == "low_volume_move":
        risk_bits.append(f"价格变动缺少量能确认，成交量约为20日均量 {volume_ratio:.2f}x" if volume_ratio is not None else "价格变动缺少量能确认")
    atr_pct = _to_float(volatility.get("atr14_pct"))
    if atr_pct is not None and atr_pct >= 4:
        risk_bits.append(f"ATR14 达 {atr_pct:.2f}%，短线波动风险偏高")
    pcr = _to_float(options.get("put_call_ratio"))
    if pcr is not None and pcr >= 1.2:
        risk_bits.append(f"Put/Call Ratio {pcr:.2f} 偏高，期权端防守需求较强")
    distance_support = _to_float(key_levels.get("distance_to_support_20d_pct"))
    if distance_support is not None and 0 <= distance_support <= 3:
        risk_bits.append(f"价格距20日支撑仅 {distance_support:+.2f}%，跌破后可能触发止损压力")
    event = snapshot.get("event_explanation") if isinstance(snapshot.get("event_explanation"), dict) else {}
    if event.get("summary"):
        risk_bits.append(f"价格异动需结合事件验证: {_safe_str(event.get('summary'))[:180]}")
    elif event.get("todo"):
        risk_bits.append(_safe_str(event.get("todo")))
    _add_section(lines, "风险提示", risk_bits)
    return "\n".join(lines)

def _format_price_agent_claims(output: dict[str, Any]) -> str:
    claims = output.get("claims")
    if not isinstance(claims, list):
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        metadata = claim.get("metadata") if isinstance(claim.get("metadata"), dict) else {}
        claim_type = _safe_str(metadata.get("claim_type") or "").strip()
        if claim_type not in _PRICE_CLAIM_LABELS or claim_type in seen:
            continue
        claim_text = _safe_str(claim.get("claim") or "").strip()
        if not claim_text:
            continue
        seen.add(claim_type)
        lines.append(f"- {_PRICE_CLAIM_LABELS[claim_type]}：{claim_text[:260]}")
    if not lines:
        return ""
    return "【结构化命题】\n" + "\n".join(lines)

def _format_price_agent_report_summary(output: dict[str, Any]) -> str:
    summary = _sanitize_report_text_block(_safe_str(output.get("summary") or ""), max_lines=24, max_chars=3600)
    snapshot = _extract_price_behavior_snapshot(output)
    if snapshot and "【价格状态】" not in summary:
        summary = _format_price_behavior_snapshot(snapshot) or summary
    claims_text = _format_price_agent_claims(output)
    parts = [part for part in (summary, claims_text) if part]
    return "\n".join(parts).strip()


# agent 专属报告摘要格式化注册表（WP3-T5）：消灭"新增 agent 要来 report_builder 加格式化"的隐藏改动点。
# 注意：现网仅 price_agent 有专属格式化；其余走 report_builder 调用点的默认摘要路径（行为保真，
# spec 草图的 list[str] claims 签名与现实不符——实际是整段 summary 字符串，见 Deviations）。
AGENT_REPORT_SUMMARY_FORMATTERS = {
    "price_agent": _format_price_agent_report_summary,
}


def format_agent_report_summary(agent_name: str, output: dict) -> str | None:
    """注册表分发；未登记 agent 返回 None（调用方走默认摘要路径）。"""
    formatter = AGENT_REPORT_SUMMARY_FORMATTERS.get(agent_name)
    if formatter is None or not isinstance(output, dict):
        return None
    return formatter(output)
