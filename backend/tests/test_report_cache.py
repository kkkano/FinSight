# -*- coding: utf-8 -*-
"""P1-7: 报告级缓存（同 ticker + 12h TTL）"""
import time

import pytest

from backend.services.report_cache import (
    ReportCache,
    get_report_cache,
    reset_report_cache_for_testing,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_report_cache_for_testing()
    yield
    reset_report_cache_for_testing()


class TestReportCache:
    def test_put_and_get(self):
        cache = ReportCache(ttl_hours=12)
        report = {"report_id": "rpt-1", "ticker": "AAPL"}

        cache.put("AAPL", "investment_report", report=report, markdown="# AAPL Report")
        entry = cache.get("AAPL", "investment_report")

        assert entry is not None
        assert entry["report"]["report_id"] == "rpt-1"
        assert entry["markdown"] == "# AAPL Report"

    def test_key_normalization(self):
        """ticker 大小写 / output_mode 大小写不敏感"""
        cache = ReportCache(ttl_hours=12)
        cache.put("aapl", "Investment_Report", report={"x": 1}, markdown="md")

        assert cache.get("AAPL", "investment_report") is not None
        assert cache.get("Aapl", "INVESTMENT_REPORT") is not None

    def test_miss_returns_none(self):
        cache = ReportCache(ttl_hours=12)
        assert cache.get("TSLA", "investment_report") is None

    def test_expired_entry_returns_none(self, monkeypatch):
        cache = ReportCache(ttl_hours=1)
        cache.put("AAPL", "investment_report", report={"x": 1}, markdown="md")

        # 模拟时间前进 2 小时
        real_time = time.time()
        monkeypatch.setattr(time, "time", lambda: real_time + 2 * 3600)

        assert cache.get("AAPL", "investment_report") is None

    def test_ttl_zero_disables_cache(self):
        cache = ReportCache(ttl_hours=0)
        cache.put("AAPL", "investment_report", report={"x": 1}, markdown="md")

        assert cache.enabled is False
        assert cache.get("AAPL", "investment_report") is None

    def test_invalidate_specific_ticker(self):
        cache = ReportCache(ttl_hours=12)
        cache.put("AAPL", "investment_report", report={"x": 1}, markdown="a")
        cache.put("TSLA", "investment_report", report={"x": 2}, markdown="b")

        removed = cache.invalidate("AAPL")

        assert removed == 1
        assert cache.get("AAPL", "investment_report") is None
        assert cache.get("TSLA", "investment_report") is not None

    def test_invalidate_all(self):
        cache = ReportCache(ttl_hours=12)
        cache.put("AAPL", "investment_report", report={"x": 1}, markdown="a")
        cache.put("TSLA", "investment_report", report={"x": 2}, markdown="b")

        removed = cache.invalidate()

        assert removed == 2
        assert cache.get("AAPL", "investment_report") is None

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("REPORT_CACHE_TTL_HOURS", "6")
        cache = ReportCache.from_env()
        assert cache.ttl_hours == 0.0
        assert cache.enabled is False

    def test_global_singleton(self):
        cache1 = get_report_cache()
        cache2 = get_report_cache()
        assert cache1 is cache2


class TestCacheTickerResolution:
    """P1-7: 只有 investment_report + 明确单 ticker 才走缓存"""


class TestPipelineCacheIntegration:
    """Final reports must never cross request/user boundaries via legacy cache."""

    @staticmethod
    def _run(coro):
        import asyncio

        return asyncio.run(coro)

    @staticmethod
    async def _collect_events(generator):
        items = []
        async for item in generator:
            if isinstance(item, dict) and item.get("type") == "keep-alive":
                continue
            items.append(item)
        return items
