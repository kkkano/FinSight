"""
缓存系统 - 应用性能优化

提供：
- 内存缓存（LRU + TTL）
- 分层缓存策略
- 缓存命中率统计
- 缓存预热机制
"""

import time
import hashlib
import json
from typing import Any, Callable, Dict, Optional, TypeVar, Generic
from dataclasses import dataclass, field
from collections import OrderedDict
from threading import Lock, RLock
from functools import wraps
from enum import Enum


T = TypeVar('T')


class CacheStrategy(str, Enum):
    """缓存策略"""
    SHORT = "short"      # 短期缓存：1-5分钟（实时数据）
    MEDIUM = "medium"    # 中期缓存：15-60分钟（新闻、情绪）
    LONG = "long"        # 长期缓存：1-24小时（公司信息）
    PERMANENT = "permanent"  # 持久缓存（静态数据）


@dataclass
class CacheConfig:
    """缓存配置"""
    max_size: int = 1000           # 最大缓存条目数
    default_ttl: int = 300         # 默认TTL（秒）
    strategy_ttls: Dict[str, int] = field(default_factory=lambda: {
        CacheStrategy.SHORT.value: 60,        # 1分钟
        CacheStrategy.MEDIUM.value: 900,      # 15分钟
        CacheStrategy.LONG.value: 3600,       # 1小时
        CacheStrategy.PERMANENT.value: 86400,  # 24小时
    })


@dataclass
class CacheEntry(Generic[T]):
    """缓存条目"""
    value: T
    created_at: float
    ttl: int
    hits: int = 0

    @property
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.ttl <= 0:  # 永不过期
            return False
        return time.time() - self.created_at > self.ttl

    def touch(self) -> None:
        """记录命中"""
        self.hits += 1


@dataclass
class CacheStats:
    """缓存统计"""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0

    @property
    def hit_rate(self) -> float:
        """命中率"""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "size": self.size,
            "hit_rate": round(self.hit_rate * 100, 2),
        }


class LRUCache(Generic[T]):
    """
    LRU缓存实现

    支持：
    - 最大容量限制
    - TTL过期
    - 线程安全
    - 统计信息
    """

    def __init__(self, config: Optional[CacheConfig] = None):
        """
        初始化缓存

        Args:
            config: 缓存配置
        """
        self.config = config or CacheConfig()
        self._cache: OrderedDict[str, CacheEntry[T]] = OrderedDict()
        self._lock = RLock()
        self._stats = CacheStats()

    def _generate_key(self, *args, **kwargs) -> str:
        """生成缓存键"""
        key_data = {
            "args": args,
            "kwargs": kwargs,
        }
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.md5(key_str.encode()).hexdigest()

    def get(self, key: str) -> Optional[T]:
        """
        获取缓存值

        Args:
            key: 缓存键

        Returns:
            缓存值或None
        """
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._stats.misses += 1
                return None

            if entry.is_expired:
                del self._cache[key]
                self._stats.misses += 1
                self._stats.size = len(self._cache)
                return None

            # 移到末尾（最近使用）
            self._cache.move_to_end(key)
            entry.touch()
            self._stats.hits += 1

            return entry.value

    def set(
        self,
        key: str,
        value: T,
        ttl: Optional[int] = None,
        strategy: Optional[CacheStrategy] = None
    ) -> None:
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），优先于strategy
            strategy: 缓存策略
        """
        with self._lock:
            # 确定TTL
            if ttl is None:
                if strategy:
                    ttl = self.config.strategy_ttls.get(
                        strategy.value,
                        self.config.default_ttl
                    )
                else:
                    ttl = self.config.default_ttl

            # 如果键已存在，先删除
            if key in self._cache:
                del self._cache[key]

            # 检查容量，必要时驱逐
            while len(self._cache) >= self.config.max_size:
                self._cache.popitem(last=False)
                self._stats.evictions += 1

            # 添加新条目
            self._cache[key] = CacheEntry(
                value=value,
                created_at=time.time(),
                ttl=ttl,
            )
            self._stats.size = len(self._cache)

    def delete(self, key: str) -> bool:
        """
        删除缓存条目

        Args:
            key: 缓存键

        Returns:
            是否删除成功
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._stats.size = len(self._cache)
                return True
            return False

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._stats.size = 0

    def cleanup_expired(self) -> int:
        """
        清理过期条目

        Returns:
            清理的条目数
        """
        with self._lock:
            expired_keys = [
                k for k, v in self._cache.items()
                if v.is_expired
            ]
            for key in expired_keys:
                del self._cache[key]

            self._stats.size = len(self._cache)
            return len(expired_keys)

    @property
    def stats(self) -> CacheStats:
        """获取统计信息"""
        with self._lock:
            self._stats.size = len(self._cache)
            return self._stats

    def get_stats_dict(self) -> Dict[str, Any]:
        """获取统计信息字典"""
        return self.stats.to_dict()


