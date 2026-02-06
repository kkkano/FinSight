# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import atexit
import logging
import os
from contextlib import ExitStack
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

CHECKPOINTER_SCHEMA_VERSION = "checkpointer.v1"

_async_bundle: Optional["CheckpointerBundle"] = None
_async_lock: Optional[asyncio.Lock] = None
_async_bundle_loop_id: Optional[int] = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def _resolve_backend() -> str:
    return (os.getenv("LANGGRAPH_CHECKPOINTER_BACKEND", "sqlite") or "sqlite").strip().lower()


@dataclass(frozen=True)
class CheckpointerInfo:
    schema_version: str
    backend: str
    persistent: bool
    location: Optional[str]
    fallback_used: bool
    fallback_reason: Optional[str]


@dataclass
class CheckpointerBundle:
    saver: Any
    info: CheckpointerInfo
    _stack: Optional[ExitStack] = None
    _async_cm: Any = None

    async def aclose(self) -> None:
        if self._async_cm is not None:
            cm = self._async_cm
            self._async_cm = None
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                logger.exception("failed to close async checkpointer context")
        if self._stack is not None:
            try:
                self._stack.close()
            except Exception:
                logger.exception("failed to close sync checkpointer stack")
            finally:
                self._stack = None

    def close(self) -> None:
        if self._stack is not None:
            try:
                self._stack.close()
            except Exception:
                logger.exception("failed to close sync checkpointer stack")
            finally:
                self._stack = None
        if self._async_cm is not None:
            try:
                asyncio.run(self.aclose())
            except Exception:
                # best effort during process shutdown
                self._async_cm = None


def _memory_bundle(*, reason: Optional[str], fallback_used: bool) -> CheckpointerBundle:
    info = CheckpointerInfo(
        schema_version=CHECKPOINTER_SCHEMA_VERSION,
        backend="memory",
        persistent=False,
        location=None,
        fallback_used=fallback_used,
        fallback_reason=reason,
    )
    return CheckpointerBundle(saver=MemorySaver(), info=info)


def _create_sync_sqlite_bundle(sqlite_path: str) -> CheckpointerBundle:
    from langgraph.checkpoint.sqlite import SqliteSaver

    resolved = os.path.abspath(sqlite_path)
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    stack = ExitStack()
    saver = stack.enter_context(SqliteSaver.from_conn_string(resolved))
    saver.setup()
    info = CheckpointerInfo(
        schema_version=CHECKPOINTER_SCHEMA_VERSION,
        backend="sqlite",
        persistent=True,
        location=resolved,
        fallback_used=False,
        fallback_reason=None,
    )
    return CheckpointerBundle(saver=saver, info=info, _stack=stack)


async def _create_async_sqlite_bundle(sqlite_path: str) -> CheckpointerBundle:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    resolved = os.path.abspath(sqlite_path)
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    cm = AsyncSqliteSaver.from_conn_string(resolved)
    saver = await cm.__aenter__()
    await saver.setup()
    info = CheckpointerInfo(
        schema_version=CHECKPOINTER_SCHEMA_VERSION,
        backend="sqlite",
        persistent=True,
        location=resolved,
        fallback_used=False,
        fallback_reason=None,
    )
    return CheckpointerBundle(saver=saver, info=info, _async_cm=cm)


def _create_sync_postgres_bundle(dsn: str, *, pipeline: bool) -> CheckpointerBundle:
    from langgraph.checkpoint.postgres import PostgresSaver

    stack = ExitStack()
    saver = stack.enter_context(PostgresSaver.from_conn_string(dsn, pipeline=pipeline))
    saver.setup()
    info = CheckpointerInfo(
        schema_version=CHECKPOINTER_SCHEMA_VERSION,
        backend="postgres",
        persistent=True,
        location=dsn,
        fallback_used=False,
        fallback_reason=None,
    )
    return CheckpointerBundle(saver=saver, info=info, _stack=stack)


