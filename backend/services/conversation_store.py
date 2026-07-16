# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from threading import Lock
from typing import Any

from sqlalchemy import text

from backend.services.database import create_core_engine, resolve_core_postgres_dsn


_STORE_LOCK = Lock()
_STORE_SINGLETON: "PostgresConversationStore | UnavailableConversationStore | None" = None


def _sanitize_message(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    role = str(item.get("role") or "").strip().lower()
    if role not in {"user", "assistant", "system", "tool"}:
        return None
    content = str(item.get("content") or "").strip()
    if not content:
        return None
    row: dict[str, Any] = {
        "role": role,
        "content": content[:20000],
    }
    message_id = str(item.get("id") or "").strip()
    if message_id:
        row["id"] = message_id[:128]
    timestamp = item.get("timestamp")
    if isinstance(timestamp, (int, float)):
        row["timestamp"] = timestamp
    return row


def _sanitize_messages(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    messages: list[dict[str, Any]] = []
    for item in rows[-200:]:
        message = _sanitize_message(item)
        if message:
            messages.append(message)
    return messages


def _derive_title(messages: list[dict[str, Any]], fallback: str = "新对话") -> str:
    for item in messages:
        if item.get("role") != "user":
            continue
        content = str(item.get("content") or "").strip()
        if content:
            return content.replace("\n", " ").strip()[:42] or fallback
    return fallback


def _derive_preview(messages: list[dict[str, Any]]) -> str:
    for item in reversed(messages):
        content = str(item.get("content") or "").strip()
        if content:
            return content.replace("\n", " ").strip()[:90]
    return ""


class ConversationStoreUnavailable(RuntimeError):
    pass


class UnavailableConversationStore:
    def __getattr__(self, _name: str):
        def unavailable(*_args, **_kwargs):
            raise ConversationStoreUnavailable("conversation postgres unavailable")

        return unavailable


def _authenticated_user_id(user_id: str) -> str:
    normalized = str(user_id or "").strip()
    if not normalized or normalized == "public":
        raise ConversationStoreUnavailable("conversation store requires authenticated user")
    return normalized


def _epoch(value: Any) -> float:
    if hasattr(value, "timestamp"):
        return float(value.timestamp())
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _conversation_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    messages = data.get("messages")
    if isinstance(messages, str):
        try:
            messages = json.loads(messages)
        except Exception:
            messages = []
    return {
        "session_id": str(data.get("session_id") or ""),
        "title": str(data.get("title") or "新对话"),
        "messages": messages if isinstance(messages, list) else [],
        "message_count": int(data.get("message_count") or 0),
        "last_message_preview": str(data.get("last_message_preview") or ""),
        "pinned": bool(data.get("pinned")),
        "archived": bool(data.get("archived")),
        "created_at": _epoch(data.get("created_at")),
        "updated_at": _epoch(data.get("updated_at")),
    }


class PostgresConversationStore:
    """按 ``user_id`` 隔离的 PostgreSQL 会话快照存储。"""

    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        self._engine = engine if engine is not None else create_core_engine(dsn=dsn)

    def get(self, session_id: str, user_id: str = "public") -> dict[str, Any] | None:
        sid = str(session_id or "").strip()
        if not sid:
            return None
        owner = _authenticated_user_id(user_id)
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT * FROM conversation_threads "
                    "WHERE user_id=:user_id AND session_id=:session_id"
                ),
                {"user_id": owner, "session_id": sid},
            ).mappings().first()
        return _conversation_row(row) if row else None

    def list(
        self,
        *,
        include_archived: bool = False,
        user_id: str = "public",
    ) -> list[dict[str, Any]]:
        owner = _authenticated_user_id(user_id)
        where = "user_id=:user_id"
        if not include_archived:
            where += " AND archived=false"
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT * FROM conversation_threads WHERE {where} ORDER BY updated_at DESC"),
                {"user_id": owner},
            ).mappings().all()
        return [_conversation_row(row) for row in rows]

    def upsert(
        self,
        session_id: str,
        payload: dict[str, Any] | None = None,
        user_id: str = "public",
    ) -> dict[str, Any]:
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id required")
        owner = _authenticated_user_id(user_id)
        data = payload if isinstance(payload, dict) else {}
        current = self.get(sid, owner) or {}
        messages = (
            _sanitize_messages(data.get("messages"))
            if "messages" in data
            else list(current.get("messages") if isinstance(current.get("messages"), list) else [])
        )
        title = str(data.get("title") or current.get("title") or "").strip()[:80]
        if not title:
            title = _derive_title(messages)
        params = {
            "user_id": owner,
            "session_id": sid,
            "title": title,
            "messages": json.dumps(messages, ensure_ascii=False),
            "message_count": len(messages),
            "last_message_preview": _derive_preview(messages),
            "pinned": bool(data.get("pinned", current.get("pinned", False))),
            "archived": bool(data.get("archived", current.get("archived", False))),
        }
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO conversation_threads "
                    "(user_id,session_id,title,messages,message_count,last_message_preview,pinned,archived) "
                    "VALUES (:user_id,:session_id,:title,CAST(:messages AS jsonb),:message_count,"
                    ":last_message_preview,:pinned,:archived) "
                    "ON CONFLICT(user_id,session_id) DO UPDATE SET "
                    "title=excluded.title,messages=excluded.messages,message_count=excluded.message_count,"
                    "last_message_preview=excluded.last_message_preview,pinned=excluded.pinned,"
                    "archived=excluded.archived,updated_at=now() RETURNING *"
                ),
                params,
            ).mappings().one()
        return _conversation_row(row)

    def patch(
        self,
        session_id: str,
        payload: dict[str, Any],
        user_id: str = "public",
    ) -> dict[str, Any]:
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id required")
        owner = _authenticated_user_id(user_id)
        current = self.get(sid, owner) or {"messages": []}
        allowed = {key: value for key, value in dict(payload or {}).items() if key in {"title", "messages", "pinned", "archived"}}
        return self.upsert(sid, current | allowed, owner)

    def delete(self, session_id: str, user_id: str = "public") -> bool:
        sid = str(session_id or "").strip()
        if not sid:
            return False
        owner = _authenticated_user_id(user_id)
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM conversation_threads "
                    "WHERE user_id=:user_id AND session_id=:session_id"
                ),
                {"user_id": owner, "session_id": sid},
            )
        return bool(result.rowcount)


ConversationStore = PostgresConversationStore


def get_conversation_store() -> PostgresConversationStore | UnavailableConversationStore:
    global _STORE_SINGLETON
    with _STORE_LOCK:
        if _STORE_SINGLETON is None:
            dsn = resolve_core_postgres_dsn(required=False)
            try:
                _STORE_SINGLETON = PostgresConversationStore(dsn=dsn) if dsn else UnavailableConversationStore()
            except Exception:
                _STORE_SINGLETON = UnavailableConversationStore()
        return _STORE_SINGLETON


def reset_conversation_store_cache() -> None:
    global _STORE_SINGLETON
    with _STORE_LOCK:
        _STORE_SINGLETON = None


__all__ = [
    "ConversationStore",
    "ConversationStoreUnavailable",
    "PostgresConversationStore",
    "get_conversation_store",
    "reset_conversation_store_cache",
]
