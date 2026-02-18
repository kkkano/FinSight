"""
Deterministic scoring logic for Dashboard Insights.

Provides rule-based fallback scores when LLM is unavailable.
Each scorer mirrors the corresponding DigestAgent's domain logic.
"""

from __future__ import annotations

import math
from typing import Any


def _safe_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def clamp_score(value: float) -> float:
    """Clamp score to [1, 10] range, rounded to 1 decimal."""
    return round(max(1.0, min(10.0, value)), 1)


# ---------------------------------------------------------------------------
# Technical scoring
# ---------------------------------------------------------------------------

def score_technical(data: dict[str, Any]) -> tuple[float, str, list[str]]:
    """
    Deterministic technical score from indicator data.

    Returns:
        (score, label, key_points)
    """
    score = 5.0
    points: list[str] = []

    rsi = _safe_get(data, "rsi")
    if isinstance(rsi, (int, float)) and math.isfinite(rsi):
        if 30 < rsi < 70:
            score += 1
            points.append(f"RSI ({rsi:.1f}) 处于正常区间")
        elif rsi >= 70:
            score -= 1
            points.append(f"RSI ({rsi:.1f}) 处于超买区间，注意回调风险")
        else:
            score -= 0.5
            points.append(f"RSI ({rsi:.1f}) 处于超卖区间，可能存在反弹机会")

    trend = _safe_get(data, "trend")
    if trend in ("bullish", "uptrend"):
        score += 2
        points.append("整体趋势偏多")
    elif trend in ("bearish", "downtrend"):
        score -= 1
        points.append("整体趋势偏空")

    ma20 = _safe_get(data, "ma20")
    ma50 = _safe_get(data, "ma50")
    if isinstance(ma20, (int, float)) and isinstance(ma50, (int, float)):
        if ma20 > ma50:
            score += 1
            points.append("MA20/MA50 金叉，短期均线多头排列")
        else:
            score -= 0.5
            points.append("MA20/MA50 死叉，短期均线空头排列")

    macd = _safe_get(data, "macd")
    macd_signal = _safe_get(data, "macd_signal")
    if isinstance(macd, (int, float)) and isinstance(macd_signal, (int, float)):
        if macd > macd_signal:
            score += 1
            points.append("MACD 在信号线上方，动能偏多")

    return clamp_score(score), _label(score), points[:5]


# ---------------------------------------------------------------------------
# Financial scoring
# ---------------------------------------------------------------------------

def score_financial(data: dict[str, Any]) -> tuple[float, str, list[str]]:
    """
    Deterministic financial health score.

    Returns:
        (score, label, key_points)
    """
    score = 4.0
    points: list[str] = []

    # Valuation data may be nested or flat
    pe = _safe_get(data, "trailing_pe") or _safe_get(data, "valuation", "trailing_pe")
    if isinstance(pe, (int, float)) and math.isfinite(pe):
        if 0 < pe < 35:
            score += 2
            comparison = "低于" if pe < 15 else ("高于" if pe > 25 else "接近")
            points.append(f"市盈率 ({pe:.1f}) {comparison}市场平均水平")
        elif pe >= 35:
            points.append(f"市盈率 ({pe:.1f}) 偏高，估值可能较贵")

    # Revenue growth
    revenue_growth = _safe_get(data, "revenue_growth") or _safe_get(
        data, "financials", "revenue_growth"
    )
    if isinstance(revenue_growth, (int, float)) and math.isfinite(revenue_growth):
        if revenue_growth > 0:
            score += 1
            points.append(f"营收同比增长 {revenue_growth:.1%}")
        else:
            score -= 0.5
            points.append(f"营收同比下降 {abs(revenue_growth):.1%}")

    # Net income positive
    net_income = _safe_get(data, "net_income") or _safe_get(
        data, "financials", "net_income"
    )
    if isinstance(net_income, (int, float)):
        if net_income > 0:
            score += 1
            points.append("最近季度净利润为正")
        else:
            score -= 1
            points.append("最近季度净利润为负")

    # Debt to equity
    de_ratio = _safe_get(data, "debt_to_equity") or _safe_get(
        data, "financials", "debt_to_equity"
    )
    if isinstance(de_ratio, (int, float)) and math.isfinite(de_ratio):
        if de_ratio < 0.6:
            score += 1
            points.append(f"资产负债率 ({de_ratio:.2f}) 较低，财务稳健")
        elif de_ratio > 1.5:
            score -= 0.5
            points.append(f"资产负债率 ({de_ratio:.2f}) 偏高")

    # Free cash flow
    fcf = _safe_get(data, "free_cash_flow") or _safe_get(
        data, "financials", "free_cash_flow"
    )
    if isinstance(fcf, (int, float)):
        if fcf > 0:
            score += 1
            points.append("自由现金流为正")

    return clamp_score(score), _label(score), points[:5]


