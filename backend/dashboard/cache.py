"""
Dashboard 数据缓存 - TTL 内存缓存

提供简易的内存缓存机制，避免每次 Dashboard 请求都重新拉取数据。

TTL 策略：
- snapshot: 60秒（高频变化的 KPI 数据）
- charts: 300秒（图表数据相对稳定）
- news: 30秒（新闻需要较高时效性）
"""
import time
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DashboardCache:
    """
    简易 TTL 缓存

    缓存键格式: dashboard:{symbol}:{data_type}

    使用示例:
        cache = DashboardCache()
        cache.set("AAPL", "snapshot", {"price": 180.5}, ttl=60)
        data = cache.get("AAPL", "snapshot")  # 60秒内返回数据，之后返回 None
    """

    # ── TTL 配置（秒） ──────────────────────────────────
    TTL_SNAPSHOT = 60    # KPI 快照
    TTL_CHARTS = 300     # 图表数据
    TTL_NEWS = 300       # 新闻数据（5 分钟，多源回退链较慢）
    TTL_SEGMENT_MIX = 86400    # 分部收入（FMP 数据更新频率低）
    TTL_SECTOR_WEIGHTS = 3600  # 板块权重
    TTL_CONSTITUENTS = 3600    # 成分股
    TTL_HOLDINGS = 3600        # 持仓数据
    TTL_VALUATION = 300        # Valuation metrics (5 min)
    TTL_FINANCIALS = 3600      # Financial statements (1 hour)
    TTL_TECHNICALS = 60        # Technical indicators (1 min)
    TTL_PEERS = 3600           # Peer comparison (1 hour)
    TTL_INSIGHTS = 3600        # AI insights (1 hour)
    TTL_INSIGHTS_STALE = 14400 # AI insights stale window (4 hours)

    def __init__(self) -> None:
        """初始化缓存存储"""
        self._store: dict[str, tuple[float, Any]] = {}

    def _key(self, symbol: str, data_type: str) -> str:
        """
        生成缓存键

        Args:
            symbol: 资产代码
            data_type: 数据类型（snapshot, charts, news 等）

        Returns:
            str: 标准化的缓存键
        """
        return f"dashboard:{symbol.upper()}:{data_type}"

    def get(self, symbol: str, data_type: str) -> Optional[Any]:
        """
        获取缓存数据

        Args:
            symbol: 资产代码
            data_type: 数据类型

        Returns:
            Any | None: 缓存数据，若不存在或已过期则返回 None
        """
        key = self._key(symbol, data_type)
        entry = self._store.get(key)

        if entry is None:
            return None

        expires_at, value = entry

        # 检查是否过期
        if time.time() > expires_at:
            del self._store[key]
            logger.debug(f"Cache expired: {key}")
            return None

        logger.debug(f"Cache hit: {key}")
        return value

    def get_with_stale(
        self,
        symbol: str,
        data_type: str,
        stale_ttl: int = 14400,
    ) -> tuple[Optional[Any], bool]:
        """
        获取缓存数据（支持 stale-while-revalidate 模式）

        如果数据在 stale_ttl 内（即使已过 TTL），仍返回数据并标记 is_stale=True。

        Args:
            symbol: 资产代码
            data_type: 数据类型
            stale_ttl: 过期后仍可返回的最大秒数

        Returns:
            (data, is_stale): data 为缓存数据或 None; is_stale 表示是否已过期
        """
        key = self._key(symbol, data_type)
        entry = self._store.get(key)

        if entry is None:
            return None, False

        expires_at, value = entry
        now = time.time()

        if now <= expires_at:
            # Fresh
            logger.debug(f"Cache hit (fresh): {key}")
            return value, False

        # Expired but within stale window?
        stale_deadline = expires_at + stale_ttl
        if now <= stale_deadline:
            logger.debug(f"Cache hit (stale): {key}")
            return value, True

        # Beyond stale window — treat as miss
        del self._store[key]
        logger.debug(f"Cache expired beyond stale window: {key}")
        return None, False

    def set(
        self,
        symbol: str,
        data_type: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> None:
        """
        设置缓存数据

        Args:
            symbol: 资产代码
            data_type: 数据类型
            value: 要缓存的数据
            ttl: 过期时间（秒），默认使用 TTL_CHARTS
        """
        if ttl is None:
            # 根据数据类型选择默认 TTL
            ttl_map = {
                "snapshot": self.TTL_SNAPSHOT,
                "charts": self.TTL_CHARTS,
                "news": self.TTL_NEWS,
                "segment_mix": self.TTL_SEGMENT_MIX,
                "sector_weights": self.TTL_SECTOR_WEIGHTS,
                "top_constituents": self.TTL_CONSTITUENTS,
                "holdings": self.TTL_HOLDINGS,
                "valuation": self.TTL_VALUATION,
                "financials": self.TTL_FINANCIALS,
                "technicals": self.TTL_TECHNICALS,
                "peers": self.TTL_PEERS,
            }
            ttl = ttl_map.get(data_type, self.TTL_CHARTS)

        key = self._key(symbol, data_type)
        expires_at = time.time() + ttl
        self._store[key] = (expires_at, value)
        logger.debug(f"Cache set: {key}, TTL={ttl}s")

    def invalidate(self, symbol: str) -> None:
        """
        使指定 symbol 的所有缓存失效

        Args:
            symbol: 资产代码
        """
        prefix = f"dashboard:{symbol.upper()}:"
        keys_to_delete = [k for k in self._store if k.startswith(prefix)]

        for key in keys_to_delete:
            del self._store[key]

        if keys_to_delete:
            logger.debug(f"Invalidated {len(keys_to_delete)} cache entries for {symbol}")

    def invalidate_type(self, data_type: str) -> None:
        """
        使指定数据类型的所有缓存失效

        Args:
            data_type: 数据类型
        """
        suffix = f":{data_type}"
        keys_to_delete = [k for k in self._store if k.endswith(suffix)]

        for key in keys_to_delete:
            del self._store[key]

        if keys_to_delete:
            logger.debug(f"Invalidated {len(keys_to_delete)} cache entries for type {data_type}")

    def clear(self) -> None:
        """清空所有缓存"""
        count = len(self._store)
        self._store.clear()
        logger.debug(f"Cache cleared: {count} entries removed")

    def stats(self) -> dict[str, Any]:
        """
        获取缓存统计信息

        Returns:
            dict: 包含缓存条目数量和各类型统计
        """
        now = time.time()
        total = len(self._store)
        expired = sum(1 for _, (exp, _) in self._store.items() if now > exp)
        active = total - expired

        # 按数据类型统计
        type_counts: dict[str, int] = {}
        for key in self._store:
            parts = key.split(":")
            if len(parts) >= 3:
                data_type = parts[-1]
                type_counts[data_type] = type_counts.get(data_type, 0) + 1

        return {
            "total_entries": total,
            "active_entries": active,
            "expired_entries": expired,
            "by_type": type_counts,
        }

    def cleanup(self) -> int:
        """
        清理过期的缓存条目

        Returns:
            int: 清理的条目数量
        """
        now = time.time()
        expired_keys = [
            key for key, (expires_at, _) in self._store.items()
            if now > expires_at
        ]

        for key in expired_keys:
            del self._store[key]

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

        return len(expired_keys)


# ── 单例实例 ──────────────────────────────────────────────
dashboard_cache = DashboardCache()
