# -*- coding: utf-8 -*-
"""一键晨报 API 路由

聚合用户持仓中所有 ticker 的快照数据 + 新闻标题，
生成当日投资组合晨报摘要。不依赖 LLM，纯数据聚合 + 格式化。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.dashboard.cache import dashboard_cache
from backend.utils.quote import parse_quote_payload, safe_float

logger = logging.getLogger(__name__)

# 晨报缓存 TTL（30 分钟）
_BRIEF_CACHE_TTL = 1800


class MorningBriefRequest(BaseModel):
    """晨报生成请求"""

    session_id: str
    tickers: list[str] = Field(default_factory=list, max_length=50)


@dataclass(frozen=True)
class MorningBriefRouterDeps:
    """晨报路由依赖注入"""

    resolve_thread_id: Callable[[Optional[str]], str]
    get_portfolio_positions: Callable[[str], list[dict[str, Any]]]
    get_stock_price: Callable[[str], Any]
    get_company_news: Callable[[str, int], Any]
    # P1: Graph Pipeline support (optional, fallback to direct fetch when None)
    get_graph_runner: Optional[Callable[[], Any]] = None


def _classify_change(pct: float | None) -> str:
    """根据涨跌幅分类情绪标签"""
    if pct is None:
        return "neutral"
    if pct >= 3.0:
        return "strong_up"
    if pct >= 1.0:
        return "up"
    if pct > -1.0:
        return "neutral"
    if pct > -3.0:
        return "down"
    return "strong_down"


def _derive_market_mood(highlights: list[dict[str, Any]]) -> str:
    """根据持仓整体涨跌情况推导市场情绪"""
    if not highlights:
        return "neutral"

    up_count = 0
    down_count = 0
    total_change = 0.0
    valid = 0

    for item in highlights:
        pct = safe_float(item.get("price_change_pct"))
        if pct is None:
            continue
        valid += 1
        total_change += pct
        if pct > 0:
            up_count += 1
        elif pct < 0:
            down_count += 1

    if valid == 0:
        return "neutral"

    avg = total_change / valid
    if avg >= 1.5:
        return "bullish"
    if avg >= 0.3:
        return "cautiously_optimistic"
    if avg > -0.3:
        return "neutral"
    if avg > -1.5:
        return "cautiously_pessimistic"
    return "bearish"


def _mood_label_cn(mood: str) -> str:
    """将情绪标签翻译为中文"""
    mapping = {
        "bullish": "看涨",
        "cautiously_optimistic": "谨慎乐观",
        "neutral": "中性",
        "cautiously_pessimistic": "谨慎悲观",
        "bearish": "看跌",
    }
    return mapping.get(mood, "中性")


def _generate_action_items(highlights: list[dict[str, Any]]) -> list[str]:
    """根据持仓变化生成操作建议"""
    items: list[str] = []

    big_movers_up = [
        h for h in highlights
        if (safe_float(h.get("price_change_pct")) or 0) >= 3.0
    ]
    big_movers_down = [
        h for h in highlights
        if (safe_float(h.get("price_change_pct")) or 0) <= -3.0
    ]
    news_tickers = [
        h for h in highlights
        if h.get("key_event") and h["key_event"] != "暂无重大事件"
    ]

    if big_movers_up:
        tickers_str = ", ".join(h["ticker"] for h in big_movers_up[:3])
        items.append(f"关注强势标的 {tickers_str} 的持续动能，考虑止盈策略")

    if big_movers_down:
        tickers_str = ", ".join(h["ticker"] for h in big_movers_down[:3])
        items.append(f"警惕 {tickers_str} 的下行风险，检查止损位")

    if news_tickers:
        tickers_str = ", ".join(h["ticker"] for h in news_tickers[:3])
        items.append(f"阅读 {tickers_str} 的最新新闻，评估事件影响")

    if not items:
        items.append("今日持仓波动平稳，建议维持当前仓位")

    return items


def _extract_headline(news_raw: Any, ticker: str) -> str:
    """从新闻原始数据提取一条关键标题"""
    if news_raw is None:
        return "暂无重大事件"

    headlines: list[str] = []

    if isinstance(news_raw, list):
        for item in news_raw[:5]:
            if isinstance(item, dict):
                title = item.get("headline") or item.get("title") or ""
                if title:
                    headlines.append(str(title).strip())
            elif isinstance(item, str):
                headlines.append(item.strip())
    elif isinstance(news_raw, str):
        # 尝试从文本中提取第一行有意义的标题
        for line in news_raw.split("\n"):
            clean = line.strip().lstrip("-•*0-9. ")
            if clean and len(clean) > 10:
                headlines.append(clean)
                break

    if not headlines:
        return "暂无重大事件"

    return headlines[0][:120]


def _cache_key(session_id: str, tickers: list[str]) -> str:
    """生成晨报缓存键"""
    sorted_tickers = sorted(set(t.upper() for t in tickers))
    raw = f"{session_id}:{','.join(sorted_tickers)}"
    digest = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"morning_brief_{digest}"


def create_morning_brief_router(deps: MorningBriefRouterDeps) -> APIRouter:
    """创建晨报 API 路由"""
    router = APIRouter(tags=["MorningBrief"])

    @router.post("/api/morning-brief/generate")
    async def generate_morning_brief(request: MorningBriefRequest):
        """生成一键晨报"""
        # 验证 session_id
        try:
            normalized_session = deps.resolve_thread_id(request.session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # 合并 tickers：请求参数 + 持仓中的 tickers
        request_tickers = {t.strip().upper() for t in request.tickers if t.strip()}

        try:
            stored_positions = deps.get_portfolio_positions(normalized_session) or []
        except Exception as exc:
            logger.warning("[MorningBrief] get_portfolio_positions failed: %s", exc)
            stored_positions = []

        position_tickers = {
            str(pos.get("ticker", "")).strip().upper()
            for pos in stored_positions
            if str(pos.get("ticker", "")).strip()
        }

        all_tickers = sorted(request_tickers | position_tickers)

        if not all_tickers:
            return {
                "success": True,
                "brief": {
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "summary": "当前无持仓，请先添加持仓后再生成晨报。",
                    "highlights": [],
                    "market_mood": "neutral",
                    "market_mood_cn": "中性",
                    "action_items": ["请先在工作台添加持仓标的"],
                },
            }

        # 检查缓存
        cache_k = _cache_key(normalized_session, all_tickers)
        cached = dashboard_cache.get("__morning_brief__", cache_k)
        if cached is not None:
            return {"success": True, "brief": cached}

        # ── P1: 优先使用 Graph Pipeline（cache miss 时） ──
        if deps.get_graph_runner is not None:
            try:
                runner = await deps.get_graph_runner()
                tickers_str = " ".join(all_tickers)
                result = await runner.ainvoke(
                    thread_id=normalized_session,
                    query=f"生成晨报 {tickers_str}",
                    output_mode="brief",
                    ui_context={"tickers_override": all_tickers},
                )
                graph_artifacts = result.get("artifacts") or {} if isinstance(result, dict) else {}
                brief_data = graph_artifacts.get("brief_data") if isinstance(graph_artifacts, dict) else None
                if isinstance(brief_data, dict) and brief_data.get("highlights"):
                    dashboard_cache.set("__morning_brief__", cache_k, brief_data, ttl=_BRIEF_CACHE_TTL)
                    return {"success": True, "brief": brief_data}
                logger.warning("[MorningBrief] Graph Pipeline returned no brief_data, falling back to direct fetch")
            except Exception as exc:
                logger.warning("[MorningBrief] Graph Pipeline failed (%s), falling back to direct fetch", exc)

        # ── Fallback: 直接数据获取（原始实现） ──
        # 并发获取所有 ticker 的快照和新闻
        async def _fetch_ticker_data(ticker: str) -> dict[str, Any]:
            """获取单个 ticker 的快照 + 新闻"""
            snapshot: dict[str, Any] = {}
            news_headline = "暂无重大事件"

            # 获取价格快照
            try:
                raw_payload = await asyncio.to_thread(deps.get_stock_price, ticker)
                parsed = parse_quote_payload(raw_payload)
                if parsed:
                    snapshot = parsed
            except Exception as exc:
                logger.debug("[MorningBrief] price fetch failed for %s: %s", ticker, exc)

            # 获取新闻标题
            try:
                raw_news = await asyncio.to_thread(deps.get_company_news, ticker, 5)
                news_headline = _extract_headline(raw_news, ticker)
            except Exception as exc:
                logger.debug("[MorningBrief] news fetch failed for %s: %s", ticker, exc)

            price = safe_float(snapshot.get("price"))
            change = safe_float(snapshot.get("change"))
            change_pct = safe_float(snapshot.get("change_percent"))

            return {
                "ticker": ticker,
                "price": round(price, 2) if price is not None else None,
                "price_change": round(change, 4) if change is not None else None,
                "price_change_pct": round(change_pct, 2) if change_pct is not None else None,
                "trend": _classify_change(change_pct),
                "key_event": news_headline,
            }

        # 限制并发数，避免 API 过载
        semaphore = asyncio.Semaphore(5)

        async def _fetch_with_limit(ticker: str) -> dict[str, Any]:
            async with semaphore:
                return await _fetch_ticker_data(ticker)

        highlights = await asyncio.gather(
            *[_fetch_with_limit(t) for t in all_tickers]
        )
        highlights_list = list(highlights)

        # 按涨跌幅绝对值排序，波动大的排前面
        highlights_list.sort(
            key=lambda h: abs(safe_float(h.get("price_change_pct")) or 0),
            reverse=True,
        )

        # 计算市场情绪
        market_mood = _derive_market_mood(highlights_list)

        # 生成汇总文本
        priced_count = sum(1 for h in highlights_list if h.get("price") is not None)
        up_count = sum(
            1 for h in highlights_list
            if (safe_float(h.get("price_change_pct")) or 0) > 0
        )
        down_count = sum(
            1 for h in highlights_list
            if (safe_float(h.get("price_change_pct")) or 0) < 0
        )
        flat_count = priced_count - up_count - down_count

        summary_parts: list[str] = []
        summary_parts.append(
            f"今日跟踪 {len(all_tickers)} 只标的，"
            f"其中 {priced_count} 只获取到实时报价。"
        )
        if priced_count > 0:
            summary_parts.append(
                f"上涨 {up_count} 只，下跌 {down_count} 只，"
                f"横盘 {flat_count} 只。"
            )
        summary_parts.append(f"整体情绪：{_mood_label_cn(market_mood)}。")

        brief = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "summary": "".join(summary_parts),
            "highlights": highlights_list,
            "market_mood": market_mood,
            "market_mood_cn": _mood_label_cn(market_mood),
            "action_items": _generate_action_items(highlights_list),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ticker_count": len(all_tickers),
            "priced_count": priced_count,
        }

        # 写入缓存
        dashboard_cache.set("__morning_brief__", cache_k, brief, ttl=_BRIEF_CACHE_TTL)

        return {"success": True, "brief": brief}

    return router