# ---------------------------------------------------------------------------
# News scoring
# ---------------------------------------------------------------------------

def score_news(data: dict[str, Any]) -> tuple[float, str, list[str]]:
    """
    Deterministic news sentiment score based on article counts.

    Returns:
        (score, label, key_points)
    """
    score = 5.0
    points: list[str] = []

    market_news = data.get("market", [])
    impact_news = data.get("impact", [])
    all_news = (market_news if isinstance(market_news, list) else []) + (
        impact_news if isinstance(impact_news, list) else []
    )
    total = len(all_news)

    if total == 0:
        return 5.0, "中性", ["暂无近期新闻数据"]

    # Simple keyword-based sentiment
    positive_keywords = {"surge", "beat", "record", "upgrade", "buy", "bullish", "上涨", "利好", "突破"}
    negative_keywords = {"drop", "miss", "downgrade", "sell", "bearish", "risk", "下跌", "利空", "风险"}

    positive_count = 0
    negative_count = 0
    for item in all_news:
        text = ""
        if isinstance(item, dict):
            text = str(item.get("title", "")) + " " + str(item.get("summary", ""))
        elif isinstance(item, str):
            text = item
        text_lower = text.lower()
        if any(kw in text_lower for kw in positive_keywords):
            positive_count += 1
        if any(kw in text_lower for kw in negative_keywords):
            negative_count += 1

    positive_ratio = positive_count / total if total > 0 else 0
    negative_ratio = negative_count / total if total > 0 else 0

    if positive_ratio > 0.6:
        score += 2
    elif positive_ratio > 0.3:
        score += 1

    if negative_ratio > 0.4:
        score -= 2
    elif negative_ratio > 0.2:
        score -= 1

    points.append(f"近期 {total} 条新闻中，{positive_count} 条正面 / {negative_count} 条负面")

    if positive_ratio > 0.5:
        points.append("新闻情绪整体偏乐观")
    elif negative_ratio > 0.5:
        points.append("新闻情绪整体偏悲观，需关注风险")
    else:
        points.append("新闻情绪中性")

    return clamp_score(score), _label(score), points[:5]


# ---------------------------------------------------------------------------
# Peers scoring
# ---------------------------------------------------------------------------

def score_peers(data: dict[str, Any]) -> tuple[float, str, list[str]]:
    """
    Deterministic peer comparison score.

    Returns:
        (score, label, key_points)
    """
    score = 5.0
    points: list[str] = []

    # Expected shape: {company: {...}, peers: [{...}]}
    company = _safe_get(data, "company") or {}
    peers_list = _safe_get(data, "peers") or []

    if not peers_list:
        return 5.0, "中性", ["暂无同行对比数据"]

    # Compare PE
    company_pe = _safe_get(company, "trailing_pe")
    if isinstance(company_pe, (int, float)) and math.isfinite(company_pe):
        peer_pes = [
            p.get("trailing_pe")
            for p in peers_list
            if isinstance(p.get("trailing_pe"), (int, float))
            and math.isfinite(p["trailing_pe"])
        ]
        if peer_pes:
            avg_pe = sum(peer_pes) / len(peer_pes)
            if company_pe < avg_pe * 0.85:
                score += 1
                points.append(f"PE ({company_pe:.1f}) 低于行业均值 ({avg_pe:.1f})，估值偏低")
            elif company_pe > avg_pe * 1.15:
                score -= 0.5
                points.append(f"PE ({company_pe:.1f}) 高于行业均值 ({avg_pe:.1f})，估值偏高")

    # Compare revenue growth
    company_growth = _safe_get(company, "revenue_growth")
    if isinstance(company_growth, (int, float)):
        peer_growths = [
            p.get("revenue_growth")
            for p in peers_list
            if isinstance(p.get("revenue_growth"), (int, float))
        ]
        if peer_growths:
            avg_growth = sum(peer_growths) / len(peer_growths)
            if company_growth > avg_growth:
                score += 1
                points.append("营收增速高于行业平均水平")
            else:
                score -= 0.5
                points.append("营收增速低于行业平均水平")

    # Compare profit margin
    company_margin = _safe_get(company, "profit_margin")
    if isinstance(company_margin, (int, float)):
        peer_margins = [
            p.get("profit_margin")
            for p in peers_list
            if isinstance(p.get("profit_margin"), (int, float))
        ]
        if peer_margins:
            avg_margin = sum(peer_margins) / len(peer_margins)
            if company_margin > avg_margin:
                score += 1
                points.append("利润率优于行业平均水平")

    if not points:
        points.append(f"与 {len(peers_list)} 家同行进行了对比分析")

    return clamp_score(score), _label(score), points[:5]


