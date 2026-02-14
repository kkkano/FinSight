# -*- coding: utf-8 -*-
"""LangFuse 全链路追踪集成。

提供三层追踪能力：
  1. 请求级 Trace — 每次用户请求创建顶层 trace（@observe 装饰器）
  2. 节点级 Span  — graph 每个节点自动创建子 span（start_as_current_span）
  3. LLM 级 Generation — LLM 调用自动嵌套到当前 span（CallbackHandler 自动检测上下文）

数据流：
  @observe (trace) → start_as_current_span (node span) → CallbackHandler (LLM generation)

环境变量：
    LANGFUSE_ENABLED: "true" 启用（默认 "false"）
    LANGFUSE_PUBLIC_KEY: LangFuse public key
    LANGFUSE_SECRET_KEY: LangFuse secret key
    LANGFUSE_HOST: LangFuse server URL（默认 "https://cloud.langfuse.com"）
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

_langfuse_client: Any | None = None
_init_attempted: bool = False


# ==================== 环境变量工具 ====================

def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


# ==================== 全局 Client 初始化 ====================

def _ensure_client() -> Any | None:
    """初始化 Langfuse 全局 client（单次执行）。返回 Langfuse 实例或 None。"""
    global _langfuse_client, _init_attempted

    if _init_attempted:
        return _langfuse_client
    _init_attempted = True

    if not _env_bool("LANGFUSE_ENABLED", False):
        logger.debug("[LangFuse] 已禁用（设置 LANGFUSE_ENABLED=true 启用）")
        return None

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").strip()

    if not public_key or not secret_key:
        logger.warning("[LangFuse] 已启用但缺少 LANGFUSE_PUBLIC_KEY 或 LANGFUSE_SECRET_KEY")
        return None

    # langfuse v3 通过环境变量读取密钥和 host
    os.environ.setdefault("LANGFUSE_SECRET_KEY", secret_key)
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", public_key)
    os.environ.setdefault("LANGFUSE_HOST", host)

    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )

        if not _langfuse_client.auth_check():
            logger.warning("[LangFuse] auth_check 失败 — 请检查 API Key")
            _langfuse_client = None
            return None

        logger.info("[LangFuse] 全链路追踪已启用 → %s", host)
        return _langfuse_client

    except ImportError:
        logger.info("[LangFuse] langfuse 未安装 — pip install langfuse")
        return None
    except Exception as exc:
        logger.warning("[LangFuse] 初始化失败: %s", exc)
        return None


def get_langfuse_client() -> Any | None:
    """获取 Langfuse 全局 client 单例。未配置时返回 None，不抛异常。"""
    return _ensure_client()


def get_langfuse_client_safe() -> Any | None:
    """获取 Langfuse client，吞掉所有异常。供 trace.py 等热路径使用。"""
    try:
        return _ensure_client()
    except Exception:
        return None


# ==================== LangChain CallbackHandler ====================

def get_langfuse_callback() -> Any | None:
    """返回一个 LangChain CallbackHandler。

    v3 行为：每次调用创建新 handler，自动检测当前 OTEL 上下文，
    使 LLM generation 嵌套到正确的 span 下。
    """
    client = _ensure_client()
    if client is None:
        return None

    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except ImportError:
        pass

    try:
        from langfuse.callback import CallbackHandler
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").strip()
        return CallbackHandler(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
    except ImportError:
        return None
    except Exception:
        return None


# ==================== Span 辅助：节点级追踪 ====================

@asynccontextmanager
async def langfuse_span(name: str, *, input: Any | None = None):
    """为 graph 节点创建 Langfuse span。禁用时为 no-op。

    用法：
        async with langfuse_span("planner", input={"query": "..."}) as span:
            # ... 节点逻辑 ...
            if span:
                span.update(output=result, metadata={"duration_ms": 42})
    """
    lf = get_langfuse_client_safe()
    if lf is not None:
        try:
            kwargs: dict[str, Any] = {"name": name}
            if input is not None:
                kwargs["input"] = input
            async with lf.start_as_current_span(**kwargs) as span:
                yield span
        except Exception:
            # Langfuse span 创建失败不应影响业务逻辑
            yield None
    else:
        yield None


# ==================== Trace 入口：请求级追踪 ====================

def update_current_trace(
    *,
    name: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    input: Any | None = None,
    metadata: dict | None = None,
    tags: list[str] | None = None,
) -> None:
    """更新当前活跃 Langfuse trace 的元数据。在 @observe 装饰器内部调用。"""
    lf = get_langfuse_client_safe()
    if lf is None:
        return
    try:
        kwargs: dict[str, Any] = {}
        if name is not None:
            kwargs["name"] = name
        if session_id is not None:
            kwargs["session_id"] = session_id
        if user_id is not None:
            kwargs["user_id"] = user_id
        if input is not None:
            kwargs["input"] = input
        if metadata is not None:
            kwargs["metadata"] = metadata
        if tags is not None:
            kwargs["tags"] = tags
        if kwargs:
            lf.update_current_trace(**kwargs)
    except Exception:
        pass


# ==================== @observe 装饰器安全导入 ====================

try:
    from langfuse import observe as langfuse_observe
except ImportError:
    # langfuse 未安装时提供 no-op 装饰器
    def langfuse_observe(func=None, *, name=None, **kwargs):  # type: ignore[misc]
        if func is not None:
            return func
        return lambda f: f


# ==================== 生命周期管理 ====================

def flush_langfuse() -> None:
    """Flush 待发送的 LangFuse 事件。在 shutdown 时调用。"""
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
        except Exception:
            pass


def shutdown_langfuse() -> None:
    """关闭 LangFuse client。在 app 退出时调用。"""
    if _langfuse_client is not None:
        try:
            _langfuse_client.shutdown()
        except Exception:
            pass


__all__ = [
    "get_langfuse_client",
    "get_langfuse_client_safe",
    "get_langfuse_callback",
    "langfuse_span",
    "langfuse_observe",
    "update_current_trace",
    "flush_langfuse",
    "shutdown_langfuse",
]
