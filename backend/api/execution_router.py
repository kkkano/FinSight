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
from typing import Any, Awaitable, Callable, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.graph.confirmation_policy import parse_confirmation_mode
from backend.services.execution_service import ExecutionDeps, run_graph_pipeline, resume_graph_pipeline

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
    confirmation_mode: Literal["auto", "required", "skip"] | None = Field(
        None,
        description="Confirmation strategy override: auto/required/skip",
    )
    analysis_depth: Literal["quick", "report", "deep_research"] | None = Field(
        None,
        description="Explicit analysis depth semantics (quick/report/deep_research)",
    )
    ensure_all_agents: bool | None = Field(
        None,
        description="Force report orchestration to keep all report agents enabled",
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
    run_id: str | None = Field(None, description="Client-provided run id for event correlation")
    trace_raw: bool | None = Field(
        None,
        description="Whether to include full raw trace events in SSE stream",
    )
    agent_preferences: dict | None = Field(
        None,
        description="Per-agent depth + budget preferences from frontend UI",
    )


class ResumeRequest(BaseModel):
    """Body for ``POST /api/execute/resume``."""

    thread_id: str = Field(..., min_length=1, description="Thread / session ID to resume")
    resume_value: Any = Field(..., description="User response to the interrupt prompt")
    session_id: str | None = Field(None, description="Session ID")
    run_id: str | None = Field(None, description="Client-provided run id for event correlation")
    source: str | None = Field(None, description="Trigger origin")
    trace_raw: bool | None = Field(None)


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
        if request.analysis_depth:
            ui_context["analysis_depth"] = request.analysis_depth
        if request.agent_preferences:
            ui_context["agent_preferences"] = request.agent_preferences
        if request.ensure_all_agents is not None:
            ui_context["ensure_all_agents"] = bool(request.ensure_all_agents)
        if (request.output_mode or "").strip().lower() == "investment_report":
            ui_context.setdefault("ensure_all_agents", True)

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
            run_id=request.run_id,
            ui_context=ui_context,
            output_mode=request.output_mode,
            confirmation_mode=parse_confirmation_mode(request.confirmation_mode),
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

    # ------------------------------------------------------------------
    # POST /api/execute/resume — resume an interrupted graph run
    # ------------------------------------------------------------------

    @router.post("/api/execute/resume")
    async def resume_endpoint(request: ResumeRequest):
        thread_id = request.thread_id
        if request.session_id:
            try:
                thread_id = deps.resolve_thread_id(request.session_id)
            except ValueError:
                pass

        exec_deps = ExecutionDeps(
            get_graph_runner=deps.get_graph_runner,
            schedule_report_index=deps.schedule_report_index,
            update_session_context=deps.update_session_context,
            redact_sensitive_payload=deps.redact_sensitive_payload,
            is_raw_trace_event=deps.is_raw_trace_event,
            contract_info=deps.contract_info,
            sse_event_schema_version=deps.sse_event_schema_version,
        )

        pipeline = resume_graph_pipeline(
            deps=exec_deps,
            thread_id=thread_id,
            run_id=request.run_id,
            resume_value=request.resume_value,
            source=request.source or "resume",
            trace_raw_enabled=True if request.trace_raw is None else bool(request.trace_raw),
        )

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
