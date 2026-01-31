# -*- coding: utf-8 -*-
"""
Global Trace Emitter - 全局事件追踪发射器
用于在整个应用中发射详细的追踪事件，供前端 Console 展示
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class TraceLevel(str, Enum):
    """追踪级别"""
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class TraceCategory(str, Enum):
    """追踪类别"""
    TOOL = "tool"           # 工具调用
    LLM = "llm"             # LLM 调用
    CACHE = "cache"         # 缓存操作
    API = "api"             # 外部 API 调用
    AGENT = "agent"         # Agent 执行
    DATA_SOURCE = "data"    # 数据源操作
    SYSTEM = "system"       # 系统事件


@dataclass
class TraceEvent:
    """追踪事件"""
    event_type: str                         # 事件类型 (tool_start, llm_call, cache_hit, etc.)
    category: TraceCategory                 # 事件类别
    message: str                            # 人类可读消息
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    level: TraceLevel = TraceLevel.INFO
    duration_ms: Optional[int] = None       # 持续时间(毫秒)
    agent: Optional[str] = None             # 关联的 Agent
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外元数据

    def to_sse_dict(self) -> Dict[str, Any]:
        """转换为 SSE 事件格式"""
        return {
            "type": self.event_type,
            "category": self.category.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "level": self.level.value,
            "duration_ms": self.duration_ms,
            "agent": self.agent,
            **self.metadata
        }


class TraceEmitter:
    """
    全局追踪事件发射器

    使用方式:
        emitter = get_trace_emitter()
        emitter.emit_tool_start("search", {"query": "TSLA"})
        # ... 执行工具 ...
        emitter.emit_tool_end("search", result, duration_ms=150)
    """

    _instance: Optional["TraceEmitter"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._listeners: List[Callable[[TraceEvent], None]] = []
        self._async_queue: Optional[asyncio.Queue] = None
        self._enabled = True
        self._min_level = TraceLevel.DEBUG

    @classmethod
    def get_instance(cls) -> "TraceEmitter":
        """获取全局单例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_enabled(self, enabled: bool):
        """启用/禁用追踪"""
        self._enabled = enabled

    def set_min_level(self, level: TraceLevel):
        """设置最小追踪级别"""
        self._min_level = level

    def add_listener(self, listener: Callable[[TraceEvent], None]):
        """添加事件监听器"""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[TraceEvent], None]):
        """移除事件监听器"""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def set_async_queue(self, queue: asyncio.Queue):
        """设置异步队列（用于 SSE 流）"""
        self._async_queue = queue

    def clear_async_queue(self):
        """清除异步队列"""
        self._async_queue = None

    def _emit(self, event: TraceEvent):
        """发射事件"""
        if not self._enabled:
            return

        # 级别过滤
        level_order = [TraceLevel.DEBUG, TraceLevel.INFO, TraceLevel.WARN, TraceLevel.ERROR]
        if level_order.index(event.level) < level_order.index(self._min_level):
            return

        # 通知所有监听器
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:
                logger.debug(f"[TraceEmitter] Listener error: {e}")

        # 放入异步队列
        if self._async_queue:
            try:
                self._async_queue.put_nowait(event)
            except Exception:
                pass

    # ==================== 工具追踪 ====================

    def emit_tool_start(self, tool_name: str, params: Dict[str, Any] = None, agent: str = None):
        """发射工具开始事件"""
        self._emit(TraceEvent(
            event_type="tool_start",
            category=TraceCategory.TOOL,
            message=f"→ {tool_name}",
            agent=agent,
            metadata={"name": tool_name, "params": params or {}}
        ))

    def emit_tool_end(self, tool_name: str, success: bool = True,
                      result_preview: str = None, duration_ms: int = None,
                      error: str = None, agent: str = None):
        """发射工具结束事件"""
        self._emit(TraceEvent(
            event_type="tool_end",
            category=TraceCategory.TOOL,
            message=f"← {tool_name} {'✓' if success else '✗'}",
            level=TraceLevel.INFO if success else TraceLevel.WARN,
            duration_ms=duration_ms,
            agent=agent,
            metadata={
                "name": tool_name,
                "success": success,
                "result_preview": result_preview,
                "error": error
            }
        ))

    @contextmanager
    def trace_tool(self, tool_name: str, params: Dict[str, Any] = None, agent: str = None):
        """工具追踪上下文管理器"""
        self.emit_tool_start(tool_name, params, agent)
        start = time.perf_counter()
        try:
            yield
            duration_ms = int((time.perf_counter() - start) * 1000)
            self.emit_tool_end(tool_name, success=True, duration_ms=duration_ms, agent=agent)
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            self.emit_tool_end(tool_name, success=False, duration_ms=duration_ms, error=str(e), agent=agent)
            raise

    # ==================== LLM 追踪 ====================

    def emit_llm_start(self, model: str = None, prompt_preview: str = None, agent: str = None):
        """发射 LLM 调用开始事件"""
        self._emit(TraceEvent(
            event_type="llm_start",
            category=TraceCategory.LLM,
            message=f"🧠 LLM 调用开始" + (f" ({model})" if model else ""),
            agent=agent,
            metadata={"model": model, "prompt_preview": prompt_preview}
        ))

    def emit_llm_end(self, model: str = None, tokens: int = None,
                     duration_ms: int = None, success: bool = True,
                     error: str = None, agent: str = None):
        """发射 LLM 调用结束事件"""
        msg = f"🧠 LLM 完成"
        if tokens:
            msg += f" ({tokens} tokens)"
        if duration_ms:
            msg += f" [{duration_ms}ms]"
        self._emit(TraceEvent(
            event_type="llm_end",
            category=TraceCategory.LLM,
            message=msg,
            level=TraceLevel.INFO if success else TraceLevel.ERROR,
            duration_ms=duration_ms,
            agent=agent,
            metadata={"model": model, "tokens": tokens, "success": success, "error": error}
        ))

    @contextmanager
    def trace_llm(self, model: str = None, prompt_preview: str = None, agent: str = None):
        """LLM 追踪上下文管理器"""
        self.emit_llm_start(model, prompt_preview, agent)
        start = time.perf_counter()
        try:
            yield
            duration_ms = int((time.perf_counter() - start) * 1000)
            self.emit_llm_end(model=model, duration_ms=duration_ms, success=True, agent=agent)
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            self.emit_llm_end(model=model, duration_ms=duration_ms, success=False, error=str(e), agent=agent)
            raise

    # ==================== 缓存追踪 ====================

    def emit_cache_hit(self, key: str, source: str = None, agent: str = None):
        """发射缓存命中事件"""
        self._emit(TraceEvent(
            event_type="cache_hit",
            category=TraceCategory.CACHE,
            message=f"📦 缓存命中: {key[:30]}..." if len(key) > 30 else f"📦 缓存命中: {key}",
            level=TraceLevel.DEBUG,
            agent=agent,
            metadata={"key": key, "source": source}
        ))

    def emit_cache_miss(self, key: str, source: str = None, agent: str = None):
        """发射缓存未命中事件"""
        self._emit(TraceEvent(
            event_type="cache_miss",
            category=TraceCategory.CACHE,
            message=f"📦 缓存未命中: {key[:30]}..." if len(key) > 30 else f"📦 缓存未命中: {key}",
            level=TraceLevel.DEBUG,
            agent=agent,
            metadata={"key": key, "source": source}
        ))

    def emit_cache_set(self, key: str, ttl: int = None, agent: str = None):
        """发射缓存设置事件"""
        self._emit(TraceEvent(
            event_type="cache_set",
            category=TraceCategory.CACHE,
            message=f"📦 缓存写入: {key[:30]}..." if len(key) > 30 else f"📦 缓存写入: {key}",
            level=TraceLevel.DEBUG,
            agent=agent,
            metadata={"key": key, "ttl": ttl}
        ))

    # ==================== API 追踪 ====================

    def emit_api_call(self, endpoint: str, method: str = "GET",
                      status: int = None, duration_ms: int = None,
                      success: bool = True, error: str = None, agent: str = None):
        """发射 API 调用事件"""
        msg = f"🌐 {method} {endpoint}"
        if status:
            msg += f" → {status}"
        if duration_ms:
            msg += f" [{duration_ms}ms]"
        self._emit(TraceEvent(
            event_type="api_call",
            category=TraceCategory.API,
            message=msg,
            level=TraceLevel.INFO if success else TraceLevel.WARN,
            duration_ms=duration_ms,
            agent=agent,
            metadata={
                "endpoint": endpoint,
                "method": method,
                "status": status,
                "success": success,
                "error": error
            }
        ))

    # ==================== 数据源追踪 ====================

    def emit_data_source_query(self, source_name: str, query_type: str,
                               ticker: str = None, success: bool = True,
                               duration_ms: int = None, error: str = None,
                               fallback: bool = False, agent: str = None):
        """发射数据源查询事件"""
        msg = f"📊 {source_name}: {query_type}"
        if ticker:
            msg += f" ({ticker})"
        if fallback:
            msg += " [回退]"
        if not success:
            msg += " ✗"
        self._emit(TraceEvent(
            event_type="data_source",
            category=TraceCategory.DATA_SOURCE,
            message=msg,
            level=TraceLevel.INFO if success else TraceLevel.WARN,
            duration_ms=duration_ms,
            agent=agent,
            metadata={
                "source": source_name,
                "query_type": query_type,
                "ticker": ticker,
                "success": success,
                "fallback": fallback,
                "error": error
            }
        ))

    # ==================== Agent 追踪 ====================

    def emit_agent_start(self, agent_name: str, query: str = None, ticker: str = None):
        """发射 Agent 开始事件"""
        self._emit(TraceEvent(
            event_type="agent_start",
            category=TraceCategory.AGENT,
            message=f"▶ {agent_name} 启动",
            agent=agent_name,
            metadata={"query": query, "ticker": ticker}
        ))

    def emit_agent_done(self, agent_name: str, success: bool = True,
                        duration_ms: int = None, summary: str = None):
        """发射 Agent 完成事件"""
        self._emit(TraceEvent(
            event_type="agent_done",
            category=TraceCategory.AGENT,
            message=f"■ {agent_name} {'完成' if success else '失败'}",
            level=TraceLevel.INFO if success else TraceLevel.ERROR,
            duration_ms=duration_ms,
            agent=agent_name,
            metadata={"success": success, "summary": summary}
        ))

    def emit_agent_step(self, agent_name: str, step: str, details: Dict[str, Any] = None):
        """发射 Agent 步骤事件"""
        self._emit(TraceEvent(
            event_type="agent_step",
            category=TraceCategory.AGENT,
            message=f"◈ {agent_name}: {step}",
            agent=agent_name,
            metadata={"step": step, **(details or {})}
        ))

    # ==================== Supervisor 追踪 ====================

    def emit_supervisor_start(self, query: str = None, tickers: list = None):
        """发射 Supervisor 开始事件"""
        self._emit(TraceEvent(
            event_type="supervisor_start",
            category=TraceCategory.AGENT,
            message="▶ Supervisor 启动",
            agent="Supervisor",
            metadata={"query": query, "tickers": tickers}
        ))

    def emit_supervisor_done(self, query: str = None, intent: str = None,
                             success: bool = True, duration_ms: int = None):
        """发射 Supervisor 完成事件"""
        self._emit(TraceEvent(
            event_type="supervisor_done",
            category=TraceCategory.AGENT,
            message=f"■ Supervisor {'完成' if success else '失败'}" + (f" [{duration_ms}ms]" if duration_ms else ""),
            level=TraceLevel.INFO if success else TraceLevel.ERROR,
            duration_ms=duration_ms,
            agent="Supervisor",
            metadata={"query": query, "intent": intent, "success": success}
        ))

    # ==================== 系统追踪 ====================

    def emit_system(self, message: str, level: TraceLevel = TraceLevel.INFO,
                    metadata: Dict[str, Any] = None):
        """发射系统事件"""
        self._emit(TraceEvent(
            event_type="system",
            category=TraceCategory.SYSTEM,
            message=message,
            level=level,
            metadata=metadata or {}
        ))


