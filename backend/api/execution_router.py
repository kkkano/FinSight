"""唯一的 Chat/Report SSE 执行入口。"""
from __future__ import annotations

import asyncio
import math
import os
import re
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time
from typing import Any, AsyncIterable, Awaitable, Callable, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.schemas import ChatContext, ChatMessage, ChatOptions
from backend.api.stream_replay import replay_buffer
from backend.graph.confirmation_policy import parse_confirmation_mode
from backend.services.execution_service import ExecutionDeps, run_graph_pipeline


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_STREAM_TASKS: set[asyncio.Task[Any]] = set()
_STREAM_TASKS_BY_RUN: dict[str, asyncio.Task[Any]] = {}
_RUN_OWNERS: OrderedDict[str, str] = OrderedDict()
_MAX_RUN_OWNERS = 256


class ExecuteRequest(BaseModel):
    """Chat、Dashboard handoff 与报告生成共用的执行请求。"""

    query: str = Field(..., min_length=1, description="Analysis query")
    session_id: str | None = Field(None, description="Conversation session ID")
    run_id: str | None = Field(None, description="Optional correlation ID")
    history: list[ChatMessage] | None = Field(None, description="Visible conversation history")
    context: ChatContext | None = Field(None, description="Ephemeral UI context")
    options: ChatOptions | None = Field(None, description="Chat execution options")

    tickers: list[str] | None = None
    output_mode: str | None = None
    confirmation_mode: Literal["auto", "required", "skip"] | None = None
    analysis_depth: Literal["quick", "report", "deep_research"] | None = None
    agents: list[str] | None = None
    budget: int | None = Field(None, ge=1, le=10)
    source: str | None = None
    trace_raw: bool | None = None
    agent_preferences: dict[str, Any] | None = None

    model_config = {"extra": "ignore"}


@dataclass(frozen=True)
class ExecutionRouterDeps:
    get_graph_runner: Callable[[], Awaitable[Any]]
    resolve_thread_id: Callable[[Optional[str]], str]
    schedule_report_index: Callable[..., None]
    update_session_context: Callable[..., None]
    redact_sensitive_payload: Callable[[Any], Any]
    is_raw_trace_event: Callable[[dict[str, Any]], bool]
    contract_info: Callable[[], dict[str, str]]
    sse_event_schema_version: str


def _build_execution_deps(deps: ExecutionRouterDeps) -> ExecutionDeps:
    return ExecutionDeps(
        get_graph_runner=deps.get_graph_runner,
        schedule_report_index=deps.schedule_report_index,
        update_session_context=deps.update_session_context,
        redact_sensitive_payload=deps.redact_sensitive_payload,
        is_raw_trace_event=deps.is_raw_trace_event,
        contract_info=deps.contract_info,
        sse_event_schema_version=deps.sse_event_schema_version,
    )


def _sanitize_json_payload(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _sanitize_json_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json_payload(item) for item in value]
    return value


def _serialize_sse_item(item: object) -> str:
    import json

    def _fallback(value: object):
        if isinstance(value, (datetime, date, dt_time)):
            return value.isoformat()
        return str(value)

    return json.dumps(
        _sanitize_json_payload(jsonable_encoder(item)),
        ensure_ascii=False,
        allow_nan=False,
        default=_fallback,
    )


def _generation_enabled() -> bool:
    return str(os.getenv("REPORTS_GENERATION_ENABLED", "true")).strip().lower() not in {"false", "0", "off"}


def _enforce_user_quota(http_request: Request) -> str:
    from backend.services.cost_audit import UserDailyCostLimitExceeded, check_user_quota

    user_id = str(getattr(http_request.state, "user_id", "public") or "public")
    try:
        check_user_quota(user_id)
    except UserDailyCostLimitExceeded as exc:
        raise HTTPException(status_code=429, detail={"code": "quota_exceeded", "message": str(exc)}) from exc
    return user_id


def _normalize_run_id(value: str | None) -> str:
    run_id = str(value or "").strip() or uuid.uuid4().hex
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_run_id", "message": "run_id format invalid"})
    return run_id


def _register_run_owner(run_id: str, user_id: str) -> None:
    existing = _RUN_OWNERS.get(run_id)
    if existing is not None:
        raise HTTPException(status_code=409, detail={"code": "run_id_conflict", "message": "run_id already exists"})
    _RUN_OWNERS[run_id] = user_id
    _RUN_OWNERS.move_to_end(run_id)
    while len(_RUN_OWNERS) > _MAX_RUN_OWNERS:
        _RUN_OWNERS.popitem(last=False)


def _authorize_run(run_id: str, user_id: str) -> None:
    owner = _RUN_OWNERS.get(run_id)
    if owner is None or owner != user_id:
        raise HTTPException(status_code=404, detail={"code": "run_not_found", "message": "stream expired or unknown"})


def _track_stream_task(run_id: str, task: asyncio.Task[Any]) -> None:
    _STREAM_TASKS.add(task)
    _STREAM_TASKS_BY_RUN[run_id] = task

    def _cleanup(done_task: asyncio.Task[Any]) -> None:
        _STREAM_TASKS.discard(done_task)
        if _STREAM_TASKS_BY_RUN.get(run_id) is done_task:
            _STREAM_TASKS_BY_RUN.pop(run_id, None)

    task.add_done_callback(_cleanup)


