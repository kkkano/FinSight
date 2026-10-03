from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from backend.services.conversation_store import ConversationVersionConflict


@dataclass(frozen=True)
class ConversationRouterDeps:
    resolve_thread_id: Callable[[Optional[str]], str]
    get_session_context: Callable[[str], Any]
    list_session_contexts: Callable[[], list[dict[str, Any]]]
    clear_session_context: Callable[[str, str], Any]
    list_conversation_records: Callable[[str], list[dict[str, Any]]] | None = None
    get_conversation_record: Callable[[str, str], dict[str, Any] | None] | None = None
    upsert_conversation_record: Callable[[str, dict[str, Any], str], dict[str, Any]] | None = None
    delete_conversation_record: Callable[[str, str], bool] | None = None


def _context_summary(session_id: str, manager: Any) -> dict[str, Any]:
    state: dict[str, Any] = {}
    get_state = getattr(manager, "get_state", None)
    if callable(get_state):
        try:
            value = get_state()
            if isinstance(value, dict):
                state = value
        except Exception:
            state = {}

    return {
        "session_id": session_id,
        "turns": int(state.get("turns") or 0),
        "current_focus": state.get("current_focus"),
        "current_focus_name": state.get("current_focus_name"),
        "current_focus_market": state.get("current_focus_market"),
        "pending_clarification": bool(state.get("pending_clarification")),
        "cached_data_keys": state.get("cached_data_keys") if isinstance(state.get("cached_data_keys"), list) else [],
    }


def _merge_conversation(
    *,
    session_id: str,
    context: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {"session_id": session_id}
    if isinstance(record, dict):
        merged.update(record)
    if isinstance(context, dict):
        merged.update({k: v for k, v in context.items() if k not in {"session_id"}})
        merged["backend_context"] = context
    merged["session_id"] = session_id
    return merged


def create_conversation_router(deps: ConversationRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Conversations"])

    def _resolve_or_422(session_id: Optional[str]) -> str:
        if session_id is not None and not isinstance(session_id, str):
            raise HTTPException(status_code=422, detail="session_id must be a string")
        try:
            return deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def _authenticated_user(request: Request) -> str:
        user_id = str(getattr(request.state, "user_id", "public") or "public").strip()
        if not user_id or user_id == "public":
            raise HTTPException(
                status_code=401,
                detail={"code": "auth_required", "message": "登录后才能访问会话"},
            )
        return user_id

    def _belongs_to_user(session_id: str, user_id: str) -> bool:
        parts = str(session_id or "").split(":")
        return len(parts) == 3 and parts[1] == user_id

    def _owned_session(
        session_id: Optional[str],
        request: Request,
        *,
        generate_when_missing: bool = False,
    ) -> tuple[str, str]:
        user_id = _authenticated_user(request)
        normalized = _resolve_or_422(session_id)
        if generate_when_missing and not str(session_id or "").strip():
            parts = normalized.split(":")
            if len(parts) != 3:
                raise HTTPException(status_code=422, detail="session_id format invalid")
            parts[1] = user_id
            normalized = _resolve_or_422(":".join(parts))
        if not _belongs_to_user(normalized, user_id):
            # 对不存在与无权访问统一返回 404，避免泄露其他用户的线程标识。
            raise HTTPException(status_code=404, detail="conversation not found")
        return normalized, user_id

    @router.get("/api/conversations")
    async def list_conversations(request: Request):
        user_id = _authenticated_user(request)
        context_items = deps.list_session_contexts()
        context_by_session = {
            str(item.get("session_id") or ""): item
            for item in context_items
            if _belongs_to_user(str(item.get("session_id") or "").strip(), user_id)
        }
        records = await asyncio.to_thread(deps.list_conversation_records, user_id) if deps.list_conversation_records else []
        items: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            session_id = str(record.get("session_id") or "").strip()
            if not session_id or not _belongs_to_user(session_id, user_id):
                continue
            items.append(
                _merge_conversation(
                    session_id=session_id,
                    context=context_by_session.get(session_id),
                    record=record,
                )
            )
        return {
            "success": True,
            "items": items,
            "count": len(items),
        }

    @router.post("/api/conversations")
    async def create_conversation(http_request: Request, request: dict | None = None):
        payload = request if isinstance(request, dict) else {}
        session_id, user_id = _owned_session(
            payload.get("session_id"),
            http_request,
            generate_when_missing=True,
        )
        manager = deps.get_session_context(session_id)
        try:
            record = (
                await asyncio.to_thread(deps.upsert_conversation_record, session_id, payload, user_id)
                if deps.upsert_conversation_record else None
            )
        except ConversationVersionConflict as exc:
            raise HTTPException(409, detail={"code": "conversation_version_conflict", "message": "会话已更新，请读取最新内容后再保存。"}) from exc
        return {
            "success": True,
            "session_id": session_id,
            "conversation": _merge_conversation(
                session_id=session_id,
                context=_context_summary(session_id, manager),
                record=record,
            ),
        }

    @router.get("/api/conversations/{session_id}")
    async def get_conversation(session_id: str, request: Request):
        normalized, user_id = _owned_session(session_id, request)
        record = await asyncio.to_thread(deps.get_conversation_record, normalized, user_id) if deps.get_conversation_record else None
        manager = deps.get_session_context(normalized) if record is not None else None
        return {
            "success": True,
            "session_id": normalized,
            "conversation": _merge_conversation(
                session_id=normalized,
                context=_context_summary(normalized, manager) if manager is not None else None,
                record=record,
            ),
        }

    @router.delete("/api/conversations/{session_id}")
    async def delete_conversation(session_id: str, request: Request):
        normalized, user_id = _owned_session(session_id, request)
        owned_record = (
            await asyncio.to_thread(deps.get_conversation_record, normalized, user_id)
            if deps.get_conversation_record
            else None
        )
        if deps.get_conversation_record and owned_record is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        cleared: dict[str, Any] = {}
        if owned_record is not None:
            clear_result = deps.clear_session_context(normalized, user_id)
            if inspect.isawaitable(clear_result):
                clear_result = await clear_result
            if isinstance(clear_result, dict):
                cleared = clear_result
        if deps.delete_conversation_record:
            cleared = dict(cleared)
            cleared["conversation_store"] = (
                1 if await asyncio.to_thread(deps.delete_conversation_record, normalized, user_id) else 0
            )
        return {
            "success": True,
            "session_id": normalized,
            "cleared": cleared,
        }

    return router
