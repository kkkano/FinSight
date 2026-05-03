from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException


@dataclass(frozen=True)
class ConversationRouterDeps:
    resolve_thread_id: Callable[[Optional[str]], str]
    get_session_context: Callable[[str], Any]
    list_session_contexts: Callable[[], list[dict[str, Any]]]
    clear_session_context: Callable[[str], dict[str, Any]]
    list_conversation_records: Callable[[], list[dict[str, Any]]] | None = None
    get_conversation_record: Callable[[str], dict[str, Any] | None] | None = None
    upsert_conversation_record: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
    patch_conversation_record: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
    delete_conversation_record: Callable[[str], bool] | None = None


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
        try:
            return deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/conversations")
    async def list_conversations():
        context_items = deps.list_session_contexts()
        context_by_session = {
            str(item.get("session_id") or ""): item
            for item in context_items
            if str(item.get("session_id") or "").strip()
        }
        records = deps.list_conversation_records() if deps.list_conversation_records else []
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, dict):
                continue
            session_id = str(record.get("session_id") or "").strip()
            if not session_id:
                continue
            seen.add(session_id)
            items.append(
                _merge_conversation(
                    session_id=session_id,
                    context=context_by_session.get(session_id),
                    record=record,
                )
            )
        for session_id, context in context_by_session.items():
            if session_id in seen:
                continue
            items.append(_merge_conversation(session_id=session_id, context=context))
        return {
            "success": True,
            "items": items,
            "count": len(items),
        }

    @router.post("/api/conversations")
    async def create_conversation(request: dict | None = None):
        payload = request if isinstance(request, dict) else {}
        session_id = _resolve_or_422(payload.get("session_id"))
        manager = deps.get_session_context(session_id)
        record = (
            deps.upsert_conversation_record(session_id, payload)
            if deps.upsert_conversation_record
            else None
        )
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
    async def get_conversation(session_id: str):
        normalized = _resolve_or_422(session_id)
        manager = deps.get_session_context(normalized)
        record = deps.get_conversation_record(normalized) if deps.get_conversation_record else None
        return {
            "success": True,
            "session_id": normalized,
            "conversation": _merge_conversation(
                session_id=normalized,
                context=_context_summary(normalized, manager),
                record=record,
            ),
        }

    @router.patch("/api/conversations/{session_id}")
    async def patch_conversation(session_id: str, request: dict | None = None):
        normalized = _resolve_or_422(session_id)
        payload = request if isinstance(request, dict) else {}
        if not deps.patch_conversation_record:
            raise HTTPException(status_code=501, detail="conversation store unavailable")
        record = deps.patch_conversation_record(normalized, payload)
        manager = deps.get_session_context(normalized)
        return {
            "success": True,
            "session_id": normalized,
            "conversation": _merge_conversation(
                session_id=normalized,
                context=_context_summary(normalized, manager),
                record=record,
            ),
        }

    @router.delete("/api/conversations/{session_id}")
    async def delete_conversation(session_id: str):
        normalized = _resolve_or_422(session_id)
        cleared = deps.clear_session_context(normalized)
        if deps.delete_conversation_record:
            cleared = dict(cleared)
            cleared["conversation_store"] = 1 if deps.delete_conversation_record(normalized) else 0
        return {
            "success": True,
            "session_id": normalized,
            "cleared": cleared,
        }

    return router