async def _stream_replay(run_id: str, *, after_seq: int = 0, session_id: str | None = None):
    cursor = max(0, int(after_seq))
    last_keep_alive = time.monotonic()
    while True:
        batch = replay_buffer.replay_from(run_id, cursor)
        if batch is None:
            return
        if batch:
            for seq, payload in batch:
                cursor = seq
                yield f"data: {payload}\n\n"
            last_keep_alive = time.monotonic()
            continue
        if replay_buffer.is_complete(run_id):
            return
        now = time.monotonic()
        if now - last_keep_alive >= 15:
            heartbeat = {"type": "keep-alive", "run_id": run_id}
            if session_id:
                heartbeat["session_id"] = session_id
            yield f"data: {_serialize_sse_item(heartbeat)}\n\n"
            last_keep_alive = now
        await asyncio.sleep(0.1)


def _buffered_sse_response(
    pipeline: AsyncIterable[dict[str, Any]],
    *,
    run_id: str,
    thread_id: str,
) -> StreamingResponse:
    replay_buffer.start_run(run_id)

    async def _pump() -> None:
        try:
            async for event in pipeline:
                payload = _sanitize_json_payload(jsonable_encoder(event))
                if not isinstance(payload, dict):
                    payload = {"type": "system", "data": payload}
                payload.setdefault("run_id", run_id)
                payload.setdefault("session_id", thread_id)
                replay_buffer.append(run_id, payload)
        except asyncio.CancelledError:
            replay_buffer.append(run_id, {"type": "cancelled", "run_id": run_id, "session_id": thread_id})
            raise
        except Exception as exc:
            replay_buffer.append(run_id, {
                "type": "error",
                "code": "execution_failed",
                "message": str(exc),
                "run_id": run_id,
                "session_id": thread_id,
            })
        finally:
            replay_buffer.mark_complete(run_id)

    _track_stream_task(run_id, asyncio.create_task(_pump()))
    return StreamingResponse(
        _stream_replay(run_id, session_id=thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Run-Id": run_id,
        },
    )


def _request_ui_context(request: ExecuteRequest, user_id: str) -> dict[str, Any]:
    ui_context = request.context.model_dump(exclude_none=True) if request.context else {}
    if request.history:
        ui_context["session_history"] = [item.model_dump() for item in request.history[-12:]]
    if request.tickers:
        ui_context["tickers_override"] = request.tickers
    selected_agents = request.agents or (request.options.agents if request.options else None)
    if selected_agents:
        ui_context["agents_override"] = selected_agents
    if request.budget is not None:
        ui_context["budget_override"] = request.budget
    if request.source:
        ui_context["source"] = request.source
    if request.analysis_depth:
        ui_context["analysis_depth"] = request.analysis_depth
    preferences = request.agent_preferences or (request.options.agent_preferences if request.options else None)
    if preferences:
        ui_context["agent_preferences"] = preferences
    ui_context["__user_id"] = user_id
    return ui_context


def create_execution_router(deps: ExecutionRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Execution"])

    @router.post("/api/execute")
    async def execute_endpoint(request: ExecuteRequest, http_request: Request):
        if not _generation_enabled():
            raise HTTPException(status_code=503, detail={"code": "generation_disabled", "message": "生成服务维护中"})
        user_id = _enforce_user_quota(http_request)
        try:
            thread_id = deps.resolve_thread_id(request.session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_session_id", "message": str(exc)}) from exc

        run_id = _normalize_run_id(request.run_id)
        _register_run_owner(run_id, user_id)
        options = request.options
        output_mode = request.output_mode or (options.output_mode if options else None)
        confirmation_mode = request.confirmation_mode or (options.confirmation_mode if options else None) or "skip"
        strict_selection = options.strict_selection if options else None
        trace_raw = request.trace_raw
        if trace_raw is None and options and options.trace_raw_override in {"on", "off"}:
            trace_raw = options.trace_raw_override == "on"

        pipeline = run_graph_pipeline(
            deps=_build_execution_deps(deps),
            query=request.query,
            thread_id=thread_id,
            run_id=run_id,
            ui_context=_request_ui_context(request, user_id),
            output_mode=output_mode,
            strict_selection=strict_selection,
            confirmation_mode=parse_confirmation_mode(confirmation_mode),
            original_query=request.query,
            source=request.source or "chat",
            user_id=user_id,
            trace_raw_enabled=bool(trace_raw),
        )
        return _buffered_sse_response(pipeline, run_id=run_id, thread_id=thread_id)

    @router.get("/api/execute/runs/{run_id}/events")
    async def replay_events(run_id: str, http_request: Request, after_seq: int = 0):
        normalized = _normalize_run_id(run_id)
        user_id = str(getattr(http_request.state, "user_id", "public") or "public")
        _authorize_run(normalized, user_id)
        if replay_buffer.replay_from(normalized, max(0, after_seq)) is None:
            raise HTTPException(status_code=410, detail={"code": "run_expired", "message": "stream expired"})
        return StreamingResponse(
            _stream_replay(normalized, after_seq=after_seq),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    @router.post("/api/execute/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, http_request: Request):
        normalized = _normalize_run_id(run_id)
        user_id = str(getattr(http_request.state, "user_id", "public") or "public")
        _authorize_run(normalized, user_id)
        task = _STREAM_TASKS_BY_RUN.get(normalized)
        if task is None or task.done():
            raise HTTPException(status_code=409, detail={"code": "run_not_active", "message": "run is not active"})
        task.cancel()
        return {"cancelled": True, "run_id": normalized}

    return router


__all__ = ["ExecuteRequest", "ExecutionRouterDeps", "create_execution_router"]
