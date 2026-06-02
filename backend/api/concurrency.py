# -*- coding: utf-8 -*-
"""
P1-6: 生成端点并发限制（全局 + 单客户端）

公网无认证部署下，HTTP 频率限流（SimpleRateLimiter）只控制请求次数，
不能阻止"少量请求 × 长时间占用"模式打满后端。本模块对昂贵的生成端点
（Chat / 报告执行）施加并发上限：

- 全局并发上限：GENERATION_MAX_CONCURRENT（默认 10）
- 单客户端并发上限：GENERATION_MAX_CONCURRENT_PER_CLIENT（默认 2）
- 开关：CONCURRENCY_LIMIT_ENABLED（默认 true）

释放时机由 middleware 负责：流式响应在 body 迭代完成后释放。
"""

from __future__ import annotations

import os
import threading
from typing import Dict


def _env_bool(name: str, default: str) -> bool:
    return str(os.getenv(name, default)).strip().lower() not in {"false", "0", "off"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# 昂贵生成端点的路径前缀（这些请求会触发多次 LLM 调用 + 长时间占用）
GENERATION_PATH_PREFIXES: tuple[str, ...] = (
    "/chat/supervisor",
    "/api/execute",
)


def is_generation_path(path: str) -> bool:
    """判断请求路径是否属于昂贵的生成端点。"""
    return any(path.startswith(prefix) for prefix in GENERATION_PATH_PREFIXES)


class ConcurrencyLimiter:
    """全局 + 单客户端 双层并发计数器（线程安全）。"""

    def __init__(self, max_global: int, max_per_client: int, enabled: bool = True):
        self.enabled = enabled
        self.max_global = max(1, int(max_global))
        self.max_per_client = max(1, int(max_per_client))
        self._global_count = 0
        self._per_client: Dict[str, int] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "ConcurrencyLimiter":
        return cls(
            max_global=_env_int("GENERATION_MAX_CONCURRENT", 10),
            max_per_client=_env_int("GENERATION_MAX_CONCURRENT_PER_CLIENT", 2),
            enabled=_env_bool("CONCURRENCY_LIMIT_ENABLED", "true"),
        )

    def try_acquire(self, client_id: str) -> bool:
        """尝试获取并发槽。成功返回 True；超限返回 False（不阻塞等待）。"""
        with self._lock:
            if self._global_count >= self.max_global:
                return False
            if self._per_client.get(client_id, 0) >= self.max_per_client:
                return False
            self._global_count += 1
            self._per_client[client_id] = self._per_client.get(client_id, 0) + 1
            return True

    def release(self, client_id: str) -> None:
        """释放并发槽（幂等：重复释放不会导致计数为负）。"""
        with self._lock:
            self._global_count = max(0, self._global_count - 1)
            remaining = self._per_client.get(client_id, 0) - 1
            if remaining <= 0:
                self._per_client.pop(client_id, None)
            else:
                self._per_client[client_id] = remaining

    def snapshot(self) -> dict:
        """当前并发状态快照（供监控/调试）。"""
        with self._lock:
            return {
                "global_count": self._global_count,
                "max_global": self.max_global,
                "max_per_client": self.max_per_client,
                "clients": dict(self._per_client),
            }