# ---------------------------------------------------------------------------
# Overview (composite) scoring
# ---------------------------------------------------------------------------

def score_overview(
    *,
    tech_score: float = 5.0,
    fin_score: float = 5.0,
    news_score: float = 5.0,
    peers_score: float = 5.0,
) -> tuple[float, str, list[str]]:
    """
    Composite overview score from other dimension scores.

    Weights: financial 35%, technical 25%, news 20%, peers 20%.
    """
    weighted = (
        fin_score * 0.35
        + tech_score * 0.25
        + news_score * 0.20
        + peers_score * 0.20
    )
    score = clamp_score(weighted)
    points = [
        f"财务面 {fin_score:.1f} · 技术面 {tech_score:.1f} · 舆情 {news_score:.1f} · 同行 {peers_score:.1f}",
    ]

    if score >= 7:
        points.append("多维度信号共振偏多，整体前景良好")
    elif score <= 3:
        points.append("多维度信号偏空，建议谨慎")
    else:
        points.append("各维度信号存在分歧，整体中性")

    return score, _label(score), points


# ---------------------------------------------------------------------------
# Score breakdown helpers (Phase I - I2)
# ---------------------------------------------------------------------------

def _clip_contribution(value: float, low: float = -5.0, high: float = 5.0) -> float:
    return max(low, min(high, float(value)))


def score_technical_details(
    data: dict[str, Any],
) -> tuple[float, str, list[str], list[dict[str, Any]]]:
    score, label, points = score_technical(data)

    rsi = _safe_get(data, "rsi")
    rsi_signal = 0.0
    if isinstance(rsi, (int, float)) and math.isfinite(rsi):
        if 30 < rsi < 70:
            rsi_signal = 1.0
        elif rsi >= 70:
            rsi_signal = -1.0
        else:
            rsi_signal = -0.5

    trend = str(_safe_get(data, "trend", default="neutral")).lower()
    trend_signal = 1.0 if trend in {"bullish", "uptrend"} else (-1.0 if trend in {"bearish", "downtrend"} else 0.0)

    momentum_signal = 0.0
    ma20 = _safe_get(data, "ma20")
    ma50 = _safe_get(data, "ma50")
    macd = _safe_get(data, "macd")
    macd_signal = _safe_get(data, "macd_signal")
    if isinstance(ma20, (int, float)) and isinstance(ma50, (int, float)):
        momentum_signal += 1.0 if ma20 > ma50 else -0.5
    if isinstance(macd, (int, float)) and isinstance(macd_signal, (int, float)):
        momentum_signal += 0.5 if macd > macd_signal else -0.25

    breakdown = [
        {
            "factor_key": "rsi_state",
            "label": "RSI状态",
            "weight": 0.35,
            "value": float(rsi) if isinstance(rsi, (int, float)) and math.isfinite(rsi) else 50.0,
            "contribution": _clip_contribution(rsi_signal * 1.8),
            "rationale": "基于 RSI 所处区间评估超买/超卖风险",
        },
        {
            "factor_key": "trend_direction",
            "label": "趋势方向",
            "weight": 0.35,
            "value": trend_signal,
            "contribution": _clip_contribution(trend_signal * 2.2),
            "rationale": "趋势方向决定技术面主导偏向",
        },
        {
            "factor_key": "momentum",
            "label": "动量信号",
            "weight": 0.30,
            "value": momentum_signal,
            "contribution": _clip_contribution(momentum_signal * 1.6),
            "rationale": "均线与 MACD 共同刻画短中期动量",
        },
    ]
    return score, label, points, breakdown


