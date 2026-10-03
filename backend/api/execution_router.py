"""唯一的 Chat/Report SSE 执行入口。"""
from __future__ import annotations

import asyncio
import logging
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
from backend.api.session_context import SessionOwnershipError, _resolve_owned_thread_id
from backend.api.stream_replay import replay_buffer
from backend.services.execution_service import ExecutionDeps, run_graph_pipeline
from backend.services.model_preflight import ensure_model_available
from backend.services.research_run_store import (
    HEARTBEAT_SECONDS, PostgresResearchRunStore, ResearchRunConflict,
    get_research_run_store, public_run, request_fingerprint,
)


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_STREAM_TASKS: set[asyncio.Task[Any]] = set()
_STREAM_TASKS_BY_RUN: dict[str, asyncio.Task[Any]] = {}
_RUN_OWNERS: OrderedDict[str, str] = OrderedDict()
_MAX_RUN_OWNERS = 256
logger = logging.getLogger(__name__)


class ExecuteRequest(BaseModel):
    """Chat、Dashboard handoff 与报告生成共用的执行请求。"""

    query: str = Field(..., min_length=1, description="Analysis query")
    session_id: str | None = Field(None, description="Conversation session ID")
    run_id: str | None = Field(None, description="Optional correlation ID")
    client_user_message_id: str | None = Field(None, min_length=1, max_length=128)
    client_assistant_message_id: str | None = Field(None, min_length=1, max_length=128)
    history: list[ChatMessage] | None = Field(None, description="Visible conversation history")
    context: ChatContext | None = Field(None, description="Ephemeral UI context")
    options: ChatOptions | None = Field(None, description="Chat execution options")

    tickers: list[str] | None = None
    output_mode: str | None = None
    analysis_depth: Literal["quick", "report", "deep_research"] | None = None
    budget: int | None = Field(None, ge=1, le=10)
    source: str | None = None
    trace_raw: bool | None = None

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


def _build_execution_deps(deps: ExecutionRouterDeps, persist_run_event=None) -> ExecutionDeps:
    return ExecutionDeps(
        get_graph_runner=deps.get_graph_runner,
        schedule_report_index=deps.schedule_report_index,
        update_session_context=deps.update_session_context,
        redact_sensitive_payload=deps.redact_sensitive_payload,
        is_raw_trace_event=deps.is_raw_trace_event,
        contract_info=deps.contract_info,
        sse_event_schema_version=deps.sse_event_schema_version,
        persist_run_event=persist_run_event,
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


def _request_user_id(http_request: Request) -> str:
    return str(getattr(http_request.state, "user_id", "public") or "public").strip() or "public"


def _enforce_user_quota(http_request: Request) -> str:
    from backend.services.llm_usage_store import (
        LLMUsageStoreUnavailable,
        UserDailyCostLimitExceeded,
        check_user_quota,
    )

    user_id = _request_user_id(http_request)
    try:
        check_user_quota(user_id)
    except UserDailyCostLimitExceeded as exc:
        raise HTTPException(status_code=429, detail={"code": "llm_quota_exceeded", "message": str(exc)}) from exc
    except LLMUsageStoreUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "store_unavailable", "message": "AI 额度暂时无法检查"},
        ) from exc
    return user_id


def _normalize_run_id(value: str | None) -> str:
    run_id = str(value or "").strip() or uuid.uuid4().hex
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_run_id", "message": "run_id format invalid"})
    return run_id


def _run_key(run_id: str, user_id: str) -> str:
    return f"{user_id}:{run_id}"


def _register_run_owner(run_id: str, user_id: str) -> None:
    key = _run_key(run_id, user_id)
    existing = _RUN_OWNERS.get(key)
    if existing is not None:
        raise HTTPException(status_code=409, detail={"code": "run_id_conflict", "message": "run_id already exists"})
    _RUN_OWNERS[key] = user_id
    _RUN_OWNERS.move_to_end(key)
    while len(_RUN_OWNERS) > _MAX_RUN_OWNERS:
        _RUN_OWNERS.popitem(last=False)


