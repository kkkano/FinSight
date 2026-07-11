# -*- coding: utf-8 -*-
"""FinSight ASGI 入口；应用装配位于 :mod:`backend.api.app_factory`。"""
from __future__ import annotations

import asyncio
import sys

from backend.api.app_factory import create_app
from backend.api.security_gate import SimpleRateLimiter
from backend.api.session_context import (
    _ESSENTIAL_SSE_TYPES,
    _SENSITIVE_KEY_FRAGMENTS,
    _SESSION_PART_PATTERN,
    _build_trace_digest,
    _build_ui_context,
    _cleanup_session_contexts,
    _clear_session_context,
    _clear_thread_rag_artifacts,
    _contract_info,
    _get_orchestrator_safe,
    _get_session_context,
    _is_raw_trace_event,
    _list_session_contexts,
    _mask_secret,
    _normalize_session_key,
    _redact_sensitive_payload,
    _reference_context_last_access,
    _reference_contexts,
    _reference_lock,
    _resolve_query_reference,
    _resolve_thread_id,
    _resolve_trace_raw_enabled,
    _schedule_report_index,
    _summarize_session_context,
    _update_session_context,
)
from backend.graph import aget_graph_runner
from backend.services.report_index import get_report_index_store


if sys.platform.startswith("win") and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.api.main:app", host="0.0.0.0", port=8000, reload=True)
