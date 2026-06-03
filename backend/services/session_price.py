# -*- coding: utf-8 -*-
"""交易时段感知价格快照（盘前/盘中/盘后）。

监控引擎在不同时段需要不同的"当前价"基准：
  - pre_market   优先盘前价 / 盘前涨跌幅
  - after_hours  优先盘后价 / 盘后涨跌幅
  - regular      常规价（与现状一致）
  - closed       不取价（价格规则被跳过，本模块不应在闭市被调用）

数据来源与诚实原则
-----------------
免费无 key 端点的现实（2026-06 实测）：
  - Yahoo v7 quote 端点已对无 crumb 请求返回 401（preMarketPrice/postMarketPrice 拿不到）
  - Yahoo v8 chart 的 meta 只暴露 regularMarketPrice，**没有**独立的盘前/盘后价字段
唯一能诚实拿到盘前/盘后真实成交价的途径：
  v8 chart `includePrePost=true&interval=1m`，用 meta.currentTradingPeriod 的
  pre/regular/post 时间窗切分 timestamp+close 数组，取对应时段最后一个有效成交点。

因此：
  - 能从盘前/盘后时间窗解析到成交点 → price_basis="pre_market"/"post_market"（真盘前/盘后价）
  - 拿不到（无盘前交易 / 端点失败）→ 回退常规价，price_basis="regular_fallback"
    （绝不把常规价冒充成盘前价；前端可据 price_basis 显示"盘前价"或"昨收基准"）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from backend.services.alert_scheduler import fetch_price_snapshot

logger = logging.getLogger(__name__)

# 复用 alert_scheduler 的 UA，免封
_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (FinSightBot)"}


@dataclass
class SessionPriceSnapshot:
    """带时段标注的价格快照。

    字段：
      ticker          标的
      price           本时段参考价（盘前价 / 盘后价 / 常规价）
      change_percent  对应涨跌幅（盘前/盘后相对昨收；常规相对前一交易日收盘）
      market_session  价格所属时段："pre_market"/"regular"/"after_hours"
      price_basis     价格来源："pre_market"/"post_market"/"regular"/"regular_fallback"
                      regular_fallback = 本想取盘前/盘后价但拿不到，回退常规价（诚实标注）
    """

    ticker: str
    price: float | None
    change_percent: float | None
    market_session: str
    price_basis: str


def _fetch_yahoo_session_price(ticker: str, period: str) -> tuple[float, float] | None:
    """从 Yahoo v8 chart 解析指定时段（pre/post）的最后成交价与相对昨收涨跌幅。

    Args:
        ticker: 标的
        period: "pre" 或 "post"（对应 currentTradingPeriod 的键）

    Returns:
        (price, change_percent) 或 None（无盘前/盘后成交 / 端点失败）。
        change_percent 相对 meta.previousClose（昨日常规收盘）计算。
    """
    try:
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            "?range=1d&interval=1m&includePrePost=true"
        )
        resp = requests.get(url, timeout=8, headers=_YAHOO_HEADERS)
        if resp.status_code != 200:
            return None

        result = (resp.json().get("chart", {}).get("result") or [None])[0] or {}
        meta = result.get("meta") or {}
        ctp = meta.get("currentTradingPeriod") or {}
        window = ctp.get(period) or {}
        start, end = window.get("start"), window.get("end")
        if start is None or end is None:
            return None

        timestamps = result.get("timestamp") or []
        closes = (result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        if not timestamps or not closes:
            return None

        # 取落在 [start, end) 窗口内的最后一个有效成交点
        last_price: float | None = None
        for ts, close in zip(timestamps, closes):
            if close is None:
                continue
            if start <= ts < end:
                last_price = float(close)
        if last_price is None:
            return None

        # 涨跌幅基准：昨日常规收盘（previousClose / chartPreviousClose 兜底）
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
        change_percent = None
        if prev_close not in (None, 0):
            change_percent = (last_price - float(prev_close)) / float(prev_close) * 100.0
        if change_percent is None:
            return None

        return last_price, change_percent
    except Exception as exc:  # noqa: BLE001 - 外部端点不稳定，失败即回退常规价
        logger.info("[SessionPrice] yahoo %s session fetch failed for %s: %s", period, ticker, exc)
        return None


def fetch_session_aware_price_snapshot(ticker: str, session: str) -> SessionPriceSnapshot | None:
    """按时段返回价格快照（盘前优先盘前价，盘后优先盘后价，常规用常规价）。

    Args:
        ticker: 标的
        session: 当前时段（"pre_market"/"regular"/"after_hours"；"closed" 不应调用本函数）

    Returns:
        SessionPriceSnapshot；常规价都拿不到时返回 None。

    回退诚实原则：盘前/盘后拿不到真价时回退常规价并标 price_basis="regular_fallback"。
    """
    # 常规价作为兜底基准（多源 fallback：stooq/yfinance/yahoo）
    regular = fetch_price_snapshot(ticker)

    # 盘前 / 盘后：先尝试取该时段真实成交价
    if session in ("pre_market", "after_hours"):
        period = "pre" if session == "pre_market" else "post"
        sess = _fetch_yahoo_session_price(ticker, period)
        if sess is not None:
            price, change_percent = sess
            basis = "pre_market" if session == "pre_market" else "post_market"
            return SessionPriceSnapshot(
                ticker=ticker,
                price=price,
                change_percent=change_percent,
                market_session=session,
                price_basis=basis,
            )
        # 拿不到盘前/盘后真价 → 回退常规价（诚实标注）
        if regular is None:
            return None
        return SessionPriceSnapshot(
            ticker=ticker,
            price=regular.price,
            change_percent=regular.change_percent,
            market_session=session,
            price_basis="regular_fallback",
        )

    # regular 时段（含其他兜底）：常规价
    if regular is None:
        return None
    return SessionPriceSnapshot(
        ticker=ticker,
        price=regular.price,
        change_percent=regular.change_percent,
        market_session=session if session else "regular",
        price_basis="regular",
    )


__all__ = ["SessionPriceSnapshot", "fetch_session_aware_price_snapshot"]