def _authorize_run(run_id: str, user_id: str) -> None:
    owner = _RUN_OWNERS.get(_run_key(run_id, user_id))
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


def _store_for_user(user_id: str) -> PostgresResearchRunStore | None:
    if user_id in {"public", "anonymous"}:
        return None
    try:
        return get_research_run_store()
    except Exception as exc:
        raise HTTPException(503, detail={"code": "run_store_unavailable", "message": "研究记录暂时无法保存，请稍后重试。"}) from exc


async def _load_run(store: PostgresResearchRunStore, run_id: str, user_id: str):
    try:
        return await asyncio.to_thread(store.get, run_id, user_id=user_id)
    except Exception as exc:
        raise HTTPException(503, detail={"code": "run_store_unavailable", "message": "研究记录暂时无法读取，请稍后重试。"}) from exc


def _persist_callback(store: PostgresResearchRunStore | None, run_id: str, user_id: str):
    async def persist(event: dict[str, Any]) -> dict[str, Any]:
        if store is None:
            return {**event, "persistence_status": "ephemeral"}
        try:
            payload = _sanitize_json_payload(jsonable_encoder(event))
            return await asyncio.to_thread(store.finish, run_id, payload, user_id=user_id)
        except Exception as exc:
            logger.error("研究终态保存失败 run_id=%s error_type=%s", run_id, type(exc).__name__)
            return {
                **event, "persistence_status": "failed", "run_status": "persistence_failed",
                "publishable": False, "error_code": "conversation_persistence_failed",
                "failure_kind": "persistence_error",
                "persistence_message": "回答已生成，但服务器保存失败；请保留当前页面内容，稍后恢复。",
            }
    return persist


async def _durable_replay(store, run_id: str, user_id: str, *, after_seq: int = 0):
    while True:
        try:
            row = await _load_run(store, run_id, user_id)
        except HTTPException:
            yield f"data: {_serialize_sse_item({'type': 'error', 'code': 'run_store_unavailable', 'message': '研究记录暂时无法读取，请稍后恢复。', 'run_id': run_id})}\n\n"
            return
        if row is None:
            return
        if row["status"] != "running":
            payload = public_run(row)["result"] or {}
            payload.update({"recovered": True, "seq": max(0, after_seq) + 1})
            yield f"data: {_serialize_sse_item(payload)}\n\n"
            return
        yield f"data: {_serialize_sse_item({'type': 'keep-alive', 'run_id': run_id, 'session_id': row['session_id'], 'run_status': 'running'})}\n\n"
        await asyncio.sleep(3)