def score_financial_details(
    data: dict[str, Any],
) -> tuple[float, str, list[str], list[dict[str, Any]]]:
    score, label, points = score_financial(data)

    pe = _safe_get(data, "trailing_pe") or _safe_get(data, "valuation", "trailing_pe")
    rg = _safe_get(data, "revenue_growth") or _safe_get(data, "financials", "revenue_growth")
    de = _safe_get(data, "debt_to_equity") or _safe_get(data, "financials", "debt_to_equity")
    fcf = _safe_get(data, "free_cash_flow") or _safe_get(data, "financials", "free_cash_flow")

    pe_signal = 0.0
    if isinstance(pe, (int, float)) and math.isfinite(pe):
        pe_signal = 1.0 if pe < 25 else (-0.6 if pe > 35 else 0.3)
    growth_signal = 0.0
    if isinstance(rg, (int, float)) and math.isfinite(rg):
        growth_signal = 1.0 if rg > 0 else -0.8
    leverage_signal = 0.0
    if isinstance(de, (int, float)) and math.isfinite(de):
        leverage_signal = 1.0 if de < 0.8 else (-0.6 if de > 1.5 else 0.1)
    cashflow_signal = 1.0 if isinstance(fcf, (int, float)) and fcf > 0 else -0.3

    breakdown = [
        {
            "factor_key": "valuation",
            "label": "估值水平",
            "weight": 0.30,
            "value": float(pe) if isinstance(pe, (int, float)) and math.isfinite(pe) else 0.0,
            "contribution": _clip_contribution(pe_signal * 2.0),
            "rationale": "结合市盈率区间评估估值压力",
        },
        {
            "factor_key": "growth",
            "label": "增长质量",
            "weight": 0.30,
            "value": float(rg) if isinstance(rg, (int, float)) and math.isfinite(rg) else 0.0,
            "contribution": _clip_contribution(growth_signal * 2.0),
            "rationale": "营收增速直接影响财务评分弹性",
        },
        {
            "factor_key": "balance_sheet",
            "label": "资产负债",
            "weight": 0.20,
            "value": float(de) if isinstance(de, (int, float)) and math.isfinite(de) else 0.0,
            "contribution": _clip_contribution(leverage_signal * 1.4),
            "rationale": "债务杠杆水平影响财务稳健性",
        },
        {
            "factor_key": "cash_flow",
            "label": "现金流",
            "weight": 0.20,
            "value": float(fcf) if isinstance(fcf, (int, float)) and math.isfinite(fcf) else 0.0,
            "contribution": _clip_contribution(cashflow_signal * 1.2),
            "rationale": "自由现金流体现盈利兑现质量",
        },
    ]
    return score, label, points, breakdown


def score_news_details(
    data: dict[str, Any],
) -> tuple[float, str, list[str], list[dict[str, Any]]]:
    score, label, points = score_news(data)

    market_news = data.get("market", [])
    impact_news = data.get("impact", [])
    market_list = market_news if isinstance(market_news, list) else []
    impact_list = impact_news if isinstance(impact_news, list) else []
    total = len(market_list) + len(impact_list)
    impact_ratio = (len(impact_list) / total) if total > 0 else 0.0

    positive_keywords = {"surge", "beat", "record", "upgrade", "buy", "bullish", "上涨", "利好", "突破"}
    negative_keywords = {"drop", "miss", "downgrade", "sell", "bearish", "risk", "下跌", "利空", "风险"}
    positive_count = 0
    negative_count = 0
    for item in market_list + impact_list:
        text = ""
        if isinstance(item, dict):
            text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        else:
            text = str(item).lower()
        if any(word in text for word in positive_keywords):
            positive_count += 1
        if any(word in text for word in negative_keywords):
            negative_count += 1
    sentiment_signal = ((positive_count - negative_count) / total) if total > 0 else 0.0

    breakdown = [
        {
            "factor_key": "sentiment_balance",
            "label": "情绪平衡",
            "weight": 0.45,
            "value": sentiment_signal,
            "contribution": _clip_contribution(sentiment_signal * 3.0),
            "rationale": "正负面新闻比值决定舆情方向",
        },
        {
            "factor_key": "impact_ratio",
            "label": "高影响占比",
            "weight": 0.35,
            "value": impact_ratio,
            "contribution": _clip_contribution((impact_ratio - 0.3) * 3.0),
            "rationale": "高影响事件占比越高，对评分影响越显著",
        },
        {
            "factor_key": "news_volume",
            "label": "样本规模",
            "weight": 0.20,
            "value": float(total),
            "contribution": _clip_contribution(min(total, 15) / 15 * 1.0 - 0.2),
            "rationale": "样本数量提升评分稳定性",
        },
    ]
    return score, label, points, breakdown


