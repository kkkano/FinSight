# -*- coding: utf-8 -*-
"""
P1-7: 报告级缓存（同 ticker + TTL）

热门股票的投资报告重复生成是最大的成本浪费来源（每次 ~20 次 LLM 调用）。
本模块对成功生成的 investment_report 按 ticker 缓存：

- 缓存键：ticker（大写标准化）+ output_mode
- TTL：REPORT_CACHE_TTL_HOURS（默认 12 小时，0 = 禁用缓存）
- 存储：进程内存（重启即失效——缓存只是省钱手段，不是持久层）
- 命中时执行管线直接回放缓存报告，并在 done 事件标记 cached=true
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Optional


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class ReportCache:
    """进程内报告缓存（线程安全）。"""

    def __init__(self, ttl_hours: float):
        self.ttl_hours = max(0.0, float(ttl_hours))
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "ReportCache":
        return cls(ttl_hours=_env_float("REPORT_CACHE_TTL_HOURS", 12.0))

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
