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
from pydantic import BaseModel, Field, field_validator

from backend.api.schemas import ChatContext, ChatMessage, ChatOptions
from backend.api.session_context import SessionOwnershipError, _resolve_owned_thread_id
from backend.api.stream_replay import replay_buffer
from backend.services.execution_service import ExecutionDeps, run_graph_pipeline
from backend.services.model_preflight import ensure_model_available
from backend.services.run_context import RunContext, run_context_scope
from backend.services.research_run_store import (
    HEARTBEAT_SECONDS, PostgresResearchRunStore, ResearchRunConflict,
    get_research_run_store, public_run, request_fingerprint,
)


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_STREAM_TASKS: set[asyncio.Task[Any]] = set()
_STREAM_TASKS_BY_RUN: dict[str, asyncio.Task[Any]] = {}
_ENTRY_TASKS_BY_RUN: dict[str, asyncio.Task[Any]] = {}
_RUN_OWNERS: OrderedDict[str, str] = OrderedDict()
_MAX_RUN_OWNERS = 256
logger = logging.getLogger(__name__)


class ResearchImage(BaseModel):
    data_url: str = Field(..., max_length=2_800_000)
    name: str | None = Field(None, max_length=128)

    @field_validator("data_url")
    @classmethod
    def valid_png(cls, value):
        from backend.agent_runtime.vision import validate_png_data_url
        validate_png_data_url(value)
        return value


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
    show_provider_reasoning: bool = True
    resume_from_run_id: str | None = Field(None, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    images: list[ResearchImage] = Field(default_factory=list, max_length=3)
    skill_ids: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("skill_ids")
    @classmethod
    def valid_skills(cls, value):
        from backend.agent_runtime.skills import validate_skill_ids
        return validate_skill_ids(value)

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


class InstructionRequest(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=8000)
    instruction_id: str = Field(..., min_length=1, max_length=128)


class ActionConfirmation(BaseModel):
    payload_hash: str = Field(..., min_length=64, max_length=64)
    confirmed: bool


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
                "success": False, "answer_status": "partial" if event.get("response") else "unavailable",
                "runtime_type": "delivery.persistence_unconfirmed",
                "publishable": False, "error_code": "conversation_persistence_failed",
                "failure_kind": "persistence_error",
                "persistence_message": "回答已生成，但服务器保存失败；请保留当前页面内容，稍后恢复。",
            }
    return persist


async def _durable_replay(store, run_id: str, user_id: str, *, after_seq: int = 0):
    last_checkpoint_seq = -1
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
            cursor = max(0, after_seq, last_checkpoint_seq)
            if payload.get("blocks"):
                cursor += 1
                snapshot = {"blocks": payload["blocks"], "committed_seq": cursor}
                yield f"data: {_serialize_sse_item({'schema_version': '2', 'type': 'snapshot.reset', 'run_id': run_id, 'session_id': row['session_id'], 'stream_epoch': 'recovered:' + run_id, 'seq': cursor, 'payload': snapshot})}\n\n"
            payload.update({"recovered": True, "seq": cursor + 1})
            yield f"data: {_serialize_sse_item(payload)}\n\n"
            return
        if hasattr(store, "get_checkpoint"):
            try:
                snapshot = await asyncio.to_thread(store.get_checkpoint, run_id, user_id=user_id)
            except Exception:
                yield f"data: {_serialize_sse_item({'type': 'error', 'code': 'run_store_unavailable', 'message': '研究记录暂时无法读取，请稍后恢复。', 'run_id': run_id})}\n\n"
                return
            if snapshot and snapshot.get("committed_seq", 0) > last_checkpoint_seq:
                last_checkpoint_seq = snapshot["committed_seq"]
                yield f"data: {_serialize_sse_item({'schema_version': '2', 'type': 'snapshot.reset', 'run_id': run_id, 'session_id': row['session_id'], 'stream_epoch': snapshot.get('stream_epoch'), 'seq': last_checkpoint_seq, 'payload': snapshot})}\n\n"
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
    ui_context["show_provider_reasoning"] = request.show_provider_reasoning
    ui_context["skill_ids"] = request.skill_ids
    if request.resume_from_run_id:
        ui_context["resume_from_run_id"] = request.resume_from_run_id
    if request.images:
        ui_context["images"] = [image.model_dump(exclude_none=True) for image in request.images]
    return ui_context


