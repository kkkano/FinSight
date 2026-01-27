"""
缓存、限流、成本追踪单元测试
"""

import pytest
import time
from unittest.mock import Mock, patch
from datetime import datetime

from finsight.infrastructure.cache import (
    LRUCache,
    CacheConfig,
    CacheStrategy,
    CacheManager,
    get_cache_manager,
    cached,
)
from finsight.infrastructure.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitStrategy,
    TokenBucketLimiter,
    SlidingWindowLimiter,
    RateLimiterManager,
    LimitExceededError,
)
from finsight.infrastructure.cost_tracker import (
    CostTracker,
    ServiceCost,
    CostTier,
    CostTrackerManager,
    get_cost_tracker_manager,
)


class TestLRUCache:
    """LRU缓存测试"""

    def test_basic_get_set(self):
        """测试基本的存取操作"""
        cache = LRUCache(CacheConfig(max_size=10, default_ttl=60))

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_miss(self):
        """测试缓存未命中"""
        cache = LRUCache(CacheConfig(max_size=10, default_ttl=60))

        assert cache.get("nonexistent") is None

    def test_cache_expiration(self):
        """测试缓存过期"""
        cache = LRUCache(CacheConfig(max_size=10, default_ttl=1))

        cache.set("key1", "value1", ttl=1)
        assert cache.get("key1") == "value1"

        time.sleep(1.1)
        assert cache.get("key1") is None

    def test_lru_eviction(self):
        """测试LRU驱逐"""
        cache = LRUCache(CacheConfig(max_size=3, default_ttl=60))

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # 访问 key1 使其变为最近使用
        cache.get("key1")

        # 添加新键，应该驱逐 key2（最久未使用）
        cache.set("key4", "value4")

        assert cache.get("key1") == "value1"
        assert cache.get("key2") is None
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"

    def test_cache_stats(self):
        """测试缓存统计"""
        cache = LRUCache(CacheConfig(max_size=10, default_ttl=60))

        cache.set("key1", "value1")
        cache.get("key1")  # 命中
        cache.get("key1")  # 命中
        cache.get("key2")  # 未命中

        stats = cache.stats
        assert stats.hits == 2
        assert stats.misses == 1
        assert stats.size == 1

    def test_cache_strategy_ttl(self):
        """测试缓存策略TTL"""
        cache = LRUCache(CacheConfig(max_size=10))

        cache.set("short", "value", strategy=CacheStrategy.SHORT)
        cache.set("long", "value", strategy=CacheStrategy.LONG)

        # 短期缓存应该更快过期
        # 这里只测试设置是否成功
        assert cache.get("short") == "value"
        assert cache.get("long") == "value"

    def test_cache_delete(self):
        """测试删除缓存"""
        cache = LRUCache(CacheConfig(max_size=10, default_ttl=60))

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        cache.delete("key1")
        assert cache.get("key1") is None

    def test_cache_clear(self):
        """测试清空缓存"""
        cache = LRUCache(CacheConfig(max_size=10, default_ttl=60))

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert cache.stats.size == 0


class TestCacheDecorator:
    """缓存装饰器测试"""

    def test_cached_decorator(self):
        """测试缓存装饰器"""
        cache = LRUCache(CacheConfig(max_size=10, default_ttl=60))
        call_count = 0

        @cached(cache, ttl=60)
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = expensive_function(5)
        result2 = expensive_function(5)

        assert result1 == 10
        assert result2 == 10
        assert call_count == 1  # 只调用一次


class TestCacheManager:
    """缓存管理器测试"""

    def test_register_and_get_cache(self):
        """测试注册和获取缓存"""
        manager = CacheManager()
        cache = manager.register_cache(
            "test_cache",
            CacheConfig(max_size=100)
        )

        assert cache is not None
        assert manager.get_cache("test_cache") is cache

    def test_default_caches(self):
        """测试默认缓存"""
        manager = CacheManager()

        assert manager.get_cache("stock_price") is not None
        assert manager.get_cache("company_info") is not None
        assert manager.get_cache("news") is not None

    def test_get_all_stats(self):
        """测试获取所有统计"""
        manager = CacheManager()
        stats = manager.get_all_stats()

        assert "stock_price" in stats
        assert "hit_rate" in stats["stock_price"]


class TestTokenBucketLimiter:
    """令牌桶限流器测试"""

    def test_acquire_within_limit(self):
        """测试在限制内获取"""
        limiter = TokenBucketLimiter(RateLimitConfig(
            requests_per_second=10,
            burst_size=5
        ))

        # 应该能获取5个令牌（突发容量）
        for _ in range(5):
            assert limiter.acquire()

    def test_acquire_exceeds_limit(self):
        """测试超出限制"""
        limiter = TokenBucketLimiter(RateLimitConfig(
            requests_per_second=10,
            burst_size=2
        ))

        assert limiter.acquire()
        assert limiter.acquire()
        assert not limiter.acquire()  # 第三次应该失败

    def test_token_refill(self):
        """测试令牌补充"""
        limiter = TokenBucketLimiter(RateLimitConfig(
            requests_per_second=10,
            burst_size=1
        ))

        assert limiter.acquire()
        assert not limiter.acquire()

        # 等待令牌补充
        time.sleep(0.15)
        assert limiter.acquire()

    def test_limiter_stats(self):
        """测试限流器统计"""
        limiter = TokenBucketLimiter(RateLimitConfig(
            requests_per_second=10,
            burst_size=2
        ))

        limiter.acquire()
        limiter.acquire()
        limiter.acquire()  # 这次会失败

        stats = limiter.stats
        assert stats.total_requests == 3
        assert stats.allowed_requests == 2
        assert stats.rejected_requests == 1


