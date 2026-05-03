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


def _build_store_client() -> tuple[TestClient, dict[str, dict]]:
    contexts = {"public:user:thread": _FakeContext()}
    records: dict[str, dict] = {}

    def resolve_thread_id(session_id: str | None) -> str:
        return session_id or "public:anonymous:new-thread"

    def get_session_context(session_id: str):
        return contexts.setdefault(session_id, _FakeContext())

    def list_session_contexts():
        return [{"session_id": session_id, "turns": context.get_state()["turns"]} for session_id, context in contexts.items()]

    def upsert_record(session_id: str, payload: dict):
        current = dict(records.get(session_id) or {"session_id": session_id, "messages": []})
        if "title" in payload:
            current["title"] = payload["title"]
        if "messages" in payload:
            current["messages"] = payload["messages"]
            current["message_count"] = len(payload["messages"])
        records[session_id] = current
        return dict(current)

    def patch_record(session_id: str, payload: dict):
        current = dict(records.get(session_id) or {"session_id": session_id, "messages": []})
        current.update(payload)
        records[session_id] = current
        return dict(current)

    app = FastAPI()
    app.include_router(
        create_conversation_router(
            ConversationRouterDeps(
                resolve_thread_id=resolve_thread_id,
                get_session_context=get_session_context,
                list_session_contexts=list_session_contexts,
                clear_session_context=lambda session_id: {"context": contexts.pop(session_id, None) is not None},
                list_conversation_records=lambda: list(records.values()),
                get_conversation_record=lambda session_id: records.get(session_id),
                upsert_conversation_record=upsert_record,
                patch_conversation_record=patch_record,
                delete_conversation_record=lambda session_id: records.pop(session_id, None) is not None,
            )
        )
    )
    return TestClient(app), records


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


def test_conversation_router_persists_messages_and_patches_metadata():
    client, records = _build_store_client()

    created = client.post(
        "/api/conversations",
        json={
            "session_id": "public:user:thread",
            "title": "Google follow-up",
            "messages": [{"role": "user", "content": "GOOGL news"}],
        },
    ).json()

    assert created["success"] is True
    assert created["conversation"]["title"] == "Google follow-up"
    assert created["conversation"]["message_count"] == 1
    assert records["public:user:thread"]["messages"][0]["content"] == "GOOGL news"

    patched = client.patch(
        "/api/conversations/public:user:thread",
        json={"title": "Updated title", "pinned": True, "archived": False},
    ).json()

    assert patched["success"] is True
    assert patched["conversation"]["title"] == "Updated title"
    assert patched["conversation"]["pinned"] is True

    listed = client.get("/api/conversations").json()
    assert any(item["session_id"] == "public:user:thread" and item["title"] == "Updated title" for item in listed["items"])

    deleted = client.delete("/api/conversations/public:user:thread").json()
    assert deleted["cleared"]["conversation_store"] == 1
    assert "public:user:thread" not in records


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
