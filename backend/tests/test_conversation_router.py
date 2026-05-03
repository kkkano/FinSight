# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.conversation_router import ConversationRouterDeps, create_conversation_router


class _FakeContext:
    def __init__(self) -> None:
        self._state = {
            "turns": 2,
            "current_focus": "AAPL",
            "pending_clarification": False,
            "cached_data_keys": ["price:AAPL"],
        }

    def get_state(self) -> dict:
        return dict(self._state)


def _build_client() -> tuple[TestClient, list[str]]:
    cleared: list[str] = []
    contexts = {"public:user:thread": _FakeContext()}

    def resolve_thread_id(session_id: str | None) -> str:
        return session_id or "public:anonymous:new-thread"

    def get_session_context(session_id: str):
        return contexts.setdefault(session_id, _FakeContext())

    def list_session_contexts():
        return [
            {
                "session_id": session_id,
                "turns": context.get_state()["turns"],
                "current_focus": context.get_state()["current_focus"],
                "last_access": 123.0,
            }
            for session_id, context in contexts.items()
        ]

    def clear_session_context(session_id: str):
        cleared.append(session_id)
        contexts.pop(session_id, None)
        return {"context": True, "reports": 1, "rag_collections": 2}

    app = FastAPI()
    app.include_router(
        create_conversation_router(
            ConversationRouterDeps(
                resolve_thread_id=resolve_thread_id,
                get_session_context=get_session_context,
                list_session_contexts=list_session_contexts,
                clear_session_context=clear_session_context,
            )
        )
    )
    return TestClient(app), cleared


def test_conversation_router_create_get_list_and_delete_flow():
    client, cleared = _build_client()

    created = client.post("/api/conversations", json={}).json()
    assert created["success"] is True
    assert created["session_id"] == "public:anonymous:new-thread"
    assert created["conversation"]["turns"] == 2

    listed = client.get("/api/conversations").json()
    assert listed["success"] is True
    assert listed["count"] >= 1
    assert any(item["session_id"] == "public:anonymous:new-thread" for item in listed["items"])

    detail = client.get("/api/conversations/public:user:thread").json()
    assert detail["success"] is True
    assert detail["conversation"]["current_focus"] == "AAPL"

    deleted = client.delete("/api/conversations/public:user:thread").json()
    assert deleted["success"] is True
    assert deleted["session_id"] == "public:user:thread"
    assert deleted["cleared"] == {"context": True, "reports": 1, "rag_collections": 2}
    assert cleared == ["public:user:thread"]


def test_conversation_router_rejects_bad_session_id():
    def resolve_thread_id(_session_id: str | None) -> str:
        raise ValueError("session_id format invalid")

    app = FastAPI()
    app.include_router(
        create_conversation_router(
            ConversationRouterDeps(
                resolve_thread_id=resolve_thread_id,
                get_session_context=lambda _session_id: object(),
                list_session_contexts=lambda: [],
                clear_session_context=lambda _session_id: {},
            )
        )
    )

    response = TestClient(app).delete("/api/conversations/bad")

    assert response.status_code == 422
    assert "session_id" in response.text