def cached(
    cache: LRUCache,
    ttl: Optional[int] = None,
    strategy: Optional[CacheStrategy] = None,
    key_prefix: str = ""
) -> Callable:
    """
    缓存装饰器

    Args:
        cache: 缓存实例
        ttl: 过期时间（秒）
        strategy: 缓存策略
        key_prefix: 键前缀

    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            key_data = {
                "prefix": key_prefix or func.__name__,
                "args": args[1:] if args else args,  # 跳过self
                "kwargs": kwargs,
            }
            key_str = json.dumps(key_data, sort_keys=True, default=str)
            cache_key = hashlib.md5(key_str.encode()).hexdigest()

            # 尝试从缓存获取
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            # 执行函数
            result = func(*args, **kwargs)

            # 存入缓存
            cache.set(cache_key, result, ttl=ttl, strategy=strategy)

            return result

        return wrapper
    return decorator


class CacheManager:
    """
    缓存管理器

    管理多个缓存实例，提供统一接口。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._caches: Dict[str, LRUCache] = {}
        self._lock = Lock()
        self._initialized = True

        # 注册默认缓存
        self._setup_default_caches()

    def _setup_default_caches(self):
        """设置默认缓存"""
        # 股票价格缓存（短期）
        self.register_cache(
            "stock_price",
            CacheConfig(max_size=500, default_ttl=60)
        )

        # 公司信息缓存（长期）
        self.register_cache(
            "company_info",
            CacheConfig(max_size=200, default_ttl=3600)
        )

        # 新闻缓存（中期）
        self.register_cache(
            "news",
            CacheConfig(max_size=300, default_ttl=900)
        )

        # 搜索结果缓存（中期）
        self.register_cache(
            "search",
            CacheConfig(max_size=200, default_ttl=600)
        )

        # 市场情绪缓存（短期）
        self.register_cache(
            "sentiment",
            CacheConfig(max_size=100, default_ttl=300)
        )

    def register_cache(
        self,
        name: str,
        config: Optional[CacheConfig] = None
    ) -> LRUCache:
        """
        注册缓存

        Args:
            name: 缓存名称
            config: 缓存配置

        Returns:
            缓存实例
        """
        with self._lock:
            if name not in self._caches:
                self._caches[name] = LRUCache(config)
            return self._caches[name]

    def get_cache(self, name: str) -> Optional[LRUCache]:
        """
        获取缓存实例

        Args:
            name: 缓存名称

        Returns:
            缓存实例或None
        """
        with self._lock:
            return self._caches.get(name)

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有缓存的统计信息"""
        with self._lock:
            return {
                name: cache.get_stats_dict()
                for name, cache in self._caches.items()
            }

    def cleanup_all_expired(self) -> Dict[str, int]:
        """清理所有缓存的过期条目"""
        with self._lock:
            return {
                name: cache.cleanup_expired()
                for name, cache in self._caches.items()
            }

    def clear_all(self) -> None:
        """清空所有缓存"""
        with self._lock:
            for cache in self._caches.values():
                cache.clear()


# 全局缓存管理器
_cache_manager = None


def get_cache_manager() -> CacheManager:
    """获取全局缓存管理器"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager


def get_cache(name: str) -> Optional[LRUCache]:
    """获取指定缓存"""
    return get_cache_manager().get_cache(name)