async def _native_pipeline_with_preflight(**kwargs):
    """先建立SSE并回执，冷启动能力验证不再造成数十秒无响应。"""
    from backend.agent_runtime.service import preflight, run_agent_pipeline
    context = kwargs["run_context"]
    base = {"schema_version": "2", "run_id": kwargs["run_id"], "session_id": kwargs["thread_id"]}
    yield {**base, "type": "activity.started", "payload": {"activity_id": "model_capability", "title": "正在验证模型工具能力"}}
    with run_context_scope(context):
        try:
            await preflight(context)
        except HTTPException as exc:
            context.finish("failed")
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            yield {**base, "type": "error", "success": False, "publishable": False,
                   "run_status": "failed", "error_code": detail.get("code", "model_preflight_failed"),
                   "message": detail.get("message", "模型能力未通过验证。"), "metrics": context.usage.summary()}
            await context.archive_usage()
            return
    yield {**base, "type": "activity.finished", "payload": {"activity_id": "model_capability", "status": "completed", "title": "模型工具能力已验证"}}
    async for event in run_agent_pipeline(**kwargs, initial_seq=2):
        yield event


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
            "resume_from_run_id": request.resume_from_run_id,
            **({"skill_ids": request.skill_ids} if request.skill_ids else {}),
            "image_hashes": [__import__("hashlib").sha256(image.data_url.encode()).hexdigest() for image in request.images],
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
        if request.resume_from_run_id:
            parent = await _load_run(store, request.resume_from_run_id, user_id) if store is not None else None
            if parent is None or parent["session_id"] != thread_id:
                raise HTTPException(404, detail={"code": "parent_run_not_found", "message": "续研资料不属于当前会话或已不可用。"})
        if not _generation_enabled():
            raise HTTPException(status_code=503, detail={"code": "generation_disabled", "message": "生成服务维护中"})
        _enforce_user_quota(http_request)
        if request.images:
            from backend.agent_runtime.config import enabled as agent_runtime_enabled, resolve_model
            from backend.services.model_selection import model_capabilities
            chosen = resolve_model()
            if not agent_runtime_enabled() or model_capabilities(chosen.model, chosen.base_url).get("vision") is not True:
                raise HTTPException(422, detail={"code": "model_vision_unverified", "message": "该模型图片能力尚未确认，请移除图片或选择已验证模型。"})
        run_context = RunContext.create(owner=user_id, entry=output_mode or "chat", run_id=run_id)
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

        run_key = _run_key(run_id, user_id)
        entry_task = asyncio.current_task()
        if entry_task is not None:
            _ENTRY_TASKS_BY_RUN[run_key] = entry_task
        with run_context_scope(run_context):
            try:
                from backend.agent_runtime.config import enabled as agent_runtime_enabled
                if not agent_runtime_enabled():
                    await ensure_model_available()
            except BaseException as exc:
                cancelled = isinstance(exc, asyncio.CancelledError)
                run_context.finish("cancelled" if cancelled else "failed")
                detail = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else {}
                payload = {"type": "cancelled" if cancelled else "error", "publishable": False,
                    "answer_status": "unavailable", "error_code": detail.get("code", "model_preflight_failed"),
                    "message": "已停止生成，可重新生成。" if cancelled else detail.get("message", "模型前置检查未完成。"),
                    "metrics": run_context.usage.summary()}
                if store is not None:
                    await _persist_callback(store, run_id, user_id)(payload)
                await run_context.archive_usage()
                raise
            finally:
                if _ENTRY_TASKS_BY_RUN.get(run_key) is entry_task:
                    _ENTRY_TASKS_BY_RUN.pop(run_key, None)

        from backend.agent_runtime.config import enabled as agent_runtime_enabled
        pipeline_factory = run_graph_pipeline
        pipeline_extra = {}
        if agent_runtime_enabled():
            pipeline_factory = _native_pipeline_with_preflight
            pipeline_extra["message_id"] = (existing or {}).get("assistant_message_id") or request.client_assistant_message_id
            if store is not None:
                async def checkpoint(snapshot):
                    return await asyncio.to_thread(store.checkpoint, run_id, snapshot, user_id=user_id)
                pipeline_extra["checkpoint"] = checkpoint
        pipeline = pipeline_factory(
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
            run_context=run_context,
            **pipeline_extra,
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
        task = _STREAM_TASKS_BY_RUN.get(_run_key(normalized, user_id)) or _ENTRY_TASKS_BY_RUN.get(_run_key(normalized, user_id))
        if task is None or task.done():
            raise HTTPException(status_code=409, detail={"code": "run_not_active", "message": "run is not active"})
        task.cancel()
        return {"cancelled": True, "run_id": normalized}

    @router.post("/api/execute/runs/{run_id}/instructions")
    async def submit_instruction(run_id: str, payload: InstructionRequest, http_request: Request):
        from backend.agent_runtime.service import add_instruction
        owner = _request_user_id(http_request)
        normalized = _normalize_run_id(run_id)
        _authorize_run(normalized, owner)
        try:
            return add_instruction(owner, normalized, payload.instruction, payload.instruction_id)
        except ValueError as exc:
            raise HTTPException(409, detail={"code": str(exc), "message": "本轮已结束或追加要求未被接收，请新建一轮。"}) from None

    @router.post("/api/execute/runs/{run_id}/actions/{action_id}/confirm")
    async def confirm_runtime_action(run_id: str, action_id: str, payload: ActionConfirmation, http_request: Request):
        from backend.agent_runtime.service import confirm_action
        owner = _request_user_id(http_request)
        normalized = _normalize_run_id(run_id)
        store = _store_for_user(owner)
        row = await _load_run(store, normalized, owner) if store is not None else None
        if row is None:
            _authorize_run(normalized, owner)
        try:
            return await confirm_action(owner, normalized, action_id, payload.payload_hash, payload.confirmed)
        except ValueError:
            raise HTTPException(404, detail={"code": "action_not_found", "message": "操作不存在、已过期或不属于当前用户。"}) from None

    return router


__all__ = ["ExecuteRequest", "ExecutionRouterDeps", "create_execution_router"]