async def _create_async_postgres_bundle(dsn: str, *, pipeline: bool) -> CheckpointerBundle:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    cm = AsyncPostgresSaver.from_conn_string(dsn, pipeline=pipeline)
    saver = await cm.__aenter__()
    await saver.setup()
    info = CheckpointerInfo(
        schema_version=CHECKPOINTER_SCHEMA_VERSION,
        backend="postgres",
        persistent=True,
        location=dsn,
        fallback_used=False,
        fallback_reason=None,
    )
    return CheckpointerBundle(saver=saver, info=info, _async_cm=cm)


def _build_sync_bundle() -> CheckpointerBundle:
    backend = _resolve_backend()
    allow_fallback = _env_bool("LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK", True)
    try:
        if backend == "memory":
            bundle = _memory_bundle(reason=None, fallback_used=False)
        elif backend == "sqlite":
            sqlite_path = os.getenv(
                "LANGGRAPH_CHECKPOINT_SQLITE_PATH",
                os.path.join("data", "langgraph", "checkpoints.sqlite"),
            )
            bundle = _create_sync_sqlite_bundle(sqlite_path)
        elif backend == "postgres":
            dsn = (os.getenv("LANGGRAPH_CHECKPOINT_POSTGRES_DSN") or "").strip()
            if not dsn:
                raise ValueError("LANGGRAPH_CHECKPOINT_POSTGRES_DSN is required when backend=postgres")
            pipeline = _env_bool("LANGGRAPH_CHECKPOINT_POSTGRES_PIPELINE", False)
            bundle = _create_sync_postgres_bundle(dsn, pipeline=pipeline)
        else:
            raise ValueError(f"Unsupported LANGGRAPH_CHECKPOINTER_BACKEND: {backend}")
        logger.info("LangGraph sync checkpointer backend=%s", bundle.info.backend)
        atexit.register(bundle.close)
        return bundle
    except Exception as exc:
        if not allow_fallback:
            raise
        logger.warning("LangGraph sync checkpointer fallback to memory: %s", exc)
        return _memory_bundle(reason=str(exc), fallback_used=True)


async def _build_async_bundle() -> CheckpointerBundle:
    backend = _resolve_backend()
    allow_fallback = _env_bool("LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK", True)
    try:
        if backend == "memory":
            bundle = _memory_bundle(reason=None, fallback_used=False)
        elif backend == "sqlite":
            sqlite_path = os.getenv(
                "LANGGRAPH_CHECKPOINT_SQLITE_PATH",
                os.path.join("data", "langgraph", "checkpoints.sqlite"),
            )
            bundle = await _create_async_sqlite_bundle(sqlite_path)
        elif backend == "postgres":
            dsn = (os.getenv("LANGGRAPH_CHECKPOINT_POSTGRES_DSN") or "").strip()
            if not dsn:
                raise ValueError("LANGGRAPH_CHECKPOINT_POSTGRES_DSN is required when backend=postgres")
            pipeline = _env_bool("LANGGRAPH_CHECKPOINT_POSTGRES_PIPELINE", False)
            bundle = await _create_async_postgres_bundle(dsn, pipeline=pipeline)
        else:
            raise ValueError(f"Unsupported LANGGRAPH_CHECKPOINTER_BACKEND: {backend}")
        logger.info("LangGraph async checkpointer backend=%s", bundle.info.backend)
        atexit.register(bundle.close)
        return bundle
    except Exception as exc:
        if not allow_fallback:
            raise
        logger.warning("LangGraph async checkpointer fallback to memory: %s", exc)
        return _memory_bundle(reason=str(exc), fallback_used=True)


@lru_cache(maxsize=1)
def get_checkpointer_bundle() -> CheckpointerBundle:
    """
    Sync accessor for scripts/tests.
    """
    return _build_sync_bundle()


