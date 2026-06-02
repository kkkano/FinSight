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
        assert cache.ttl_hours == 6.0

        monkeypatch.setenv("REPORT_CACHE_TTL_HOURS", "0")
        cache_disabled = ReportCache.from_env()
        assert cache_disabled.enabled is False

    def test_global_singleton(self):
        cache1 = get_report_cache()
        cache2 = get_report_cache()
        assert cache1 is cache2


class TestCacheTickerResolution:
    """P1-7: 只有 investment_report + 明确单 ticker 才走缓存"""

    def test_single_ticker_override_resolved(self):
        from backend.services.execution_service import _resolve_cache_ticker

        ticker = _resolve_cache_ticker(
            {"tickers_override": ["AAPL"]}, "investment_report"
        )
        assert ticker == "AAPL"

    def test_multi_ticker_not_cached(self):
        from backend.services.execution_service import _resolve_cache_ticker

        ticker = _resolve_cache_ticker(
            {"tickers_override": ["AAPL", "TSLA"]}, "investment_report"
        )
        assert ticker is None

    def test_non_report_mode_not_cached(self):
        from backend.services.execution_service import _resolve_cache_ticker

        ticker = _resolve_cache_ticker({"tickers_override": ["AAPL"]}, None)
        assert ticker is None

        ticker2 = _resolve_cache_ticker({"tickers_override": ["AAPL"]}, "brief")
        assert ticker2 is None

    def test_no_ticker_override_not_cached(self):
        from backend.services.execution_service import _resolve_cache_ticker

        ticker = _resolve_cache_ticker({"active_symbol": "AAPL"}, "investment_report")
        assert ticker is None


class TestPipelineCacheIntegration:
    """P1-7: 缓存命中时执行管线直接回放，不跑图"""

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

    def test_cache_hit_replays_without_running_graph(self):
        import importlib

        from backend.services.report_cache import get_report_cache

        execution_service = importlib.import_module("backend.services.execution_service")

        # 预先写入缓存
        cached_report = {
            "report_id": "rpt-cached-1",
            "ticker": "AAPL",
            "title": "Cached AAPL report",
            "report_quality": {"state": "pass", "reasons": []},
        }
        get_report_cache().put(
            "AAPL", "investment_report",
            report=cached_report, markdown="# Cached AAPL Report\n内容",
        )

        graph_runner_called = []

        async def _fake_get_graph_runner():
            graph_runner_called.append(True)
            return object()

        deps = execution_service.ExecutionDeps(
            get_graph_runner=_fake_get_graph_runner,
            schedule_report_index=lambda **kwargs: None,
            update_session_context=lambda **kwargs: None,
            redact_sensitive_payload=lambda payload: payload,
            is_raw_trace_event=lambda payload: False,
            contract_info=lambda: {"chat_response": "chat.response.v1"},
            sse_event_schema_version="chat.sse.v1",
        )

        events = self._run(
            self._collect_events(
                execution_service.run_graph_pipeline(
                    deps=deps,
                    query="生成 AAPL 投资报告",
                    thread_id="tenant:user:thread",
                    output_mode="investment_report",
                    source="execute_test",
                    ui_context={"tickers_override": ["AAPL"]},
                )
            )
        )

        # 图不应该被执行（缓存命中直接回放）
        assert not graph_runner_called, "graph runner should NOT be called on cache hit"

        done_events = [
            event for event in events
            if isinstance(event, dict) and event.get("type") == "done"
        ]
        assert done_events, "cached replay should emit done event"
        done = done_events[0]
        assert done.get("cached") is True
        assert done.get("report", {}).get("report_id") == "rpt-cached-1"

        # markdown 应该以 token 流形式回放
        token_events = [
            event for event in events
            if isinstance(event, dict) and event.get("type") == "token"
        ]
        assert token_events, "cached markdown should be streamed as tokens"
        full_text = "".join(event.get("content", "") for event in token_events)
        assert "Cached AAPL Report" in full_text
