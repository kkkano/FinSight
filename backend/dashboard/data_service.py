"""
Dashboard 数据服务层

统一调用 tools 层的多源数据获取函数，提供 Dashboard 专用的数据接口。
将原本 dashboard_router.py 中的单一数据源（yfinance）替换为多源回退策略。

数据流:
    Dashboard Router → Data Service → Tools Layer (10+ 数据源)
                                         ↓
                                    Dashboard Cache
"""
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from backend.dashboard.cache import dashboard_cache

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════


def _safe_float(value: Any) -> Optional[float]:
    """安全转换为浮点数，处理 NaN 和 Inf"""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _ts_seconds(ts: Any) -> Optional[int]:
    """将各种时间格式转换为 Unix 秒级时间戳"""
    try:
        if ts is None:
            return None
        if isinstance(ts, (int, float)):
            return int(ts)
        if isinstance(ts, pd.Timestamp):
            return int(ts.to_pydatetime().timestamp())
        if isinstance(ts, datetime):
            dt = ts
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        # 字符串格式 "2024-01-15" 或 "2024-01-15 16:00"
        if isinstance(ts, str):
            for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]:
                try:
                    dt = datetime.strptime(ts, fmt)
                    dt = dt.replace(tzinfo=timezone.utc)
                    return int(dt.timestamp())
                except ValueError:
                    continue
    except Exception:
        return None
    return None


def _parse_time_to_unix(time_value: Any) -> Optional[int]:
    """解析各种时间格式为 Unix 时间戳"""
    return _ts_seconds(time_value)


# ══════════════════════════════════════════════════════════════════════════════
# 市场数据获取
# ══════════════════════════════════════════════════════════════════════════════


