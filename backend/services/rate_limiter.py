# -*- coding: utf-8 -*-
"""
分层 LLM API 速率限制器 — 全局桶 + 每 agent 保底配额

设计思路 (ADR-004):
- 全局令牌桶控制整体请求速率，防止 LLM 代理服务 429
- 每个 agent 在 60s 窗口内保证至少获得 MIN_TOKENS_PER_AGENT 个令牌
- 即使全局桶耗尽，未达保底配额的 agent 仍可获取令牌（防饿死）
- 向后兼容：agent_name=None 时退化为纯全局桶行为
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """从环境变量获取整数配置"""
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    """从环境变量获取浮点数配置"""
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default


class LLMRateLimiter:
    """
    分层令牌桶速率限制器

    配置项（可通过环境变量覆盖）:
    - LLM_RATE_LIMIT_ENABLED: 是否启用 (默认 true)
    - LLM_RATE_LIMIT_RPM: 每分钟最大请求数 (默认 60)
    - LLM_RATE_LIMIT_BURST: 突发请求容量 (默认 15)
    - LLM_RATE_LIMIT_MIN_TOKENS_PER_AGENT: 每 agent 60s 保底配额 (默认 8)
    - LLM_RATE_LIMIT_AGENT_WINDOW_SECONDS: 保底配额滑动窗口 (默认 60)
    """

    _instance: Optional["LLMRateLimiter"] = None

    def __init__(
        self,
        *,
        requests_per_minute: int | None = None,
        burst_capacity: int | None = None,
        enabled: bool | None = None,
        min_tokens_per_agent: int | None = None,
        agent_window_seconds: float | None = None,
    ):
        self.enabled = (
            enabled
            if enabled is not None
            else os.getenv("LLM_RATE_LIMIT_ENABLED", "true").lower() == "true"
        )
        self.requests_per_minute = (
            requests_per_minute
            if requests_per_minute is not None
            else _env_int("LLM_RATE_LIMIT_RPM", 60)
        )
        self.burst_capacity = (
            burst_capacity
            if burst_capacity is not None
            else _env_int("LLM_RATE_LIMIT_BURST", 15)
        )
        self.min_tokens_per_agent = (
            min_tokens_per_agent
            if min_tokens_per_agent is not None
            else _env_int("LLM_RATE_LIMIT_MIN_TOKENS_PER_AGENT", 8)
        )
        self.agent_window_seconds = (
            agent_window_seconds
            if agent_window_seconds is not None
            else _env_float("LLM_RATE_LIMIT_AGENT_WINDOW_SECONDS", 60.0)
        )

        # --- 全局令牌桶状态 ---
        self._tokens = float(self.burst_capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

        # --- 每 agent 保底配额跟踪 ---
        # agent_name -> [timestamp, timestamp, ...]
        self._agent_usage: dict[str, list[float]] = defaultdict(list)

        # --- 统计 ---
        self._total_requests = 0
        self._total_waits = 0
        self._total_wait_time = 0.0
        self._guaranteed_grants = 0

        logger.info(
            "[RateLimiter] Initialized: enabled=%s, rpm=%d, burst=%d, "
            "min_tokens_per_agent=%d, agent_window=%.0fs",
            self.enabled,
            self.requests_per_minute,
            self.burst_capacity,
            self.min_tokens_per_agent,
            self.agent_window_seconds,
        )

    @classmethod
    def get_instance(cls) -> "LLMRateLimiter":
        """获取全局单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（用于测试）"""
        cls._instance = None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _refill_tokens(self) -> None:
        """根据经过的时间补充全局令牌"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        tokens_per_second = self.requests_per_minute / 60.0
        new_tokens = elapsed * tokens_per_second
        self._tokens = min(self._tokens + new_tokens, float(self.burst_capacity))
        self._last_refill = now

    def _prune_agent_window(self, agent_name: str, now: float) -> int:
        """清理过期时间戳，返回窗口内已用令牌数"""
        cutoff = now - self.agent_window_seconds
        fresh = [t for t in self._agent_usage[agent_name] if t > cutoff]
        self._agent_usage[agent_name] = fresh
        return len(fresh)

    def _agent_has_guaranteed_quota(self, agent_name: str | None) -> bool:
        """检查 agent 是否还有保底配额可用"""
        if not agent_name or self.min_tokens_per_agent <= 0:
            return False
        now = time.monotonic()
        usage_count = self._prune_agent_window(agent_name, now)
        return usage_count < self.min_tokens_per_agent

    def _record_agent_usage(self, agent_name: str | None) -> None:
        """记录 agent 使用一次令牌"""
        if agent_name:
            self._agent_usage[agent_name].append(time.monotonic())

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def acquire(
        self,
        timeout: float = 120.0,
        agent_name: str | None = None,
    ) -> bool:
        """
        获取一个请求令牌

        策略（分层）:
        1. 全局桶有令牌 → 直接扣减
        2. 全局桶为空，但 agent 未达保底配额 → 保底放行
        3. 都不满足 → 等待全局桶补充

        Args:
            timeout: 最大等待时间（秒）
            agent_name: 调用方 agent 名称（用于保底配额跟踪）

        Returns:
            True 如果成功获取令牌，False 如果超时
        """
        if not self.enabled:
            self._record_agent_usage(agent_name)
            return True

        start_time = time.monotonic()

        async with self._lock:
            while True:
                self._refill_tokens()

                # 路径 1: 全局桶有令牌
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_requests += 1
                    self._record_agent_usage(agent_name)
                    return True

                # 路径 2: 保底配额放行
                if self._agent_has_guaranteed_quota(agent_name):
                    self._total_requests += 1
                    self._guaranteed_grants += 1
                    self._record_agent_usage(agent_name)
                    logger.info(
                        "[RateLimiter] Guaranteed quota grant for agent=%s "
                        "(global bucket empty, used %d/%d in window)",
                        agent_name,
                        self._prune_agent_window(agent_name, time.monotonic()),
                        self.min_tokens_per_agent,
                    )
                    return True

                # 路径 3: 等待全局桶补充
                tokens_per_second = self.requests_per_minute / 60.0
                if tokens_per_second <= 0:
                    return False
                tokens_needed = 1.0 - self._tokens
                wait_time = tokens_needed / tokens_per_second

                elapsed = time.monotonic() - start_time
                if elapsed + wait_time > timeout:
                    logger.warning(
                        "[RateLimiter] Timeout (agent=%s): elapsed=%.1fs, "
                        "need=%.1fs, timeout=%.0fs",
                        agent_name or "unknown",
                        elapsed,
                        wait_time,
                        timeout,
                    )
                    return False

                self._total_waits += 1
                self._total_wait_time += wait_time
                logger.info(
                    "[RateLimiter] Waiting %.1fs (agent=%s, tokens=%.2f, rpm=%d)",
                    wait_time,
                    agent_name or "unknown",
                    self._tokens,
                    self.requests_per_minute,
                )

                # 释放锁再等待，让其他协程有机会获取
                self._lock.release()
                try:
                    await asyncio.sleep(wait_time + 0.1)
                finally:
                    await self._lock.acquire()

    def snapshot(self) -> dict:
        """获取当前状态快照（含 per-agent 统计）"""
        now = time.monotonic()
        agent_stats: dict[str, dict] = {}
        for name in list(self._agent_usage.keys()):
            cutoff = now - self.agent_window_seconds
            recent = [t for t in self._agent_usage[name] if t > cutoff]
            agent_stats[name] = {
                "usage_in_window": len(recent),
                "guaranteed_remaining": max(
                    0, self.min_tokens_per_agent - len(recent)
                ),
            }

        return {
            "enabled": self.enabled,
            "requests_per_minute": self.requests_per_minute,
            "burst_capacity": self.burst_capacity,
            "min_tokens_per_agent": self.min_tokens_per_agent,
            "current_tokens": round(self._tokens, 2),
            "total_requests": self._total_requests,
            "total_waits": self._total_waits,
            "total_wait_time": round(self._total_wait_time, 2),
            "guaranteed_grants": self._guaranteed_grants,
            "agent_stats": agent_stats,
        }


# ------------------------------------------------------------------
# 全局便捷函数
# ------------------------------------------------------------------


async def acquire_llm_token(
    timeout: float = 120.0,
    agent_name: str | None = None,
) -> bool:
    """获取 LLM 调用令牌（全局桶 + agent 保底配额）"""
    return await LLMRateLimiter.get_instance().acquire(
        timeout=timeout, agent_name=agent_name
    )


def get_rate_limiter_stats() -> dict:
    """获取速率限制器统计信息"""
    return LLMRateLimiter.get_instance().snapshot()
