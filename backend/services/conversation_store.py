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


class ConversationVersionConflict(ValueError):
    """客户端快照版本已过期，需读回最新会话再合并。"""


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
        "version": int(data.get("version") or 0),
    }


_THREAD_COLUMNS = (
    "user_id,session_id,title,messages,message_count,last_message_preview,"
    "pinned,archived,created_at,updated_at,version"
)


def _configure_owner(conn: Any, owner: str) -> None:
    # SET LOCAL 随事务结束清除，不把租户身份留在连接池中。
    conn.execute(text("SELECT set_config('app.current_user_id', :owner, true), "
                      "set_config('lock_timeout', '5s', true), "
                      "set_config('statement_timeout', '15s', true)"), {"owner": owner})


def _locked_thread(conn: Any, owner: str, sid: str, *, create: bool = True) -> dict[str, Any] | None:
    if create:
        conn.execute(text("INSERT INTO conversation_threads (user_id,session_id,title) "
                          "VALUES (:owner,:sid,'新对话') ON CONFLICT (user_id,session_id) DO NOTHING"),
                     {"owner": owner, "sid": sid})
    row = conn.execute(text(f"SELECT {_THREAD_COLUMNS} FROM conversation_threads "
                            "WHERE user_id=:owner AND session_id=:sid FOR UPDATE"),
                       {"owner": owner, "sid": sid}).mappings().first()
    return _conversation_row(row) if row else None


def _merge_messages(
    current: list[dict[str, Any]], incoming: list[dict[str, Any]], authoritative: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """快照只补充消息；权威消息最后覆盖同 ID，迟到快照不能回滚正文。"""
    result: list[dict[str, Any]] = []
    positions: dict[tuple[Any, ...], int] = {}
    for message in [*current, *incoming, *authoritative]:
        key = ("id", message["id"]) if message.get("id") else (
            "legacy", message.get("role"), message.get("content"), message.get("timestamp"),
        )
        if key in positions:
            result[positions[key]] = dict(message)
        else:
            positions[key] = len(result)
            result.append(dict(message))
    # 重新生成保留运行审计，但会话只显示该用户消息最新运行的回复。
    latest: dict[str, dict[str, Any]] = {}
    canonical_reply_ids: set[str] = set()
    for message in authoritative:
        reply_to = str(message.get("reply_to") or "")
        if message.get("role") != "assistant" or not reply_to:
            continue
        canonical_reply_ids.add(str(message["id"]))
        previous = latest.get(reply_to)
        if previous is None or int(message.get("run_sequence") or 0) > int(previous.get("run_sequence") or 0):
            latest[reply_to] = message
    if latest:
        result = [message for message in result if str(message.get("id") or "") not in canonical_reply_ids]
        ordered: list[dict[str, Any]] = []
        for message in result:
            ordered.append(message)
            if message.get("role") == "user" and str(message.get("id") or "") in latest:
                ordered.append(dict(latest.pop(str(message["id"]))))
        ordered.extend(dict(message) for message in latest.values())
        result = ordered
    return result


def _canonical_messages(conn: Any, owner: str, sid: str) -> list[dict[str, Any]]:
    rows = conn.execute(text("SELECT payload FROM conversation_messages "
                             "WHERE user_id=:owner AND session_id=:sid ORDER BY created_at,message_id"),
                        {"owner": owner, "sid": sid}).scalars().all()
    return [json.loads(row) if isinstance(row, str) else dict(row) for row in rows]


def _write_thread(
    conn: Any, owner: str, sid: str, current: dict[str, Any],
    messages: list[dict[str, Any]], changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = changes or {}
    title = str(data.get("title") or current.get("title") or "").strip()[:80]
    if not title or title == "新对话":
        title = _derive_title(messages)
    row = conn.execute(text(
        "UPDATE conversation_threads SET title=:title,messages=CAST(:messages AS jsonb),"
        "message_count=:count,last_message_preview=:preview,pinned=:pinned,archived=:archived,"
        f"version=version+1,updated_at=now() WHERE user_id=:owner AND session_id=:sid RETURNING {_THREAD_COLUMNS}"
    ), {
        "owner": owner, "sid": sid, "title": title,
        "messages": json.dumps(messages, ensure_ascii=False), "count": len(messages),
        "preview": _derive_preview(messages), "pinned": bool(data.get("pinned", current.get("pinned", False))),
        "archived": bool(data.get("archived", current.get("archived", False))),
    }).mappings().one()
    return _conversation_row(row)


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
                    f"SELECT {_THREAD_COLUMNS} FROM conversation_threads "
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
                text(f"SELECT {_THREAD_COLUMNS} FROM conversation_threads WHERE {where} ORDER BY updated_at DESC"),
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
        with self._engine.begin() as conn:
            _configure_owner(conn, owner)
            current = _locked_thread(conn, owner, sid)
            expected = data.get("expected_version")
            if expected is not None and (not isinstance(expected, int) or expected != current["version"]):
                raise ConversationVersionConflict("conversation version changed")
            messages = _merge_messages(
                current["messages"], _sanitize_messages(data.get("messages")), _canonical_messages(conn, owner, sid),
            )
            return _write_thread(conn, owner, sid, current, messages, data)

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
        allowed = {key: value for key, value in dict(payload or {}).items() if key in {"title", "messages", "pinned", "archived", "expected_version"}}
        return self.upsert(sid, allowed, owner)

    def delete(self, session_id: str, user_id: str = "public") -> bool:
        sid = str(session_id or "").strip()
        if not sid:
            return False
        owner = _authenticated_user_id(user_id)
        with self._engine.begin() as conn:
            _configure_owner(conn, owner)
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
    "ConversationVersionConflict",
    "PostgresConversationStore",
    "get_conversation_store",
    "reset_conversation_store_cache",
]
