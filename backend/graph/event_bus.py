# -*- coding: utf-8 -*-
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Optional

EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]

_EVENT_EMITTER: ContextVar[Optional[EventEmitter]] = ContextVar("langgraph_event_emitter", default=None)


def set_event_emitter(emitter: Optional[EventEmitter]):
    """
    Set an async event emitter for the current async context.

    Used by `/chat/supervisor/stream` to stream real-time trace/thinking events
    while the graph is executing.
    """

    return _EVENT_EMITTER.set(emitter)


def reset_event_emitter(token) -> None:
    _EVENT_EMITTER.reset(token)


async def emit_event(payload: dict[str, Any]) -> None:
    emitter = _EVENT_EMITTER.get()
    if not emitter:
        return
    try:
        await emitter(payload)
    except Exception:
        # Never let tracing break the main flow.
        return


__all__ = ["EventEmitter", "emit_event", "set_event_emitter", "reset_event_emitter"]

