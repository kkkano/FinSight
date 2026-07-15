# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy import text

from backend.services.database import create_core_engine, resolve_core_postgres_dsn


_STORE_LOCK = Lock()
_STORE_SINGLETON: "PostgresConversationStore | UnavailableConversationStore | None" = None


def _now() -> float:
    return time.time()


def _data_dir() -> Path:
    """解析数据目录：优先 FINSIGHT_DATA_DIR，否则锚定到仓库根 /data。

    避免相对 Path("data") 受进程 CWD 影响导致的 split-brain
    （与 portfolio_store/monitor_store/cost_audit_store 同一锚定模式）。
    conversation_store.py 位于 backend/services/，parents[2] 即仓库根。
    """
    env_dir = os.getenv("FINSIGHT_DATA_DIR")
    if env_dir and env_dir.strip():
        return Path(env_dir.strip())
    return Path(__file__).resolve().parents[2] / "data"


def _store_path() -> Path:
    configured = os.getenv("CONVERSATION_STORE_PATH")
    if configured and configured.strip():
        return Path(configured.strip())
    return _data_dir() / "conversations.json"


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


def _normalize_user_id(user_id: str) -> str:
    return str(user_id or "public").strip() or "public"


def _record_key(session_id: str, user_id: str) -> str:
    normalized_user = _normalize_user_id(user_id)
    if normalized_user == "public":
        return session_id
    return f"{normalized_user}\x1f{session_id}"


def _external_record(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    result.pop("user_id", None)
    return result


class LegacyConversationStore:
    """仅供一次性迁移读取/回滚验证的旧 JSON 会话存储。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _store_path()
        self._lock = Lock()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        rows = payload.get("conversations")
        if not isinstance(rows, dict):
            return {}
        records: dict[str, dict[str, Any]] = {}
        for key, value in rows.items():
            if not isinstance(value, dict):
                continue
            record = dict(value)
            record["user_id"] = _normalize_user_id(str(record.get("user_id") or "public"))
            records[str(key)] = record
        return records

    def _save(self, records: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"conversations": records}, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def get(self, session_id: str, user_id: str = "public") -> dict[str, Any] | None:
        sid = str(session_id or "").strip()
        if not sid:
            return None
        with self._lock:
            record = self._load().get(_record_key(sid, user_id))
        return _external_record(record) if isinstance(record, dict) else None

    def list(
        self,
        *,
        include_archived: bool = False,
        user_id: str = "public",
    ) -> list[dict[str, Any]]:
        normalized_user = _normalize_user_id(user_id)
        with self._lock:
            records = list(self._load().values())
        rows = [
            _external_record(item)
            for item in records
            if item.get("user_id", "public") == normalized_user
            and (include_archived or not bool(item.get("archived")))
        ]
        return sorted(rows, key=lambda item: float(item.get("updated_at") or 0), reverse=True)

    def upsert(
        self,
        session_id: str,
        payload: dict[str, Any] | None = None,
        user_id: str = "public",
    ) -> dict[str, Any]:
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id required")
        data = payload if isinstance(payload, dict) else {}
        normalized_user = _normalize_user_id(user_id)
        key = _record_key(sid, normalized_user)
        now = _now()
        with self._lock:
            records = self._load()
            current = dict(records.get(key) or {})
            messages = (
                _sanitize_messages(data.get("messages"))
                if "messages" in data
                else list(current.get("messages") if isinstance(current.get("messages"), list) else [])
            )
            title_raw = data.get("title")
            title = str(title_raw or current.get("title") or "").strip()[:80]
            if not title:
                title = _derive_title(messages)
            record = {
                "user_id": normalized_user,
                "session_id": sid,
                "title": title,
                "messages": messages,
                "message_count": len(messages),
                "last_message_preview": _derive_preview(messages),
                "pinned": bool(data.get("pinned", current.get("pinned", False))),
                "archived": bool(data.get("archived", current.get("archived", False))),
                "created_at": float(current.get("created_at") or now),
                "updated_at": now,
            }
            records[key] = record
            self._save(records)
        return _external_record(record)

    def patch(
        self,
        session_id: str,
        payload: dict[str, Any],
        user_id: str = "public",
    ) -> dict[str, Any]:
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id required")
        data = payload if isinstance(payload, dict) else {}
        normalized_user = _normalize_user_id(user_id)
        key = _record_key(sid, normalized_user)
        with self._lock:
            records = self._load()
            current = dict(
                records.get(key)
                or {
                    "user_id": normalized_user,
                    "session_id": sid,
                    "created_at": _now(),
                    "messages": [],
                }
            )
            if "title" in data:
                title = str(data.get("title") or "").strip()
                if title:
                    current["title"] = title[:80]
            if "pinned" in data:
                current["pinned"] = bool(data.get("pinned"))
            if "archived" in data:
                current["archived"] = bool(data.get("archived"))
            if "messages" in data:
                current["messages"] = _sanitize_messages(data.get("messages"))
            messages = current.get("messages") if isinstance(current.get("messages"), list) else []
            if not str(current.get("title") or "").strip():
                current["title"] = _derive_title(messages)
            current["message_count"] = len(messages)
            current["last_message_preview"] = _derive_preview(messages)
            current["updated_at"] = _now()
            current["user_id"] = normalized_user
            records[key] = current
            self._save(records)
        return _external_record(current)

    def delete(self, session_id: str, user_id: str = "public") -> bool:
        sid = str(session_id or "").strip()
        if not sid:
            return False
        key = _record_key(sid, user_id)
        with self._lock:
            records = self._load()
            existed = key in records
            if existed:
                records.pop(key, None)
                self._save(records)
        return existed


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
    "LegacyConversationStore",
    "PostgresConversationStore",
    "get_conversation_store",
    "reset_conversation_store_cache",
]