def score_peers_details(
    data: dict[str, Any],
) -> tuple[float, str, list[str], list[dict[str, Any]]]:
    score, label, points = score_peers(data)

    company = _safe_get(data, "company") or {}
    peers_list = _safe_get(data, "peers") or []
    peers_list = peers_list if isinstance(peers_list, list) else []

    company_pe = _safe_get(company, "trailing_pe")
    peer_pes = [p.get("trailing_pe") for p in peers_list if isinstance(p, dict) and isinstance(p.get("trailing_pe"), (int, float))]
    avg_peer_pe = (sum(peer_pes) / len(peer_pes)) if peer_pes else 0.0

    company_growth = _safe_get(company, "revenue_growth")
    peer_growths = [p.get("revenue_growth") for p in peers_list if isinstance(p, dict) and isinstance(p.get("revenue_growth"), (int, float))]
    avg_peer_growth = (sum(peer_growths) / len(peer_growths)) if peer_growths else 0.0

    pe_signal = 0.0
    if isinstance(company_pe, (int, float)) and avg_peer_pe > 0:
        pe_signal = 1.0 if company_pe < avg_peer_pe else -0.5
    growth_signal = 0.0
    if isinstance(company_growth, (int, float)) and peer_growths:
        growth_signal = 1.0 if company_growth > avg_peer_growth else -0.5

    breakdown = [
        {
            "factor_key": "peer_valuation_gap",
            "label": "估值相对差",
            "weight": 0.40,
            "value": float(company_pe) if isinstance(company_pe, (int, float)) else 0.0,
            "contribution": _clip_contribution(pe_signal * 2.2),
            "rationale": "与同行估值差异影响相对性价比判断",
        },
        {
            "factor_key": "peer_growth_gap",
            "label": "增速相对差",
            "weight": 0.35,
            "value": float(company_growth) if isinstance(company_growth, (int, float)) else 0.0,
            "contribution": _clip_contribution(growth_signal * 1.8),
            "rationale": "营收增速相对同行的优势或劣势",
        },
        {
            "factor_key": "peer_sample_size",
            "label": "同行样本数",
            "weight": 0.25,
            "value": float(len(peers_list)),
            "contribution": _clip_contribution(min(len(peers_list), 8) / 8 * 1.0 - 0.1),
            "rationale": "样本充足时同行结论更稳健",
        },
    ]
    return score, label, points, breakdown


def score_overview_details(
    *,
    tech_score: float = 5.0,
    fin_score: float = 5.0,
    news_score: float = 5.0,
    peers_score: float = 5.0,
) -> tuple[float, str, list[str], list[dict[str, Any]]]:
    score, label, points = score_overview(
        tech_score=tech_score,
        fin_score=fin_score,
        news_score=news_score,
        peers_score=peers_score,
    )
    breakdown = [
        {
            "factor_key": "financial",
            "label": "财务面",
            "weight": 0.35,
            "value": fin_score,
            "contribution": _clip_contribution((fin_score - 5.0) * 0.35),
            "rationale": "财务质量与估值稳健性",
        },
        {
            "factor_key": "technical",
            "label": "技术面",
            "weight": 0.25,
            "value": tech_score,
            "contribution": _clip_contribution((tech_score - 5.0) * 0.25),
            "rationale": "趋势与动量信号",
        },
        {
            "factor_key": "news",
            "label": "舆情面",
            "weight": 0.20,
            "value": news_score,
            "contribution": _clip_contribution((news_score - 5.0) * 0.20),
            "rationale": "短期信息流与事件冲击",
        },
        {
            "factor_key": "peers",
            "label": "同行面",
            "weight": 0.20,
            "value": peers_score,
            "contribution": _clip_contribution((peers_score - 5.0) * 0.20),
            "rationale": "相对同行表现与估值位置",
        },
    ]
    return score, label, points, breakdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _label(score: float) -> str:
    """Map score to Chinese label."""
    if score >= 8:
        return "强势"
    if score >= 6.5:
        return "偏多"
    if score >= 4.5:
        return "中性"
    if score >= 3:
        return "偏空"
    return "弱势"


# ---------------------------------------------------------------------------
# key_metrics extraction (deterministic fallback)
# ---------------------------------------------------------------------------

