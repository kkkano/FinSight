"""
限流系统 - API调用保护

提供：
- 令牌桶限流
- 滑动窗口限流
- 按服务配置
- 限流统计
"""

import time
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from threading import Lock, RLock
from enum import Enum
from collections import deque


class LimitExceededError(Exception):
    """限流超出异常"""

    def __init__(
        self,
        message: str,
        service: str,
        retry_after: float = 0
    ):
        super().__init__(message)
        self.service = service
        self.retry_after = retry_after


class RateLimitStrategy(str, Enum):
    """限流策略"""
    TOKEN_BUCKET = "token_bucket"   # 令牌桶
    SLIDING_WINDOW = "sliding_window"  # 滑动窗口
    FIXED_WINDOW = "fixed_window"   # 固定窗口


@dataclass
class RateLimitConfig:
    """限流配置"""
    requests_per_second: float = 1.0   # 每秒请求数
    burst_size: int = 10               # 突发容量
    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET
    window_size: int = 60              # 滑动窗口大小（秒）


@dataclass
class RateLimitStats:
    """限流统计"""
    total_requests: int = 0
    allowed_requests: int = 0
    rejected_requests: int = 0
    current_tokens: float = 0.0
    last_request_time: float = 0.0

    @property
    def rejection_rate(self) -> float:
        """拒绝率"""
        if self.total_requests == 0:
            return 0.0
        return self.rejected_requests / self.total_requests

    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return {
            "total_requests": self.total_requests,
            "allowed_requests": self.allowed_requests,
            "rejected_requests": self.rejected_requests,
            "rejection_rate": round(self.rejection_rate * 100, 2),
            "current_tokens": round(self.current_tokens, 2),
        }


class TokenBucketLimiter:
    """
    令牌桶限流器

    特点：
    - 允许突发流量
    - 平均速率控制
    - 线程安全
    """

    def __init__(self, config: RateLimitConfig):
        """
        初始化限流器

        Args:
            config: 限流配置
        """
        self.config = config
        self._tokens = float(config.burst_size)
        self._last_refill = time.time()
        self._lock = Lock()
        self._stats = RateLimitStats(current_tokens=self._tokens)

    def _refill(self) -> None:
        """补充令牌"""
        now = time.time()
        elapsed = now - self._last_refill
        new_tokens = elapsed * self.config.requests_per_second

        self._tokens = min(
            self.config.burst_size,
            self._tokens + new_tokens
        )
        self._last_refill = now
        self._stats.current_tokens = self._tokens

    def acquire(self, tokens: int = 1, blocking: bool = False) -> bool:
        """
        获取令牌

        Args:
            tokens: 需要的令牌数
            blocking: 是否阻塞等待

        Returns:
            是否获取成功
        """
        with self._lock:
            self._refill()
            self._stats.total_requests += 1
            self._stats.last_request_time = time.time()

            if self._tokens >= tokens:
                self._tokens -= tokens
                self._stats.allowed_requests += 1
                self._stats.current_tokens = self._tokens
                return True

            if blocking:
                # 计算需要等待的时间
                needed = tokens - self._tokens
                wait_time = needed / self.config.requests_per_second

                self._lock.release()
                time.sleep(wait_time)
                self._lock.acquire()

                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    self._stats.allowed_requests += 1
                    self._stats.current_tokens = self._tokens
                    return True

            self._stats.rejected_requests += 1
            return False

    def get_wait_time(self, tokens: int = 1) -> float:
        """
        获取等待时间

        Args:
            tokens: 需要的令牌数

        Returns:
            需要等待的秒数
        """
        with self._lock:
            self._refill()

            if self._tokens >= tokens:
                return 0.0

            needed = tokens - self._tokens
            return needed / self.config.requests_per_second

    @property
    def stats(self) -> RateLimitStats:
        """获取统计信息"""
        with self._lock:
            return self._stats


class SlidingWindowLimiter:
    """
    滑动窗口限流器

    特点：
    - 精确的时间窗口控制
    - 平滑的流量限制
    - 内存占用随请求量增加
    """

    def __init__(self, config: RateLimitConfig):
        """
        初始化限流器

        Args:
            config: 限流配置
        """
        self.config = config
        self._requests: deque = deque()
        self._lock = Lock()
        self._stats = RateLimitStats()

        # 计算窗口内允许的最大请求数
        self._max_requests = int(
            config.requests_per_second * config.window_size
        )

    def _cleanup(self) -> None:
        """清理过期请求记录"""
        now = time.time()
        window_start = now - self.config.window_size

        while self._requests and self._requests[0] < window_start:
            self._requests.popleft()

    def acquire(self, blocking: bool = False) -> bool:
        """
        尝试获取许可

        Args:
            blocking: 是否阻塞等待

        Returns:
            是否获取成功
        """
        with self._lock:
            self._cleanup()
            self._stats.total_requests += 1
            self._stats.last_request_time = time.time()

            if len(self._requests) < self._max_requests:
                self._requests.append(time.time())
                self._stats.allowed_requests += 1
                return True

            if blocking:
                # 等待最旧的请求过期
                oldest = self._requests[0]
                wait_time = oldest + self.config.window_size - time.time()

                if wait_time > 0:
                    self._lock.release()
                    time.sleep(wait_time + 0.01)
                    self._lock.acquire()

                    self._cleanup()
                    if len(self._requests) < self._max_requests:
                        self._requests.append(time.time())
                        self._stats.allowed_requests += 1
                        return True

            self._stats.rejected_requests += 1
            return False

    def get_wait_time(self) -> float:
        """获取等待时间"""
        with self._lock:
            self._cleanup()

            if len(self._requests) < self._max_requests:
                return 0.0

            oldest = self._requests[0]
            return max(0.0, oldest + self.config.window_size - time.time())

    @property
    def stats(self) -> RateLimitStats:
        """获取统计信息"""
        with self._lock:
            return self._stats


