# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import FastAPI, Request
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


def _build_client() -> tuple[TestClient, list[tuple[str, str]]]:
    cleared: list[tuple[str, str]] = []
    contexts = {"public:user:thread": _FakeContext()}
    records: dict[tuple[str, str], dict] = {
        ("user", "public:user:thread"): {"session_id": "public:user:thread"},
    }

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

    async def clear_session_context(session_id: str, user_id: str):
        cleared.append((session_id, user_id))
        contexts.pop(session_id, None)
        return {"context": True, "reports": 1, "rag_collections": 2}

    def upsert_record(session_id: str, payload: dict, user_id: str):
        record = {"session_id": session_id, **payload}
        records[(user_id, session_id)] = record
        return dict(record)

    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "user")
        return await call_next(request)

    app.include_router(
        create_conversation_router(
            ConversationRouterDeps(
                resolve_thread_id=resolve_thread_id,
                get_session_context=get_session_context,
                list_session_contexts=list_session_contexts,
                clear_session_context=clear_session_context,
                list_conversation_records=lambda user_id: [
                    dict(record)
                    for (owner, _), record in records.items()
                    if owner == user_id
                ],
                get_conversation_record=lambda session_id, user_id: records.get((user_id, session_id)),
                upsert_conversation_record=upsert_record,
                delete_conversation_record=lambda session_id, user_id: records.pop(
                    (user_id, session_id), None
                ) is not None,
            )
        )
    )
    return TestClient(app), cleared


def _build_store_client() -> tuple[TestClient, dict[tuple[str, str], dict]]:
    contexts = {"public:user:thread": _FakeContext()}
    records: dict[tuple[str, str], dict] = {}

    def resolve_thread_id(session_id: str | None) -> str:
        return session_id or "public:anonymous:new-thread"

    def get_session_context(session_id: str):
        return contexts.setdefault(session_id, _FakeContext())

    def list_session_contexts():
        return [{"session_id": session_id, "turns": context.get_state()["turns"]} for session_id, context in contexts.items()]

    def upsert_record(session_id: str, payload: dict, user_id: str):
        key = (user_id, session_id)
        current = dict(records.get(key) or {"session_id": session_id, "messages": []})
        if "title" in payload:
            current["title"] = payload["title"]
        if "messages" in payload:
            current["messages"] = payload["messages"]
            current["message_count"] = len(payload["messages"])
        records[key] = current
        return dict(current)

    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "user")
        return await call_next(request)

    app.include_router(
        create_conversation_router(
            ConversationRouterDeps(
                resolve_thread_id=resolve_thread_id,
                get_session_context=get_session_context,
                list_session_contexts=list_session_contexts,
                clear_session_context=lambda session_id, _user_id: {
                    "context": contexts.pop(session_id, None) is not None
                },
                list_conversation_records=lambda user_id: [
                    dict(record)
                    for (owner, _), record in records.items()
                    if owner == user_id
                ],
                get_conversation_record=lambda session_id, user_id: records.get((user_id, session_id)),
                upsert_conversation_record=upsert_record,
                delete_conversation_record=lambda session_id, user_id: records.pop(
                    (user_id, session_id), None
                ) is not None,
            )
        )
    )
    return TestClient(app), records


def test_conversation_router_create_get_list_and_delete_flow():
    client, cleared = _build_client()

    created = client.post("/api/conversations", json={}).json()
    assert created["success"] is True
    assert created["session_id"] == "public:user:new-thread"
    assert created["conversation"]["turns"] == 2

    listed = client.get("/api/conversations").json()
    assert listed["success"] is True
    assert listed["count"] >= 1
    assert any(item["session_id"] == "public:user:new-thread" for item in listed["items"])

    detail = client.get("/api/conversations/public:user:thread").json()
    assert detail["success"] is True
    assert detail["conversation"]["current_focus"] == "AAPL"

    deleted = client.delete("/api/conversations/public:user:thread").json()
    assert deleted["success"] is True
    assert deleted["session_id"] == "public:user:thread"
    assert deleted["cleared"] == {
        "context": True,
        "reports": 1,
        "rag_collections": 2,
        "conversation_store": 1,
    }
    assert cleared == [("public:user:thread", "user")]


def test_conversation_router_persists_messages_and_deletes_record():
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
    assert records[("user", "public:user:thread")]["messages"][0]["content"] == "GOOGL news"

    listed = client.get("/api/conversations").json()
    assert any(
        item["session_id"] == "public:user:thread" and item["title"] == "Google follow-up"
        for item in listed["items"]
    )

    deleted = client.delete("/api/conversations/public:user:thread").json()
    assert deleted["cleared"]["conversation_store"] == 1
    assert ("user", "public:user:thread") not in records


def test_conversation_router_rejects_bad_session_id():
    def resolve_thread_id(_session_id: str | None) -> str:
        raise ValueError("session_id format invalid")

    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = "user"
        return await call_next(request)

    app.include_router(
        create_conversation_router(
            ConversationRouterDeps(
                resolve_thread_id=resolve_thread_id,
                get_session_context=lambda _session_id: object(),
                list_session_contexts=lambda: [],
                clear_session_context=lambda _session_id, _user_id: {},
            )
        )
    )

    response = TestClient(app).delete("/api/conversations/bad")

    assert response.status_code == 422
    assert "session_id" in response.text


def test_conversation_router_rejects_anonymous_and_cross_user_session_access():
    client, records = _build_store_client()
    alice = {"x-test-user": "alice"}
    bob = {"x-test-user": "bob"}

    anonymous = client.get("/api/conversations", headers={"x-test-user": "public"})
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"]["code"] == "auth_required"

    created = client.post(
        "/api/conversations",
        headers=bob,
        json={"session_id": "public:bob:thread", "title": "Bob private"},
    )
    assert created.status_code == 200
    assert ("bob", "public:bob:thread") in records

    forged_create = client.post(
        "/api/conversations",
        headers=alice,
        json={"session_id": "public:bob:thread", "title": "Forged"},
    )
    forged_get = client.get("/api/conversations/public:bob:thread", headers=alice)
    forged_delete = client.delete("/api/conversations/public:bob:thread", headers=alice)
    missing_get = client.get("/api/conversations/public:alice:missing", headers=alice)
    missing_delete = client.delete("/api/conversations/public:alice:missing", headers=alice)

    assert forged_create.status_code == 404
    assert forged_get.status_code == 404
    assert forged_delete.status_code == 404
    assert missing_get.status_code == 200
    assert missing_get.json()["conversation"] == {"session_id": "public:alice:missing"}
    assert missing_delete.status_code == 404
    assert ("alice", "public:bob:thread") not in records
    assert ("bob", "public:bob:thread") in records
