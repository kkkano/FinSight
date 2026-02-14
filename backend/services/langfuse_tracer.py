# -*- coding: utf-8 -*-
"""LangFuse tracing integration for FinSight.

Provides optional LangFuse callback handler for LangChain LLM calls.
Gracefully degrades when LangFuse is not installed or not configured.

Environment variables:
    LANGFUSE_ENABLED: "true" to enable (default: "false")
    LANGFUSE_PUBLIC_KEY: LangFuse public key
    LANGFUSE_SECRET_KEY: LangFuse secret key
    LANGFUSE_HOST: LangFuse server URL (default: "https://cloud.langfuse.com")
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_langfuse_client = None
_langfuse_handler = None
_init_attempted = False


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def get_langfuse_callback() -> Any | None:
    """Return a LangFuse CallbackHandler if enabled and configured, else None.

    Safe to call repeatedly — initializes once, caches result.
    Never raises — returns None on any failure.
    """
    global _langfuse_client, _langfuse_handler, _init_attempted

    if _init_attempted:
        return _langfuse_handler
    _init_attempted = True

    if not _env_bool("LANGFUSE_ENABLED", False):
        logger.debug("[LangFuse] Disabled (set LANGFUSE_ENABLED=true to enable)")
        return None

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").strip()

    if not public_key or not secret_key:
        logger.warning("[LangFuse] Enabled but missing LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY")
        return None

    # langfuse v3+ 通过环境变量读取 secret_key / host，确保已设置
    os.environ.setdefault("LANGFUSE_SECRET_KEY", secret_key)
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", public_key)
    os.environ.setdefault("LANGFUSE_HOST", host)

    try:
        # ==================== v3 初始化全局 client ====================
        # langfuse v3 要求先创建 Langfuse() 全局 client，
        # CallbackHandler 内部依赖它进行 trace 上报。
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )

        # 验证连接
        if not _langfuse_client.auth_check():
            logger.warning("[LangFuse] auth_check failed — 请检查 API Key")
            _langfuse_client = None
            return None

        # ==================== 创建 LangChain CallbackHandler ====================
        try:
            from langfuse.langchain import CallbackHandler

            _langfuse_handler = CallbackHandler(public_key=public_key)
        except ImportError:
            from langfuse.callback import CallbackHandler

            _langfuse_handler = CallbackHandler(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )

        logger.info("[LangFuse] Tracing enabled → %s", host)
        return _langfuse_handler
    except ImportError:
        logger.info("[LangFuse] langfuse package not installed — pip install langfuse")
        return None
    except Exception as exc:
        logger.warning("[LangFuse] Failed to initialize: %s", exc)
        return None


def flush_langfuse() -> None:
    """Flush pending LangFuse events. Call on shutdown."""
    # 先 flush 全局 client（v3 的 trace 实际通过它发送）
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
        except Exception:
            pass
    # 兼容 v2 handler flush
    if _langfuse_handler is not None:
        try:
            if hasattr(_langfuse_handler, "langfuse"):
                _langfuse_handler.langfuse.flush()
            elif hasattr(_langfuse_handler, "flush"):
                _langfuse_handler.flush()
        except Exception:
            pass


def shutdown_langfuse() -> None:
    """Shutdown LangFuse client. Call on app exit."""
    if _langfuse_client is not None:
        try:
            _langfuse_client.shutdown()
        except Exception:
            pass


__all__ = ["get_langfuse_callback", "flush_langfuse", "shutdown_langfuse"]
