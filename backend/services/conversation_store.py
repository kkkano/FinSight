# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any


_STORE_LOCK = Lock()
_STORE_SINGLETON: "ConversationStore | None" = None


def _now() -> float:
    return time.time()


def _store_path() -> Path:
    configured = os.getenv("CONVERSATION_STORE_PATH")
    if configured and configured.strip():
        return Path(configured.strip())
    return Path("data") / "conversations.json"


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


class ConversationStore:
    """轻量会话快照存储，负责服务端消息、标题和列表元数据。"""

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
        return {str(k): v for k, v in rows.items() if isinstance(v, dict)}

    def _save(self, records: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"conversations": records}, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def get(self, session_id: str) -> dict[str, Any] | None:
        sid = str(session_id or "").strip()
        if not sid:
            return None
        with self._lock:
            record = self._load().get(sid)
        return dict(record) if isinstance(record, dict) else None

    def list(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._load().values())
        rows = [
            dict(item)
            for item in records
            if include_archived or not bool(item.get("archived"))
        ]
        return sorted(rows, key=lambda item: float(item.get("updated_at") or 0), reverse=True)

    def upsert(self, session_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id required")
        data = payload if isinstance(payload, dict) else {}
        now = _now()
        with self._lock:
            records = self._load()
            current = dict(records.get(sid) or {})
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
            records[sid] = record
            self._save(records)
        return dict(record)

    def patch(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id required")
        data = payload if isinstance(payload, dict) else {}
        with self._lock:
            records = self._load()
            current = dict(records.get(sid) or {"session_id": sid, "created_at": _now(), "messages": []})
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
            records[sid] = current
            self._save(records)
        return dict(current)

    def delete(self, session_id: str) -> bool:
        sid = str(session_id or "").strip()
        if not sid:
            return False
        with self._lock:
            records = self._load()
            existed = sid in records
            if existed:
                records.pop(sid, None)
                self._save(records)
        return existed


def get_conversation_store() -> ConversationStore:
    global _STORE_SINGLETON
    with _STORE_LOCK:
        if _STORE_SINGLETON is None:
            _STORE_SINGLETON = ConversationStore()
        return _STORE_SINGLETON


__all__ = ["ConversationStore", "get_conversation_store"]
