# -*- coding: utf-8 -*-
"""P1-6: 生成端点并发限制（全局 + 单客户端）

公网无认证部署下，防止单 IP 大量并发或全局并发打挂后端/烧光 API 配额。
"""
import pytest

from backend.api.concurrency import ConcurrencyLimiter


class TestConcurrencyLimiter:
    def test_acquire_within_limits(self):
        limiter = ConcurrencyLimiter(max_global=3, max_per_client=2)

        assert limiter.try_acquire("client-a") is True
        assert limiter.try_acquire("client-a") is True
        assert limiter.try_acquire("client-b") is True

    def test_per_client_limit_enforced(self):
        limiter = ConcurrencyLimiter(max_global=10, max_per_client=2)

        assert limiter.try_acquire("client-a") is True
        assert limiter.try_acquire("client-a") is True
        # 第 3 个并发被拒
        assert limiter.try_acquire("client-a") is False
        # 其他客户端不受影响
        assert limiter.try_acquire("client-b") is True

    def test_global_limit_enforced(self):
        limiter = ConcurrencyLimiter(max_global=2, max_per_client=10)

        assert limiter.try_acquire("client-a") is True
        assert limiter.try_acquire("client-b") is True
        # 全局满，第三个客户端也被拒
        assert limiter.try_acquire("client-c") is False

    def test_release_frees_slot(self):
        limiter = ConcurrencyLimiter(max_global=1, max_per_client=1)

        assert limiter.try_acquire("client-a") is True
        assert limiter.try_acquire("client-a") is False

        limiter.release("client-a")
        assert limiter.try_acquire("client-a") is True

    def test_release_never_goes_negative(self):
        limiter = ConcurrencyLimiter(max_global=2, max_per_client=2)

        # 多次 release 不应导致计数为负
        limiter.release("client-a")
        limiter.release("client-a")

        # 仍然遵守上限
        assert limiter.try_acquire("client-a") is True
        assert limiter.try_acquire("client-a") is True
        assert limiter.try_acquire("client-a") is False

    def test_from_env_defaults(self, monkeypatch):
        monkeypatch.delenv("CONCURRENCY_LIMIT_ENABLED", raising=False)
        monkeypatch.delenv("GENERATION_MAX_CONCURRENT", raising=False)
        monkeypatch.delenv("GENERATION_MAX_CONCURRENT_PER_CLIENT", raising=False)

        limiter = ConcurrencyLimiter.from_env()

        assert limiter.enabled is True
        assert limiter.max_global == 10
        assert limiter.max_per_client == 2

    def test_from_env_overrides(self, monkeypatch):
        monkeypatch.setenv("CONCURRENCY_LIMIT_ENABLED", "false")
        monkeypatch.setenv("GENERATION_MAX_CONCURRENT", "5")
        monkeypatch.setenv("GENERATION_MAX_CONCURRENT_PER_CLIENT", "1")

        limiter = ConcurrencyLimiter.from_env()

        assert limiter.enabled is False
        assert limiter.max_global == 5
        assert limiter.max_per_client == 1

    def test_current_usage_snapshot(self):
        """并发状态可查询（供监控/调试）"""
        limiter = ConcurrencyLimiter(max_global=5, max_per_client=3)
        limiter.try_acquire("client-a")
        limiter.try_acquire("client-a")
        limiter.try_acquire("client-b")

        snapshot = limiter.snapshot()
        assert snapshot["global_count"] == 3
        assert snapshot["max_global"] == 5
        assert snapshot["clients"]["client-a"] == 2
        assert snapshot["clients"]["client-b"] == 1


class TestGenerationPathMatcher:
    """P1-6: 只对昂贵的生成端点做并发限制"""

    def test_generation_paths_matched(self):
        from backend.api.concurrency import is_generation_path

        assert is_generation_path("/chat/supervisor") is True
        assert is_generation_path("/chat/supervisor/stream") is True
        assert is_generation_path("/api/execute") is True
        assert is_generation_path("/api/execute/resume") is True

    def test_cheap_paths_not_matched(self):
        from backend.api.concurrency import is_generation_path

        assert is_generation_path("/api/config") is False
        assert is_generation_path("/api/stock/price/AAPL") is False
        assert is_generation_path("/health") is False
        assert is_generation_path("/api/reports/index") is False