async def aget_checkpointer_bundle() -> CheckpointerBundle:
    """
    Async accessor for LangGraph runtime (ainvoke/astream).
    """
    global _async_bundle, _async_lock, _async_bundle_loop_id
    loop_id = id(asyncio.get_running_loop())
    if _async_bundle is not None and _async_bundle_loop_id == loop_id:
        return _async_bundle
    if _async_lock is None:
        _async_lock = asyncio.Lock()
    async with _async_lock:
        loop_id = id(asyncio.get_running_loop())
        if _async_bundle is not None and _async_bundle_loop_id == loop_id:
            return _async_bundle
        if _async_bundle is not None and _async_bundle_loop_id != loop_id:
            # AsyncSqliteSaver binds to loop/thread; reuse across loops causes
            # "ValueError: no active connection" in tests/reloads.
            old_bundle = _async_bundle
            _async_bundle = None
            _async_bundle_loop_id = None
            try:
                await old_bundle.aclose()
            except Exception:
                logger.exception("failed to close stale async checkpointer bundle")
        if _async_bundle is None:
            _async_bundle = await _build_async_bundle()
            _async_bundle_loop_id = loop_id
    return _async_bundle


def get_graph_checkpointer() -> Any:
    return get_checkpointer_bundle().saver


async def aget_graph_checkpointer() -> Any:
    return (await aget_checkpointer_bundle()).saver


def _sanitize_location(info: CheckpointerInfo) -> Optional[str]:
    location = info.location
    if info.backend == "postgres" and isinstance(location, str) and "@" in location:
        right = location.split("@", 1)[1]
        if "://" in location:
            scheme = location.split("://", 1)[0]
            return f"{scheme}://***@{right}"
        return f"***@{right}"
    return location


def get_graph_checkpointer_info() -> dict[str, Any]:
    info: Optional[CheckpointerInfo] = None
    if _async_bundle is not None:
        info = _async_bundle.info
    else:
        try:
            info = get_checkpointer_bundle().info
        except Exception:
            info = None

    if info is None:
        return {
            "schema_version": CHECKPOINTER_SCHEMA_VERSION,
            "backend": "unknown",
            "persistent": False,
            "location": None,
            "fallback_used": False,
            "fallback_reason": "uninitialized",
        }

    return {
        "schema_version": info.schema_version,
        "backend": info.backend,
        "persistent": info.persistent,
        "location": _sanitize_location(info),
        "fallback_used": info.fallback_used,
        "fallback_reason": info.fallback_reason,
    }


def reset_checkpointer_caches() -> None:
    """
    Test helper.
    """
    global _async_bundle, _async_lock, _async_bundle_loop_id
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        raise RuntimeError("Use areset_checkpointer_caches() inside async context")

    if _async_bundle is not None:
        try:
            _async_bundle.close()
        except Exception:
            pass
    _async_bundle = None
    _async_lock = None
    _async_bundle_loop_id = None
    try:
        bundle = get_checkpointer_bundle()
        bundle.close()
    except Exception:
        pass
    get_checkpointer_bundle.cache_clear()


async def areset_checkpointer_caches() -> None:
    global _async_bundle, _async_lock, _async_bundle_loop_id
    if _async_bundle is not None:
        try:
            await _async_bundle.aclose()
        except Exception:
            logger.exception("failed to close async bundle")
    _async_bundle = None
    _async_lock = None
    _async_bundle_loop_id = None
    try:
        bundle = get_checkpointer_bundle()
        bundle.close()
    except Exception:
        pass
    get_checkpointer_bundle.cache_clear()


__all__ = [
    "CHECKPOINTER_SCHEMA_VERSION",
    "CheckpointerInfo",
    "CheckpointerBundle",
    "get_checkpointer_bundle",
    "aget_checkpointer_bundle",
    "get_graph_checkpointer",
    "aget_graph_checkpointer",
    "get_graph_checkpointer_info",
    "reset_checkpointer_caches",
    "areset_checkpointer_caches",
]