class TestSlidingWindowLimiter:
    """滑动窗口限流器测试"""

    def test_acquire_within_window(self):
        """测试窗口内获取"""
        limiter = SlidingWindowLimiter(RateLimitConfig(
            requests_per_second=10,
            window_size=1
        ))

        # 窗口内允许 10 个请求
        for _ in range(10):
            assert limiter.acquire()

    def test_acquire_exceeds_window(self):
        """测试超出窗口限制"""
        limiter = SlidingWindowLimiter(RateLimitConfig(
            requests_per_second=5,
            window_size=1
        ))

        for _ in range(5):
            assert limiter.acquire()

        # 第6次应该失败
        assert not limiter.acquire()


class TestRateLimiterManager:
    """限流管理器测试"""

    def test_register_and_get_limiter(self):
        """测试注册和获取限流器"""
        manager = RateLimiterManager()

        limiter = manager.register_limiter(
            "test_service",
            RateLimitConfig(requests_per_second=5)
        )

        assert limiter is not None
        assert manager.get_limiter("test_service") is limiter

    def test_default_limiters(self):
        """测试默认限流器"""
        manager = RateLimiterManager()

        assert manager.get_limiter("yfinance") is not None
        assert manager.get_limiter("ddgs") is not None
        assert manager.get_limiter("default") is not None

    def test_check_or_raise(self):
        """测试检查或抛出异常"""
        manager = RateLimiterManager()
        manager.register_limiter(
            "strict_service",
            RateLimitConfig(requests_per_second=1, burst_size=1)
        )

        # 第一次应该成功
        manager.check_or_raise("strict_service")

        # 第二次应该抛出异常
        with pytest.raises(LimitExceededError):
            manager.check_or_raise("strict_service")


class TestCostTracker:
    """成本追踪器测试"""

    def test_record_call(self):
        """测试记录调用"""
        tracker = CostTracker(ServiceCost(
            service_name="test_service",
            tier=CostTier.LOW,
            cost_per_call=0.01,
            daily_free_quota=0
        ))

        record = tracker.record_call(success=True, duration_ms=100)

        assert record.service == "test_service"
        assert record.cost == 0.01
        assert record.success is True
        assert record.duration_ms == 100

    def test_free_quota(self):
        """测试免费配额"""
        tracker = CostTracker(ServiceCost(
            service_name="test_service",
            tier=CostTier.FREE,
            cost_per_call=0.01,
            daily_free_quota=10
        ))

        # 免费配额内，成本应为0
        for _ in range(10):
            record = tracker.record_call()
            assert record.cost == 0.0

        # 超出配额，开始计费
        record = tracker.record_call()
        assert record.cost == 0.01

    def test_usage_stats(self):
        """测试使用统计"""
        tracker = CostTracker(ServiceCost(
            service_name="test_service",
            tier=CostTier.LOW,
            cost_per_call=0.01,
            daily_free_quota=0
        ))

        tracker.record_call(success=True, duration_ms=100)
        tracker.record_call(success=True, duration_ms=200)
        tracker.record_call(success=False, duration_ms=50)

        stats = tracker.get_stats()
        assert stats.total_calls == 3
        assert stats.successful_calls == 2
        assert stats.failed_calls == 1
        assert stats.total_cost == 0.03


class TestCostTrackerManager:
    """成本追踪管理器测试"""

    def test_register_and_get_tracker(self):
        """测试注册和获取追踪器"""
        manager = CostTrackerManager()

        tracker = manager.register_tracker(ServiceCost(
            service_name="custom_service",
            tier=CostTier.MEDIUM,
            cost_per_call=0.05
        ))

        assert tracker is not None
        assert manager.get_tracker("custom_service") is tracker

    def test_default_trackers(self):
        """测试默认追踪器"""
        manager = CostTrackerManager()

        assert manager.get_tracker("yfinance") is not None
        assert manager.get_tracker("ddgs") is not None
        assert manager.get_tracker("openai") is not None

    def test_record_call_through_manager(self):
        """测试通过管理器记录调用"""
        manager = CostTrackerManager()

        record = manager.record_call(
            service="yfinance",
            success=True,
            duration_ms=150
        )

        assert record is not None
        assert record.service == "yfinance"

    def test_get_total_cost(self):
        """测试获取总成本"""
        manager = CostTrackerManager()
        manager.record_call("yfinance")
        manager.record_call("ddgs")

        total = manager.get_total_cost()
        assert "total" in total
        assert "today" in total
        assert "by_service" in total

    def test_generate_usage_report(self):
        """测试生成使用报告"""
        manager = CostTrackerManager()
        report = manager.generate_usage_report()

        assert "generated_at" in report
        assert "summary" in report
        assert "services" in report


class TestAlertCallback:
    """告警回调测试"""

    def test_budget_alert(self):
        """测试预算告警"""
        alerts = []

        def alert_callback(alert_type, current, threshold):
            alerts.append((alert_type, current, threshold))

        tracker = CostTracker(ServiceCost(
            service_name="expensive_service",
            tier=CostTier.PREMIUM,
            cost_per_call=1.0,
            daily_free_quota=0,
            monthly_budget=5.0
        ))
        tracker.add_alert_callback(alert_callback)

        # 触发80%告警
        for _ in range(4):
            tracker.record_call()

        assert len(alerts) == 1
        assert alerts[0][0] == "budget_warning"

        # 触发100%告警
        tracker.record_call()
        assert len(alerts) == 2
        assert alerts[1][0] == "budget_exceeded"