def _fmt_float(val: Any, suffix: str = "", pct: bool = False) -> str | None:
    """安全格式化浮点数为字符串，返回 None 表示无效值。"""
    if not isinstance(val, (int, float)) or not math.isfinite(val):
        return None
    if pct:
        return f"{val:.2%}{suffix}"
    return f"{val:.2f}{suffix}"


def _fmt_int(val: Any, suffix: str = "") -> str | None:
    if not isinstance(val, (int, float)) or not math.isfinite(val):
        return None
    return f"{int(val):,}{suffix}"


def metrics_technical(data: dict[str, Any]) -> list[dict[str, str]]:
    """从技术指标数据中提取关键指标 k/v 对。"""
    result: list[dict[str, str]] = []

    rsi = _fmt_float(_safe_get(data, "rsi"))
    if rsi:
        result.append({"label": "RSI", "value": rsi})

    price = _fmt_float(_safe_get(data, "close") or _safe_get(data, "price"))
    if price:
        result.append({"label": "当前价格", "value": price})

    ma20 = _fmt_float(_safe_get(data, "ma20"))
    if ma20:
        result.append({"label": "MA20", "value": ma20})

    ma50 = _fmt_float(_safe_get(data, "ma50"))
    if ma50:
        result.append({"label": "MA50", "value": ma50})

    macd = _fmt_float(_safe_get(data, "macd"))
    if macd:
        result.append({"label": "MACD", "value": macd})

    return result[:4]


def metrics_financial(data: dict[str, Any]) -> list[dict[str, str]]:
    """从财务数据中提取关键指标 k/v 对。"""
    result: list[dict[str, str]] = []

    pe = _safe_get(data, "trailing_pe") or _safe_get(data, "valuation", "trailing_pe")
    v = _fmt_float(pe)
    if v:
        result.append({"label": "市盈率", "value": v})

    pb = _safe_get(data, "price_to_book") or _safe_get(data, "valuation", "price_to_book")
    v = _fmt_float(pb)
    if v:
        result.append({"label": "市净率", "value": v})

    rg = _safe_get(data, "revenue_growth") or _safe_get(data, "financials", "revenue_growth")
    v = _fmt_float(rg, pct=True)
    if v:
        result.append({"label": "营收增长", "value": v})

    de = _safe_get(data, "debt_to_equity") or _safe_get(data, "financials", "debt_to_equity")
    v = _fmt_float(de)
    if v:
        result.append({"label": "资产负债率", "value": v})

    return result[:4]


def metrics_news(data: dict[str, Any]) -> list[dict[str, str]]:
    """从新闻数据中提取关键指标 k/v 对。"""
    market_news = data.get("market", [])
    impact_news = data.get("impact", [])
    total = len(market_news if isinstance(market_news, list) else []) + \
            len(impact_news if isinstance(impact_news, list) else [])

    result: list[dict[str, str]] = []
    if total > 0:
        result.append({"label": "新闻数量", "value": str(total)})
    return result[:4]


def metrics_peers(data: dict[str, Any]) -> list[dict[str, str]]:
    """从同行对比数据中提取关键指标 k/v 对。"""
    result: list[dict[str, str]] = []
    company = _safe_get(data, "company") or {}
    peers_list = _safe_get(data, "peers") or []

    pe = _safe_get(company, "trailing_pe")
    v = _fmt_float(pe)
    if v:
        result.append({"label": "公司PE", "value": v})

    if peers_list:
        peer_pes = [
            p.get("trailing_pe") for p in peers_list
            if isinstance(p.get("trailing_pe"), (int, float))
            and math.isfinite(p["trailing_pe"])
        ]
        if peer_pes:
            avg_pe = sum(peer_pes) / len(peer_pes)
            result.append({"label": "行业均值PE", "value": f"{avg_pe:.1f}"})
        result.append({"label": "对比公司数", "value": str(len(peers_list))})

    return result[:4]


def metrics_overview(sub_scores: dict[str, float]) -> list[dict[str, str]]:
    """从综合子评分中提取关键指标 k/v 对。"""
    return [
        {"label": "财务面", "value": f"{sub_scores.get('financial', 5.0):.1f}"},
        {"label": "技术面", "value": f"{sub_scores.get('technical', 5.0):.1f}"},
        {"label": "舆情面", "value": f"{sub_scores.get('news', 5.0):.1f}"},
        {"label": "同行面", "value": f"{sub_scores.get('peers', 5.0):.1f}"},
    ]