class RateLimiter:
    """
    统一限流器接口

    根据策略选择具体实现。
    """

    def __init__(self, config: RateLimitConfig):
        """
        初始化限流器

        Args:
            config: 限流配置
        """
        self.config = config

        if config.strategy == RateLimitStrategy.TOKEN_BUCKET:
            self._limiter = TokenBucketLimiter(config)
        elif config.strategy == RateLimitStrategy.SLIDING_WINDOW:
            self._limiter = SlidingWindowLimiter(config)
        else:
            self._limiter = TokenBucketLimiter(config)

    def acquire(self, tokens: int = 1, blocking: bool = False) -> bool:
        """获取许可"""
        if hasattr(self._limiter, 'acquire'):
            if isinstance(self._limiter, TokenBucketLimiter):
                return self._limiter.acquire(tokens, blocking)
            else:
                return self._limiter.acquire(blocking)
        return True

    def get_wait_time(self, tokens: int = 1) -> float:
        """获取等待时间"""
        if hasattr(self._limiter, 'get_wait_time'):
            if isinstance(self._limiter, TokenBucketLimiter):
                return self._limiter.get_wait_time(tokens)
            else:
                return self._limiter.get_wait_time()
        return 0.0

    @property
    def stats(self) -> RateLimitStats:
        """获取统计信息"""
        return self._limiter.stats


class RateLimiterManager:
    """
    限流管理器

    管理多个服务的限流器。
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

        self._limiters: Dict[str, RateLimiter] = {}
        self._lock = Lock()
        self._initialized = True

        # 注册默认限流器
        self._setup_default_limiters()

    def _setup_default_limiters(self):
        """设置默认限流器"""
        # Yahoo Finance 限流（保守策略）
        self.register_limiter(
            "yfinance",
            RateLimitConfig(
                requests_per_second=0.5,  # 每2秒1个请求
                burst_size=5,
                strategy=RateLimitStrategy.TOKEN_BUCKET
            )
        )

        # DuckDuckGo 搜索限流
        self.register_limiter(
            "ddgs",
            RateLimitConfig(
                requests_per_second=0.2,  # 每5秒1个请求
                burst_size=3,
                strategy=RateLimitStrategy.TOKEN_BUCKET
            )
        )

        # CNN Fear & Greed 限流
        self.register_limiter(
            "cnn",
            RateLimitConfig(
                requests_per_second=0.1,  # 每10秒1个请求
                burst_size=2,
                strategy=RateLimitStrategy.TOKEN_BUCKET
            )
        )

        # LLM API 限流
        self.register_limiter(
            "llm",
            RateLimitConfig(
                requests_per_second=1.0,  # 每秒1个请求
                burst_size=10,
                strategy=RateLimitStrategy.TOKEN_BUCKET
            )
        )

        # 通用 API 限流
        self.register_limiter(
            "default",
            RateLimitConfig(
                requests_per_second=1.0,
                burst_size=10,
                strategy=RateLimitStrategy.TOKEN_BUCKET
            )
        )

    def register_limiter(
        self,
        service: str,
        config: RateLimitConfig
    ) -> RateLimiter:
        """
        注册限流器

        Args:
            service: 服务名称
            config: 限流配置

        Returns:
            限流器实例
        """
        with self._lock:
            if service not in self._limiters:
                self._limiters[service] = RateLimiter(config)
            return self._limiters[service]

    def get_limiter(self, service: str) -> RateLimiter:
        """
        获取限流器

        Args:
            service: 服务名称

        Returns:
            限流器实例（不存在则返回默认）
        """
        with self._lock:
            return self._limiters.get(service, self._limiters.get("default"))

    def acquire(
        self,
        service: str,
        tokens: int = 1,
        blocking: bool = False
    ) -> bool:
        """
        获取许可

        Args:
            service: 服务名称
            tokens: 需要的令牌数
            blocking: 是否阻塞等待

        Returns:
            是否获取成功
        """
        limiter = self.get_limiter(service)
        if limiter:
            return limiter.acquire(tokens, blocking)
        return True

    def check_or_raise(
        self,
        service: str,
        tokens: int = 1
    ) -> None:
        """
        检查限流，超出则抛出异常

        Args:
            service: 服务名称
            tokens: 需要的令牌数

        Raises:
            LimitExceededError: 超出限流
        """
        limiter = self.get_limiter(service)
        if limiter and not limiter.acquire(tokens):
            wait_time = limiter.get_wait_time(tokens)
            raise LimitExceededError(
                f"服务 {service} 请求频率超限，请等待 {wait_time:.1f} 秒",
                service=service,
                retry_after=wait_time
            )

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有限流器的统计信息"""
        with self._lock:
            return {
                name: limiter.stats.to_dict()
                for name, limiter in self._limiters.items()
            }


# 全局限流管理器
_rate_limiter_manager = None


def get_rate_limiter_manager() -> RateLimiterManager:
    """获取全局限流管理器"""
    global _rate_limiter_manager
    if _rate_limiter_manager is None:
        _rate_limiter_manager = RateLimiterManager()
    return _rate_limiter_manager


def rate_limit(service: str, blocking: bool = True):
    """
    限流装饰器

    Args:
        service: 服务名称
        blocking: 是否阻塞等待

    Returns:
        装饰器函数
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            manager = get_rate_limiter_manager()
            if blocking:
                manager.acquire(service, blocking=True)
            else:
                manager.check_or_raise(service)
            return func(*args, **kwargs)
        return wrapper
    return decorator