def fetch_market_chart(symbol: str, period: str = "1y", interval: str = "1d") -> list[dict]:
    """
    获取 K 线图数据 - 使用多源回退策略

    使用 tools/price.py 的 get_stock_historical_data()，支持 10+ 数据源：
    yfinance → Alpha Vantage → Finnhub → IEX Cloud → Tiingo → Twelve Data → ...

    Args:
        symbol: 资产代码 (e.g., "AAPL", "^GSPC", "SPY", "BTC-USD")
        period: 时间周期 ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y")
        interval: 数据间隔 ("1d", "1wk", "1mo")

    Returns:
        list[dict]: OHLCV 数据列表
            [{"time": 1705276800, "open": 180.5, "high": 185.2, "low": 179.8,
              "close": 183.4, "volume": 1250000}, ...]
    """
    try:
        # 动态导入避免循环依赖
        from backend.tools.price import get_stock_historical_data

        result = get_stock_historical_data(symbol, period=period, interval=interval)

        if result.get("error"):
            logger.info(f"[DataService] market_chart error for {symbol}: {result['error']}")
            return []

        kline_data = result.get("kline_data", [])
        if not kline_data:
            logger.info(f"[DataService] market_chart empty for {symbol}")
            return []

        # 转换为 Dashboard 格式 (time: unix seconds)
        out = []
        for item in kline_data:
            ts = _parse_time_to_unix(item.get("time"))
            if ts is None:
                continue

            out.append({
                "time": ts,
                "open": _safe_float(item.get("open")),
                "high": _safe_float(item.get("high")),
                "low": _safe_float(item.get("low")),
                "close": _safe_float(item.get("close")),
                "volume": _safe_float(item.get("volume")) or 0,
            })

        logger.info(f"[DataService] market_chart OK for {symbol}: {len(out)} bars, source={result.get('source', 'unknown')}")
        return out

    except Exception as e:
        logger.info(f"[DataService] market_chart exception for {symbol}: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# 快照数据获取
# ══════════════════════════════════════════════════════════════════════════════


def fetch_snapshot(symbol: str, asset_type: str) -> dict:
    """
    获取快照数据 (KPI)

    根据资产类型返回不同字段:
    - equity: revenue, eps, gross_margin, fcf
    - index: index_level
    - etf: nav
    - crypto: index_level

    使用 yfinance 作为主要来源（info 数据目前没有更好的多源替代）

    Args:
        symbol: 资产代码
        asset_type: 资产类型 ("equity", "index", "etf", "crypto")

    Returns:
        dict: 快照数据
    """
    import yfinance as yf

    snapshot: dict = {}
    try:
        t = yf.Ticker(symbol)

        # 获取最近收盘价作为基础点位
        last_close = None
        try:
            hist = t.history(period="5d", interval="1d")
            if hist is not None and not hist.empty and len(hist) >= 1:
                last_close = _safe_float(hist["Close"].iloc[-1])
        except Exception:
            last_close = None

        if asset_type == "equity":
            info = {}
            try:
                info = getattr(t, "info", {}) or {}
            except Exception:
                info = {}

            snapshot.update({
                "revenue": _safe_float(info.get("totalRevenue")),
                "eps": _safe_float(info.get("trailingEps") or info.get("forwardEps")),
                "gross_margin": _safe_float(info.get("grossMargins")),
                "fcf": _safe_float(info.get("freeCashflow")),
            })

        elif asset_type == "index":
            if last_close is not None:
                snapshot["index_level"] = last_close

        elif asset_type == "etf":
            nav = None
            try:
                info = getattr(t, "info", {}) or {}
                nav = _safe_float(info.get("navPrice"))
            except Exception:
                nav = None
            snapshot["nav"] = nav if nav is not None else last_close

        elif asset_type == "crypto":
            if last_close is not None:
                snapshot["index_level"] = last_close

    except Exception as e:
        logger.info(f"[DataService] snapshot failed for {symbol}: {e}")

    return snapshot


# ══════════════════════════════════════════════════════════════════════════════
# 营收趋势获取
# ══════════════════════════════════════════════════════════════════════════════


def fetch_revenue_trend(symbol: str) -> list[dict]:
    """
    获取季度营收趋势数据

    使用 yfinance 的 quarterly_income_stmt 或 quarterly_financials

    Args:
        symbol: 股票代码

    Returns:
        list[dict]: 季度营收数据
            [{"period": "2024 Q1", "value": 123456789, "name": "2024 Q1"}, ...]
    """
    import yfinance as yf

    try:
        t = yf.Ticker(symbol)

        # 优先尝试 quarterly_income_stmt（更新的 API）
        financials = None
        try:
            financials = getattr(t, "quarterly_income_stmt", None)
            if financials is None or (hasattr(financials, "empty") and financials.empty):
                financials = getattr(t, "quarterly_financials", None)
        except Exception:
            financials = getattr(t, "quarterly_financials", None)

        if financials is None or (hasattr(financials, "empty") and financials.empty):
            logger.info(f"[DataService] No quarterly financials for {symbol}")
            return []

        # 查找营收行（可能的名称）
        revenue_keys = ["Total Revenue", "Revenue", "Net Sales", "Operating Revenue"]
        revenue_row = None
        for key in revenue_keys:
            if key in financials.index:
                revenue_row = financials.loc[key]
                break

        if revenue_row is None:
            logger.info(f"[DataService] No revenue row found for {symbol}")
            return []

        # 转换为列表格式，按时间排序
        out: list[dict] = []
        for col in revenue_row.index:
            value = _safe_float(revenue_row[col])
            if value is None:
                continue

            # 格式化季度标签
            if isinstance(col, pd.Timestamp):
                period = f"{col.year} Q{(col.month - 1) // 3 + 1}"
            else:
                period = str(col)[:10]

            out.append({
                "period": period,
                "value": value,
                "name": period,
            })

        # 按时间正序排列（最早的在前）
        out.reverse()
        # 只保留最近 8 个季度
        result = out[-8:]
        logger.info(f"[DataService] revenue_trend OK for {symbol}: {len(result)} quarters")
        return result

    except Exception as e:
        logger.info(f"[DataService] revenue_trend failed for {symbol}: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# 分部数据获取
# ══════════════════════════════════════════════════════════════════════════════


def fetch_segment_mix(symbol: str) -> list[dict]:
    """
    获取业务分部收入占比

    Phase 2 将使用 FMP API 实现
    目前返回空数组（yfinance 不提供分部数据）

    Args:
        symbol: 股票代码

    Returns:
        list[dict]: 分部数据
            [{"name": "iPhone", "value": 200000000000, "weight": 0.52}, ...]
    """
    try:
        # Phase 2: 使用 FMP API
        from backend.tools.fmp import get_revenue_product_segmentation
        segments = get_revenue_product_segmentation(symbol)

        if segments:
            return [
                {
                    "name": seg.get("segment", "Unknown"),
                    "value": seg.get("revenue", 0),
                    "weight": seg.get("percentage", 0) / 100,
                }
                for seg in segments
            ]
    except ImportError:
        # FMP 模块尚未创建
        pass
    except Exception as e:
        logger.info(f"[DataService] segment_mix failed for {symbol}: {e}")

    # 暂时返回空
    logger.info(f"[DataService] segment_mix: no data available for {symbol}")
    return []


# ══════════════════════════════════════════════════════════════════════════════
# 新闻数据获取
# ══════════════════════════════════════════════════════════════════════════════


def fetch_news(symbol: str, limit: int = 20) -> dict[str, list[dict]]:
    """
    获取新闻数据 - 使用多源回退策略

    使用 tools/news.py 的多源获取：
    yfinance → Finnhub → Alpha Vantage → 搜索

    Args:
        symbol: 资产代码
        limit: 每类新闻的数量限制

    Returns:
        dict: {"market": [...], "impact": [...]}
            - market: 市场新闻
            - impact: 资产相关新闻
    """
    try:
        from backend.tools.news import get_company_news, get_market_news_headlines

        # 获取资产相关新闻 (impact)
        impact_items = []
        try:
            raw_impact = get_company_news(symbol, limit=limit)
            if isinstance(raw_impact, list):
                impact_items = raw_impact
            elif isinstance(raw_impact, str):
                # 某些情况下可能返回格式化字符串，需要解析
                impact_items = _parse_news_text(raw_impact)
        except Exception as e:
            logger.info(f"[DataService] get_company_news failed for {symbol}: {e}")

        # 获取市场新闻
        market_items = []
        try:
            # 使用 SPY 作为市场新闻代理
            raw_market = get_market_news_headlines(limit=limit)
            if isinstance(raw_market, list):
                market_items = raw_market
            elif isinstance(raw_market, str):
                market_items = _parse_news_text(raw_market)
        except Exception as e:
            logger.info(f"[DataService] get_market_news_headlines failed: {e}")

        # 转换为 Dashboard NewsItem 格式
        result = {
            "market": [_to_news_item(item) for item in market_items[:limit]],
            "impact": [_to_news_item(item) for item in impact_items[:limit]],
        }

        logger.info(f"[DataService] news OK for {symbol}: market={len(result['market'])}, impact={len(result['impact'])}")
        return result

    except Exception as e:
        logger.info(f"[DataService] news exception for {symbol}: {e}")
        return {"market": [], "impact": []}


def _to_news_item(item: Any) -> dict:
    """将各种新闻格式转换为统一的 NewsItem 格式"""
    if isinstance(item, dict):
        # 标准格式
        title = item.get("title") or item.get("headline") or ""
        url = item.get("url") or item.get("link") or ""
        source = item.get("source") or item.get("publisher") or ""
        ts = item.get("ts") or item.get("published_at") or item.get("datetime") or ""
        summary = item.get("summary") or item.get("snippet") or item.get("content") or ""

        # 处理时间戳
        if isinstance(ts, (int, float)):
            try:
                dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                ts = dt.isoformat()
            except Exception:
                ts = ""
        elif not isinstance(ts, str):
            ts = str(ts) if ts else ""

        return {
            "title": title.strip() if title else "",
            "url": url.strip() if url else "",
            "source": source.strip() if source else "",
            "ts": ts,
            "summary": summary.strip() if summary else "",
        }
    else:
        return {
            "title": str(item) if item else "",
            "url": "",
            "source": "",
            "ts": "",
            "summary": "",
        }


def _parse_news_text(text: str) -> list[dict]:
    """解析文本格式的新闻列表"""
    items = []
    if not text:
        return items

    # 尝试按行解析
    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if line and len(line) > 10:
            items.append({
                "title": line,
                "url": "",
                "source": "",
                "ts": "",
                "summary": "",
            })

    return items


# ══════════════════════════════════════════════════════════════════════════════
# ETF/Index 特定数据
# ══════════════════════════════════════════════════════════════════════════════


def fetch_sector_weights(symbol: str, asset_type: str) -> list[dict]:
    """
    获取 ETF/Index 板块权重

    Phase 3 将使用 FMP API 实现

    Args:
        symbol: ETF/Index 代码
        asset_type: 资产类型

    Returns:
        list[dict]: 板块权重
            [{"name": "Technology", "weight": 0.285}, ...]
    """
    if asset_type not in ("etf", "index"):
        return []

    try:
        from backend.tools.fmp import get_etf_sector_weights
        weights = get_etf_sector_weights(symbol)

        if weights:
            return [
                {"name": w.get("sector", "Unknown"), "weight": w.get("weight", 0) / 100}
                for w in weights
            ]
    except ImportError:
        pass
    except Exception as e:
        logger.info(f"[DataService] sector_weights failed for {symbol}: {e}")

    return []


def fetch_top_constituents(symbol: str, asset_type: str, limit: int = 10) -> list[dict]:
    """
    获取指数成分股

    Phase 3 将使用 FMP API 实现

    Args:
        symbol: Index 代码
        asset_type: 资产类型
        limit: 返回数量限制

    Returns:
        list[dict]: 成分股列表
            [{"symbol": "AAPL", "name": "Apple Inc.", "weight": 0.072}, ...]
    """
    if asset_type != "index":
        return []

    try:
        from backend.tools.fmp import get_index_constituents
        constituents = get_index_constituents(symbol)

        if constituents:
            return [
                {
                    "symbol": c.get("symbol", ""),
                    "name": c.get("name", ""),
                    "weight": c.get("weight", 0),
                }
                for c in constituents[:limit]
            ]
    except ImportError:
        pass
    except Exception as e:
        logger.info(f"[DataService] top_constituents failed for {symbol}: {e}")

    return []


def fetch_holdings(symbol: str, asset_type: str, limit: int = 50) -> list[dict]:
    """
    获取 ETF 持仓

    Phase 3 将使用 FMP API 实现

    Args:
        symbol: ETF 代码
        asset_type: 资产类型
        limit: 返回数量限制

    Returns:
        list[dict]: 持仓列表
            [{"symbol": "AAPL", "name": "Apple Inc.", "weight": 0.072,
              "shares": 123456, "value": 12345678}, ...]
    """
    if asset_type not in ("etf", "portfolio"):
        return []

    try:
        from backend.tools.fmp import get_etf_holdings
        holdings = get_etf_holdings(symbol, limit=limit)

        if holdings:
            return [
                {
                    "symbol": h.get("symbol", ""),
                    "name": h.get("name", ""),
                    "weight": h.get("weight", 0),
                    "shares": h.get("shares", 0),
                    "value": h.get("value", 0),
                }
                for h in holdings[:limit]
            ]
    except ImportError:
        pass
    except Exception as e:
        logger.info(f"[DataService] holdings failed for {symbol}: {e}")

    return []


# ══════════════════════════════════════════════════════════════════════════════
# 数据服务类（可选的面向对象封装）
# ══════════════════════════════════════════════════════════════════════════════


class DashboardDataService:
    """
    Dashboard 数据服务

    提供统一的数据获取接口，内置缓存支持
    """

    def __init__(self):
        self.cache = dashboard_cache

    def get_market_chart(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
        use_cache: bool = True,
    ) -> list[dict]:
        """获取 K 线数据（带缓存）"""
        cache_key = f"market_chart:{period}:{interval}"

        if use_cache:
            cached = self.cache.get(symbol, cache_key)
            if cached is not None:
                return cached

        data = fetch_market_chart(symbol, period, interval)
        self.cache.set(symbol, cache_key, data, ttl=self.cache.TTL_CHARTS)
        return data

    def get_snapshot(
        self,
        symbol: str,
        asset_type: str,
        use_cache: bool = True,
    ) -> dict:
        """获取快照数据（带缓存）"""
        if use_cache:
            cached = self.cache.get(symbol, "snapshot")
            if cached is not None:
                return cached

        data = fetch_snapshot(symbol, asset_type)
        self.cache.set(symbol, "snapshot", data, ttl=self.cache.TTL_SNAPSHOT)
        return data

    def get_revenue_trend(
        self,
        symbol: str,
        use_cache: bool = True,
    ) -> list[dict]:
        """获取营收趋势（带缓存）"""
        if use_cache:
            cached = self.cache.get(symbol, "revenue_trend")
            if cached is not None:
                return cached

        data = fetch_revenue_trend(symbol)
        self.cache.set(symbol, "revenue_trend", data, ttl=self.cache.TTL_CHARTS)
        return data

    def get_segment_mix(
        self,
        symbol: str,
        use_cache: bool = True,
    ) -> list[dict]:
        """获取分部数据（带缓存）"""
        if use_cache:
            cached = self.cache.get(symbol, "segment_mix")
            if cached is not None:
                return cached

        data = fetch_segment_mix(symbol)
        # FMP 数据更新频率低，缓存 24 小时
        self.cache.set(symbol, "segment_mix", data, ttl=86400)
        return data

    def get_news(
        self,
        symbol: str,
        limit: int = 20,
        use_cache: bool = True,
    ) -> dict[str, list[dict]]:
        """获取新闻数据（带缓存）"""
        if use_cache:
            cached = self.cache.get(symbol, "news")
            if cached is not None:
                return cached

        data = fetch_news(symbol, limit)
        self.cache.set(symbol, "news", data, ttl=self.cache.TTL_NEWS)
        return data

    def get_sector_weights(
        self,
        symbol: str,
        asset_type: str,
        use_cache: bool = True,
    ) -> list[dict]:
        """获取板块权重（带缓存）"""
        if use_cache:
            cached = self.cache.get(symbol, "sector_weights")
            if cached is not None:
                return cached

        data = fetch_sector_weights(symbol, asset_type)
        self.cache.set(symbol, "sector_weights", data, ttl=3600)
        return data

    def get_top_constituents(
        self,
        symbol: str,
        asset_type: str,
        limit: int = 10,
        use_cache: bool = True,
    ) -> list[dict]:
        """获取成分股（带缓存）"""
        if use_cache:
            cached = self.cache.get(symbol, "top_constituents")
            if cached is not None:
                return cached

        data = fetch_top_constituents(symbol, asset_type, limit)
        self.cache.set(symbol, "top_constituents", data, ttl=3600)
        return data

    def get_holdings(
        self,
        symbol: str,
        asset_type: str,
        limit: int = 50,
        use_cache: bool = True,
    ) -> list[dict]:
        """获取持仓（带缓存）"""
        if use_cache:
            cached = self.cache.get(symbol, "holdings")
            if cached is not None:
                return cached

        data = fetch_holdings(symbol, asset_type, limit)
        self.cache.set(symbol, "holdings", data, ttl=3600)
        return data


# ── 单例实例 ──────────────────────────────────────────────────
dashboard_data_service = DashboardDataService()