# 便捷函数
def get_trace_emitter() -> TraceEmitter:
    """获取全局追踪发射器实例"""
    return TraceEmitter.get_instance()


def emit_tool_start(tool_name: str, params: Dict[str, Any] = None, agent: str = None):
    """便捷函数：发射工具开始事件"""
    get_trace_emitter().emit_tool_start(tool_name, params, agent)


def emit_tool_end(tool_name: str, success: bool = True, **kwargs):
    """便捷函数：发射工具结束事件"""
    get_trace_emitter().emit_tool_end(tool_name, success, **kwargs)


def emit_llm_start(model: str = None, **kwargs):
    """便捷函数：发射 LLM 开始事件"""
    get_trace_emitter().emit_llm_start(model, **kwargs)


def emit_llm_end(model: str = None, **kwargs):
    """便捷函数：发射 LLM 结束事件"""
    get_trace_emitter().emit_llm_end(model, **kwargs)


def emit_cache_hit(key: str, **kwargs):
    """便捷函数：发射缓存命中事件"""
    get_trace_emitter().emit_cache_hit(key, **kwargs)


def emit_cache_miss(key: str, **kwargs):
    """便捷函数：发射缓存未命中事件"""
    get_trace_emitter().emit_cache_miss(key, **kwargs)


def emit_api_call(endpoint: str, **kwargs):
    """便捷函数：发射 API 调用事件"""
    get_trace_emitter().emit_api_call(endpoint, **kwargs)


def emit_data_source(source_name: str, query_type: str, **kwargs):
    """便捷函数：发射数据源查询事件"""
    get_trace_emitter().emit_data_source_query(source_name, query_type, **kwargs)
