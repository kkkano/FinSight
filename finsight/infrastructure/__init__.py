"""
基础设施层 - 横切关注点

提供日志、缓存、配置、监控、错误处理等基础服务。

包含：
- logging: 结构化日志系统
- metrics: 指标收集系统
- errors: 错误处理和重试机制
- cache: LRU缓存系统
- rate_limiter: 限流系统
- cost_tracker: 成本追踪系统
- security: 安全中间件和输入验证
"""

from finsight.infrastructure.logging import (
    setup_logging,
    get_logger,
    LogContext,
    log_performance,
    log_async_performance,
    StructuredFormatter,
    SimpleFormatter,
)
from finsight.infrastructure.metrics import (
    MetricsRegistry,
    Counter,
    Gauge,
    Histogram,
    Timer,
    get_metrics_registry,
    increment_counter,
    record_histogram,
    set_gauge,
    time_histogram,
)
from finsight.infrastructure.errors import (
    FinSightError,
    ValidationError,
    ResourceNotFoundError,
    DataUnavailableError,
    RateLimitError,
    LLMError,
    TimeoutError,
    ErrorHandler,
    retry,
    async_retry,
    error_boundary,
)
from finsight.infrastructure.cache import (
    LRUCache,
    CacheConfig,
    CacheStrategy,
    CacheManager,
    get_cache_manager,
    get_cache,
    cached,
)
from finsight.infrastructure.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitStrategy,
    RateLimiterManager,
    get_rate_limiter_manager,
    rate_limit,
    LimitExceededError,
)
from finsight.infrastructure.cost_tracker import (
    CostTracker,
    CostTrackerManager,
    ServiceCost,
    CostTier,
    get_cost_tracker_manager,
    track_cost,
)
from finsight.infrastructure.security import (
    SecurityHeadersMiddleware,
    InputSanitizer,
    RequestValidator,
    SecurityConfig,
    require_safe_input,
)

__all__ = [
    # 日志
    "setup_logging",
    "get_logger",
    "LogContext",
    "log_performance",
    "log_async_performance",
    "StructuredFormatter",
    "SimpleFormatter",
    # 指标
    "MetricsRegistry",
    "Counter",
    "Gauge",
    "Histogram",
    "Timer",
    "get_metrics_registry",
    "increment_counter",
    "record_histogram",
    "set_gauge",
    "time_histogram",
    # 错误
    "FinSightError",
    "ValidationError",
    "ResourceNotFoundError",
    "DataUnavailableError",
    "RateLimitError",
    "LLMError",
    "TimeoutError",
    "ErrorHandler",
    "retry",
    "async_retry",
    "error_boundary",
    # 缓存
    "LRUCache",
    "CacheConfig",
    "CacheStrategy",
    "CacheManager",
    "get_cache_manager",
    "get_cache",
    "cached",
    # 限流
    "RateLimiter",
    "RateLimitConfig",
    "RateLimitStrategy",
    "RateLimiterManager",
    "get_rate_limiter_manager",
    "rate_limit",
    "LimitExceededError",
    # 成本追踪
    "CostTracker",
    "CostTrackerManager",
    "ServiceCost",
    "CostTier",
    "get_cost_tracker_manager",
    "track_cost",
    # 安全
    "SecurityHeadersMiddleware",
    "InputSanitizer",
    "RequestValidator",
    "SecurityConfig",
    "require_safe_input",
]
