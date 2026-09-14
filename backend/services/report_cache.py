# -*- coding: utf-8 -*-
"""Legacy in-process final-report cache.

The execution path no longer reads or writes this cache. Its historical key
only contained ticker/output mode, while entries contain full markdown,
query-specific reports and trace-derived fields. Reusing those entries across
requests could disclose one user's research to another. The implementation is
kept temporarily for compatibility with maintenance tooling, but the global
runtime instance is hard-disabled until a request- and owner-scoped artifact
cache contract exists.
"""

from __future__ import annotations

from backend.utils.env import env_float as _env_float

import threading
import time
from typing import Any, Optional


class ReportCache:
    """进程内报告缓存（线程安全）。"""

    def __init__(self, ttl_hours: float):
        self.ttl_hours = max(0.0, float(ttl_hours))
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "ReportCache":
        # REPORT_CACHE_TTL_HOURS is deliberately ignored for the global final
        # report cache. A safe replacement needs authenticated owner, canonical
        # request, policy/prompt/data versions and a sanitized artifact schema.
        _env_float("REPORT_CACHE_TTL_HOURS", 0.0)  # parse only for legacy config visibility
        return cls(ttl_hours=0.0)

    @property
    def enabled(self) -> bool:
        return self.ttl_hours > 0

    @staticmethod
    def make_key(ticker: str, output_mode: str) -> str:
        return f"{str(ticker).strip().upper()}:{str(output_mode).strip().lower()}"

    def get(self, ticker: str, output_mode: str) -> Optional[dict[str, Any]]:
        """返回未过期的缓存条目（{'report', 'markdown', 'created_at'}），过期/未命中返回 None。"""
        if not self.enabled:
            return None
        key = self.make_key(ticker, output_mode)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            age_seconds = time.time() - entry["created_at"]
            if age_seconds >= self.ttl_hours * 3600:
                self._store.pop(key, None)
                return None
            return dict(entry)

    def put(
        self,
        ticker: str,
        output_mode: str,
        *,
        report: dict[str, Any],
        markdown: str,
    ) -> None:
        """写入缓存（覆盖同键旧条目）。"""
        if not self.enabled:
            return
        key = self.make_key(ticker, output_mode)
        with self._lock:
            self._store[key] = {
                "report": report,
                "markdown": markdown,
                "created_at": time.time(),
            }

    def invalidate(self, ticker: str | None = None) -> int:
        """失效缓存。指定 ticker 时只清该 ticker；否则全部清空。返回清除数量。"""
        with self._lock:
            if ticker is None:
                count = len(self._store)
                self._store.clear()
                return count
            prefix = f"{str(ticker).strip().upper()}:"
            keys = [key for key in self._store if key.startswith(prefix)]
            for key in keys:
                self._store.pop(key, None)
            return len(keys)

    def snapshot(self) -> dict[str, Any]:
        """当前缓存状态（供监控/调试）。"""
        with self._lock:
            return {
                "ttl_hours": self.ttl_hours,
                "enabled": self.enabled,
                "entries": {
                    key: {"created_at": entry["created_at"]}
                    for key, entry in self._store.items()
                },
            }


_report_cache: ReportCache | None = None
_cache_init_lock = threading.Lock()


def get_report_cache() -> ReportCache:
    """全局报告缓存单例（懒加载，从环境变量读 TTL）。"""
    global _report_cache
    if _report_cache is None:
        with _cache_init_lock:
            if _report_cache is None:
                _report_cache = ReportCache.from_env()
    return _report_cache


def reset_report_cache_for_testing() -> None:
    """测试用：重置全局单例。"""
    global _report_cache
    _report_cache = None
