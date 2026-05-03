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


def create_conversation_router(deps: ConversationRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Conversations"])

    def _resolve_or_422(session_id: Optional[str]) -> str:
        try:
            return deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/api/conversations")
    async def list_conversations():
        items = deps.list_session_contexts()
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
        return {
            "success": True,
            "session_id": session_id,
            "conversation": _context_summary(session_id, manager),
        }

    @router.get("/api/conversations/{session_id}")
    async def get_conversation(session_id: str):
        normalized = _resolve_or_422(session_id)
        manager = deps.get_session_context(normalized)
        return {
            "success": True,
            "session_id": normalized,
            "conversation": _context_summary(normalized, manager),
        }

    @router.delete("/api/conversations/{session_id}")
    async def delete_conversation(session_id: str):
        normalized = _resolve_or_422(session_id)
        cleared = deps.clear_session_context(normalized)
        return {
            "success": True,
            "session_id": normalized,
            "cleared": cleared,
        }

    return router
