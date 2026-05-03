# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Optional


_CANCEL_EVENT: ContextVar[Optional[asyncio.Event]] = ContextVar(
    "langgraph_cancel_event",
    default=None,
)


def set_cancel_event(cancel_event: asyncio.Event | None):
    return _CANCEL_EVENT.set(cancel_event)


def reset_cancel_event(token) -> None:
    _CANCEL_EVENT.reset(token)


def get_cancel_event() -> asyncio.Event | None:
    return _CANCEL_EVENT.get()


def is_cancelled(cancel_event: asyncio.Event | None = None) -> bool:
    event = cancel_event if cancel_event is not None else get_cancel_event()
    return bool(event and event.is_set())


__all__ = [
    "get_cancel_event",
    "is_cancelled",
    "reset_cancel_event",
    "set_cancel_event",
]
