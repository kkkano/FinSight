# -*- coding: utf-8 -*-
"""
全局 LLM API 速率限制器

解决问题：
- LLM 代理服务限制 5分钟内最多请求 18 次
- 多个 Agent 并发调用导致 429 错误
- Forum 综合报告因限流失败

设计思路：
- 使用令牌桶算法控制请求速率
- 可配置的每分钟最大请求数
- 自动等待以避免 429 错误
"""

from __future__ import annotations

import asyncio
import time
import os
import logging
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
    全局 LLM API 速率限制器（令牌桶算法）
    
    配置项（可通过环境变量覆盖）:
    - LLM_RATE_LIMIT_ENABLED: 是否启用速率限制（默认 true）
    - LLM_RATE_LIMIT_RPM: 每分钟最大请求数（默认 15，留 3 次缓冲）
    - LLM_RATE_LIMIT_BURST: 突发请求容量（默认 3）
    """
    
    _instance: Optional["LLMRateLimiter"] = None
    
    def __init__(
        self,
        requests_per_minute: int = None,
        burst_capacity: int = None,
        enabled: bool = None,
    ):
        # 从环境变量读取配置
        self.enabled = enabled if enabled is not None else os.getenv("LLM_RATE_LIMIT_ENABLED", "true").lower() == "true"
        self.requests_per_minute = requests_per_minute or _env_int("LLM_RATE_LIMIT_RPM", 15)  # 保守值，留 3 次缓冲
        self.burst_capacity = burst_capacity or _env_int("LLM_RATE_LIMIT_BURST", 3)
        
        # 令牌桶状态
        self._tokens = float(self.burst_capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        
        # 统计
        self._total_requests = 0
        self._total_waits = 0
        self._total_wait_time = 0.0
        
        logger.info(
            f"[RateLimiter] Initialized: enabled={self.enabled}, "
            f"rpm={self.requests_per_minute}, burst={self.burst_capacity}"
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
    
    def _refill_tokens(self) -> None:
        """根据经过的时间补充令牌"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        
        # 每分钟补充 requests_per_minute 个令牌
        tokens_per_second = self.requests_per_minute / 60.0
        new_tokens = elapsed * tokens_per_second
        
        self._tokens = min(self._tokens + new_tokens, float(self.burst_capacity))
        self._last_refill = now
    
    async def acquire(self, timeout: float = 120.0) -> bool:
        """
        获取一个请求令牌
        
        Args:
            timeout: 最大等待时间（秒）
            
        Returns:
            True 如果成功获取令牌，False 如果超时
        """
        if not self.enabled:
            return True
        
        start_time = time.monotonic()
        
        async with self._lock:
            while True:
                self._refill_tokens()
                
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_requests += 1
                    return True
                
                # 计算需要等待的时间
                tokens_per_second = self.requests_per_minute / 60.0
                tokens_needed = 1.0 - self._tokens
                wait_time = tokens_needed / tokens_per_second
                
                # 检查是否超时
                elapsed = time.monotonic() - start_time
                if elapsed + wait_time > timeout:
                    logger.warning(
                        f"[RateLimiter] Timeout waiting for token: "
                        f"elapsed={elapsed:.1f}s, need={wait_time:.1f}s, timeout={timeout}s"
                    )
                    return False
                
                # 等待
                self._total_waits += 1
                self._total_wait_time += wait_time
                logger.info(
                    f"[RateLimiter] Waiting {wait_time:.1f}s for rate limit "
                    f"(tokens={self._tokens:.2f}, rpm={self.requests_per_minute})"
                )
                
                # 释放锁再等待
                self._lock.release()
                try:
                    await asyncio.sleep(wait_time + 0.1)  # 加 0.1s 缓冲
                finally:
                    await self._lock.acquire()
    
    def snapshot(self) -> dict:
        """获取当前状态快照"""
        return {
            "enabled": self.enabled,
            "requests_per_minute": self.requests_per_minute,
            "burst_capacity": self.burst_capacity,
            "current_tokens": round(self._tokens, 2),
            "total_requests": self._total_requests,
            "total_waits": self._total_waits,
            "total_wait_time": round(self._total_wait_time, 2),
        }


# 全局便捷函数
async def acquire_llm_token(timeout: float = 120.0) -> bool:
    """获取 LLM 调用令牌"""
    return await LLMRateLimiter.get_instance().acquire(timeout)


def get_rate_limiter_stats() -> dict:
    """获取速率限制器统计信息"""
    return LLMRateLimiter.get_instance().snapshot()
