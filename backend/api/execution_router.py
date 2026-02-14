"""
Execution router — ``POST /api/execute``

A *non-chat* entry point for triggering the LangGraph pipeline from
Dashboard cards, Workbench tasks, or any UI widget that isn't the chat
panel.  Uses the **same** :func:`run_graph_pipeline` as the chat
streaming endpoint so execution behaviour is never duplicated.
"""
from __future__ import annotations

import json as _json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.services.execution_service import ExecutionDeps, run_graph_pipeline

logger = logging.getLogger("execution_router")


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    """Body for ``POST /api/execute``."""

    query: str = Field(..., min_length=1, description="Analysis query")
    tickers: list[str] | None = Field(None, description="Explicit ticker list")
    output_mode: str | None = Field(
        None, description="chat / brief / investment_report",
    )
    agents: list[str] | None = Field(
        None, description="Override: only run these agents",
    )
    budget: int | None = Field(
        None, ge=1, le=10, description="Max LangGraph rounds",
    )
    source: str | None = Field(
        None, description="Trigger origin (dashboard / workbench / …)",
    )
    session_id: str | None = Field(None, description="Session ID")
    trace_raw: bool | None = Field(
        None,
        description="Whether to include full raw trace events in SSE stream",
    )


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionRouterDeps:
    """Injected from main.py — mirrors the subset needed by the router."""

    get_graph_runner: Callable[[], Awaitable[Any]]
    resolve_thread_id: Callable[[Optional[str]], str]
    schedule_report_index: Callable[..., None]
    update_session_context: Callable[..., None]
    redact_sensitive_payload: Callable[[Any], Any]
    is_raw_trace_event: Callable[[dict[str, Any]], bool]
    contract_info: Callable[[], dict[str, str]]
    sse_event_schema_version: str


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def create_execution_router(deps: ExecutionRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Execution"])

    @router.post("/api/execute")
    async def execute_endpoint(request: ExecuteRequest):
        try:
            thread_id = deps.resolve_thread_id(request.session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # Build ui_context from execution-specific fields
        ui_context: dict[str, Any] = {}
        if request.tickers:
            ui_context["tickers_override"] = request.tickers
        if request.agents:
            ui_context["agents_override"] = request.agents
        if request.budget is not None:
            ui_context["budget_override"] = request.budget
        if request.source:
            ui_context["source"] = request.source

        exec_deps = ExecutionDeps(
            get_graph_runner=deps.get_graph_runner,
            schedule_report_index=deps.schedule_report_index,
            update_session_context=deps.update_session_context,
            redact_sensitive_payload=deps.redact_sensitive_payload,
            is_raw_trace_event=deps.is_raw_trace_event,
            contract_info=deps.contract_info,
            sse_event_schema_version=deps.sse_event_schema_version,
        )

        pipeline = run_graph_pipeline(
            deps=exec_deps,
            query=request.query,
            thread_id=thread_id,
            ui_context=ui_context,
            output_mode=request.output_mode,
            source=request.source or "execute",
            trace_raw_enabled=True if request.trace_raw is None else bool(request.trace_raw),
        )

        # --- SSE streaming (same wire format as /chat/supervisor/stream) ---

        def _serialize(item: object) -> str:
            def _fallback(value: object):
                if isinstance(value, (datetime, date, dt_time)):
                    return value.isoformat()
                return str(value)

            return _json.dumps(
                jsonable_encoder(item), ensure_ascii=False, default=_fallback,
            )

        async def _stream():
            async for event in pipeline:
                if isinstance(event, dict) and event.get("type") == "keep-alive":
                    yield ": keep-alive\n\n"
                else:
                    yield f"data: {_serialize(event)}\n\n"

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