async def _stream_replay(
    run_id: str, *, user_id: str, after_seq: int = 0, session_id: str | None = None,
    store: PostgresResearchRunStore | None = None,
):
    key = _run_key(run_id, user_id)
    cursor = max(0, int(after_seq))
    last_keep_alive = time.monotonic()
    while True:
        batch = replay_buffer.replay_from(key, cursor)
        if batch is None:
            if store is not None:
                async for event in _durable_replay(store, run_id, user_id, after_seq=cursor):
                    yield event
            return
        if batch:
            for seq, payload in batch:
                cursor = seq
                yield f"data: {payload}\n\n"
            last_keep_alive = time.monotonic()
            continue
        if replay_buffer.is_complete(key):
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
    user_id: str,
    store: PostgresResearchRunStore | None = None,
) -> StreamingResponse:
    key = _run_key(run_id, user_id)
    replay_buffer.start_run(key)
    persist = _persist_callback(store, run_id, user_id)

    async def _heartbeat() -> None:
        while store is not None:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                alive = await asyncio.to_thread(store.heartbeat, run_id, user_id=user_id)
                if not alive:
                    return
            except Exception as exc:
                logger.warning("研究运行心跳失败 run_id=%s error_type=%s", run_id, type(exc).__name__)

    async def _pump() -> None:
        from backend.services.model_selection import current_model, model_client_scope, CUSTOM_REQUEST_TIMEOUT_SECONDS
        chosen = current_model()
        heartbeat = asyncio.create_task(_heartbeat()) if store is not None else None
        terminal_seen = False
        preview: list[str] = []

        async def append(event: dict[str, Any]) -> None:
            nonlocal terminal_seen
            payload = _sanitize_json_payload(jsonable_encoder(event))
            payload.setdefault("run_id", run_id)
            payload.setdefault("session_id", thread_id)
            if payload.get("type") == "token" and isinstance(payload.get("content"), str):
                preview.append(payload["content"])
            if payload.get("type") in {"done", "error", "cancelled"}:
                terminal_seen = True
                if payload.get("type") != "done" and not payload.get("response") and preview:
                    payload["response"] = "".join(preview)
                if payload.get("persistence_status") not in {"saved", "failed", "ephemeral"}:
                    payload = await persist(payload)
            replay_buffer.append(key, payload)

        try:
            async with model_client_scope(), asyncio.timeout(
                CUSTOM_REQUEST_TIMEOUT_SECONDS if chosen is not None and chosen.source == "custom" else None
            ):
                async for event in pipeline:
                    await append(event if isinstance(event, dict) else {"type": "system", "data": event})
        except TimeoutError:
            await append({"type": "error", "code": "model_timeout",
                "message": "模型请求超时，请稍后重试。", "run_id": run_id, "session_id": thread_id})
        except asyncio.CancelledError:
            await append({"type": "cancelled", "run_id": run_id, "session_id": thread_id, "publishable": False})
            raise
        except Exception:
            logger.exception("execution stream pump failed run_id=%s", run_id)
            await append({
                "type": "error",
                "code": "execution_failed",
                "message": "执行失败，请稍后重试。",
                "run_id": run_id,
                "session_id": thread_id,
            })
        finally:
            if not terminal_seen:
                await append({"type": "error", "code": "run_interrupted", "run_status": "interrupted",
                              "message": "生成中断，已保留本次提问，请重新生成。", "publishable": False})
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            replay_buffer.mark_complete(key)

    _track_stream_task(key, asyncio.create_task(_pump()))
    return StreamingResponse(
        _stream_replay(run_id, user_id=user_id, session_id=thread_id, store=store),
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
    if request.budget is not None:
        ui_context["budget_override"] = request.budget
    if request.source:
        ui_context["source"] = request.source
    if request.analysis_depth:
        ui_context["analysis_depth"] = request.analysis_depth
    ui_context["__user_id"] = user_id
    return ui_context


def create_execution_router(deps: ExecutionRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Execution"])

    @router.post("/api/execute")
    async def execute_endpoint(request: ExecuteRequest, http_request: Request):
        user_id = _request_user_id(http_request)
        run_id = _normalize_run_id(request.run_id)
        store = _store_for_user(user_id)
        existing = await _load_run(store, run_id, user_id) if store is not None else None
        try:
            thread_id = _resolve_owned_thread_id(
                request.session_id or (existing["session_id"] if existing else None),
                user_id,
                normalize=deps.resolve_thread_id,
            )
        except SessionOwnershipError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "session_not_found", "message": "session not found"},
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_session_id", "message": str(exc)}) from exc

        options = request.options
        output_mode = request.output_mode or (options.output_mode if options else None)
        strict_selection = options.strict_selection if options else None
        trace_raw = request.trace_raw
        if trace_raw is None and options and options.trace_raw_override in {"on", "off"}:
            trace_raw = options.trace_raw_override == "on"
        from backend.services.model_selection import current_model
        selected = current_model()
        fingerprint = request_fingerprint({
            "query": request.query, "session_id": thread_id, "output_mode": output_mode,
            "strict_selection": strict_selection, "tickers": request.tickers,
            "analysis_depth": request.analysis_depth, "source": request.source,
            "context": request.context.model_dump(exclude_none=True) if request.context else None,
            "history": [message.model_dump() for message in (request.history or [])],
            "model": {"source": selected.source, "model": selected.model, "endpoint": selected.base_url,
                      "effort": selected.effort} if selected is not None else None,
        })

        def existing_response():
            if existing["request_fingerprint"] != fingerprint:
                raise HTTPException(409, detail={"code": "run_id_conflict", "message": "run_id 已用于其他请求，请使用新的运行 ID。"})
            return StreamingResponse(
                _stream_replay(run_id, user_id=user_id, session_id=thread_id, store=store),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no", "X-Run-Id": run_id},
            )

        if existing is not None:
            # 恢复在配额/模型预检之前完成；供应商故障也不能阻止读回已完成答案。
            return existing_response()
        if not _generation_enabled():
            raise HTTPException(status_code=503, detail={"code": "generation_disabled", "message": "生成服务维护中"})
        _enforce_user_quota(http_request)
        await ensure_model_available()
        if store is not None:
            try:
                existing, created = await asyncio.to_thread(
                    store.begin, user_id=user_id, run_id=run_id, session_id=thread_id, query=request.query,
                    fingerprint=fingerprint, user_message_id=request.client_user_message_id,
                    assistant_message_id=request.client_assistant_message_id,
                )
            except ResearchRunConflict as exc:
                raise HTTPException(409, detail={"code": "run_id_conflict", "message": "运行或消息 ID 已被使用，请恢复原运行或使用新 ID。"}) from exc
            except Exception as exc:
                raise HTTPException(503, detail={"code": "run_store_unavailable", "message": "研究记录保存失败，本轮尚未启动，请稍后重试。"}) from exc
            if not created:
                return existing_response()
        _register_run_owner(run_id, user_id)

        pipeline = run_graph_pipeline(
            deps=_build_execution_deps(deps, _persist_callback(store, run_id, user_id)),
            query=request.query,
            thread_id=thread_id,
            run_id=run_id,
            ui_context=_request_ui_context(request, user_id),
            output_mode=output_mode,
            strict_selection=strict_selection,
            original_query=request.query,
            source=request.source or "chat",
            user_id=user_id,
            trace_raw_enabled=bool(trace_raw),
        )
        return _buffered_sse_response(pipeline, run_id=run_id, thread_id=thread_id, user_id=user_id, store=store)

    @router.get("/api/execute/runs/{run_id}")
    async def get_run(run_id: str, http_request: Request):
        normalized = _normalize_run_id(run_id)
        user_id = _request_user_id(http_request)
        store = _store_for_user(user_id)
        row = await _load_run(store, normalized, user_id) if store is not None else None
        if row is not None:
            return public_run(row)
        _authorize_run(normalized, user_id)
        raise HTTPException(410, detail={"code": "run_not_durable", "message": "此运行未启用持久化恢复。"})

    @router.get("/api/execute/runs/{run_id}/events")
    async def replay_events(run_id: str, http_request: Request, after_seq: int = 0):
        normalized = _normalize_run_id(run_id)
        user_id = _request_user_id(http_request)
        store = _store_for_user(user_id)
        row = await _load_run(store, normalized, user_id) if store is not None else None
        if row is None:
            _authorize_run(normalized, user_id)
        if row is None and replay_buffer.replay_from(_run_key(normalized, user_id), max(0, after_seq)) is None:
            raise HTTPException(status_code=410, detail={"code": "run_expired", "message": "stream expired"})
        return StreamingResponse(
            _stream_replay(normalized, user_id=user_id, after_seq=after_seq, store=store),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    @router.post("/api/execute/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, http_request: Request):
        normalized = _normalize_run_id(run_id)
        user_id = _request_user_id(http_request)
        store = _store_for_user(user_id)
        row = await _load_run(store, normalized, user_id) if store is not None else None
        if row is None:
            _authorize_run(normalized, user_id)
        task = _STREAM_TASKS_BY_RUN.get(_run_key(normalized, user_id))
        if task is None or task.done():
            raise HTTPException(status_code=409, detail={"code": "run_not_active", "message": "run is not active"})
        task.cancel()
        return {"cancelled": True, "run_id": normalized}

    return router


__all__ = ["ExecuteRequest", "ExecutionRouterDeps", "create_execution_router"]
