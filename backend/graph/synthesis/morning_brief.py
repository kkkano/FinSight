# -*- coding: utf-8 -*-
"""Deterministic morning-brief synthesis."""
from __future__ import annotations

from typing import Any

from backend.graph.state import GraphState


def _extract_brief_headline(news_raw: Any) -> str:
    """Extract first headline from news tool output for morning brief."""
    if news_raw is None:
        return "暂无重大事件"
    if isinstance(news_raw, list):
        for item in news_raw[:5]:
            if isinstance(item, dict):
                title = item.get("headline") or item.get("title") or ""
                if title:
                    return str(title).strip()[:120]
            elif isinstance(item, str) and item.strip():
                return item.strip()[:120]
    elif isinstance(news_raw, str):
        for line in news_raw.split("\n"):
            clean = line.strip().lstrip("-•*0-9. ")
            if clean and len(clean) > 10:
                return clean[:120]
    return "暂无重大事件"


def _synthesize_morning_brief_data(state: GraphState) -> dict[str, Any]:
    """Deterministic morning brief synthesis — zero LLM cost (ADR-P1-001).

    Extracts price + news data from Graph step_results and produces
    structured brief data + formatted markdown.  Reuses the same response
    schema as ``morning_brief_router`` so the frontend needs no changes.
    """
    from datetime import datetime, timezone

    from backend.utils.quote import parse_quote_payload, safe_float

    artifacts = state.get("artifacts") or {}
    step_results = artifacts.get("step_results") if isinstance(artifacts, dict) else {}
    plan_ir = state.get("plan_ir") or {}
    raw_steps = plan_ir.get("steps") if isinstance(plan_ir, dict) else []
    step_index = {s.get("id"): s for s in (raw_steps or []) if isinstance(s, dict) and s.get("id")}

    subject = state.get("subject") or {}
    tickers = subject.get("tickers") if isinstance(subject, dict) else []
    all_tickers = [t for t in (tickers if isinstance(tickers, list) else []) if isinstance(t, str) and t.strip()]

    # Collect per-ticker price and news from step_results
    ticker_prices: dict[str, dict] = {}
    ticker_news: dict[str, str] = {}

    for step_id, item in (step_results if isinstance(step_results, dict) else {}).items():
        if not isinstance(item, dict):
            continue
        output = item.get("output")
        step_def = step_index.get(step_id) or {}
        tool_name = step_def.get("name") or ""
        inputs = step_def.get("inputs") or {}
        ticker = str(inputs.get("ticker") or "").strip()

        if tool_name == "get_stock_price" and ticker:
            parsed = parse_quote_payload(output) if output else None
            if parsed:
                ticker_prices[ticker] = parsed
        elif tool_name == "get_company_news" and ticker:
            ticker_news[ticker] = _extract_brief_headline(output)

    # Build highlights
    highlights: list[dict[str, Any]] = []
    for ticker in all_tickers:
        price_data = ticker_prices.get(ticker, {})
        price = safe_float(price_data.get("price"))
        change = safe_float(price_data.get("change"))
        change_pct = safe_float(price_data.get("change_percent"))
        headline = ticker_news.get(ticker, "暂无重大事件")

        trend = "neutral"
        if change_pct is not None:
            if change_pct >= 3.0:
                trend = "strong_up"
            elif change_pct >= 1.0:
                trend = "up"
            elif change_pct > -1.0:
                trend = "neutral"
            elif change_pct > -3.0:
                trend = "down"
            else:
                trend = "strong_down"

        highlights.append({
            "ticker": ticker,
            "price": round(price, 2) if price is not None else None,
            "price_change": round(change, 4) if change is not None else None,
            "price_change_pct": round(change_pct, 2) if change_pct is not None else None,
            "trend": trend,
            "key_event": headline,
        })

    highlights.sort(key=lambda h: abs(safe_float(h.get("price_change_pct")) or 0), reverse=True)

    # Market mood
    _MOOD_CN: dict[str, str] = {
        "bullish": "看涨", "cautiously_optimistic": "谨慎乐观", "neutral": "中性",
        "cautiously_pessimistic": "谨慎悲观", "bearish": "看跌",
    }
    priced = [h for h in highlights if h.get("price") is not None]
    if priced:
        avg = sum(safe_float(h.get("price_change_pct")) or 0 for h in priced) / len(priced)
        if avg >= 1.5:
            mood = "bullish"
        elif avg >= 0.3:
            mood = "cautiously_optimistic"
        elif avg > -0.3:
            mood = "neutral"
        elif avg > -1.5:
            mood = "cautiously_pessimistic"
        else:
            mood = "bearish"
    else:
        mood = "neutral"

    # Summary text
    up_cnt = sum(1 for h in priced if (safe_float(h.get("price_change_pct")) or 0) > 0)
    down_cnt = sum(1 for h in priced if (safe_float(h.get("price_change_pct")) or 0) < 0)
    flat_cnt = len(priced) - up_cnt - down_cnt
    summary = f"今日跟踪 {len(all_tickers)} 只标的，其中 {len(priced)} 只获取到实时报价。"
    if priced:
        summary += f"上涨 {up_cnt} 只，下跌 {down_cnt} 只，横盘 {flat_cnt} 只。"
    summary += f"整体情绪：{_MOOD_CN.get(mood, '中性')}。"

    # Action items
    action_items: list[str] = []
    big_up = [h for h in highlights if (safe_float(h.get("price_change_pct")) or 0) >= 3.0]
    big_down = [h for h in highlights if (safe_float(h.get("price_change_pct")) or 0) <= -3.0]
    if big_up:
        action_items.append(f"关注强势标的 {', '.join(h['ticker'] for h in big_up[:3])} 的持续动能，考虑止盈策略")
    if big_down:
        action_items.append(f"警惕 {', '.join(h['ticker'] for h in big_down[:3])} 的下行风险，检查止损位")
    news_hits = [h for h in highlights if h.get("key_event") and h["key_event"] != "暂无重大事件"]
    if news_hits:
        action_items.append(f"阅读 {', '.join(h['ticker'] for h in news_hits[:3])} 的最新新闻，评估事件影响")
    if not action_items:
        action_items.append("今日持仓波动平稳，建议维持当前仓位")

    brief_data: dict[str, Any] = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "summary": summary,
        "highlights": highlights,
        "market_mood": mood,
        "market_mood_cn": _MOOD_CN.get(mood, "中性"),
        "action_items": action_items,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ticker_count": len(all_tickers),
        "priced_count": len(priced),
    }

    # Draft markdown
    md_lines = [
        f"# 📊 每日晨报 — {brief_data['date']}", "",
        f"**{summary}**", "",
        "## 持仓概览", "",
    ]
    for h in highlights:
        p = f"${h['price']:.2f}" if h.get("price") is not None else "N/A"
        c = f"{h['price_change_pct']:+.2f}%" if h.get("price_change_pct") is not None else ""
        md_lines.append(f"- **{h['ticker']}** {p} {c} — {h['key_event']}")
    md_lines += ["", "## 操作建议", ""]
    for item in action_items:
        md_lines.append(f"- {item}")
    md_lines += [
        "",
        f"> 整体情绪：**{_MOOD_CN.get(mood, '中性')}** | 本报告由 FinSight Pipeline 自动生成，不构成投资建议。",
    ]

    return {"brief_data": brief_data, "draft_markdown": "\n".join(md_lines)}
