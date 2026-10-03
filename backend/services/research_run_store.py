"""研究运行与权威消息的事务存储；外部研究调用不占用数据库事务。"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from threading import Lock
from typing import Any

from sqlalchemy import text

from backend.services.conversation_store import (
    _authenticated_user_id,
    _canonical_messages,
    _configure_owner,
    _epoch,
    _locked_thread,
    _merge_messages,
    _write_thread,
)
from backend.services.database import create_core_engine, is_production_mode, resolve_core_postgres_dsn


WORKER_ID = uuid.uuid4().hex
LEASE_SECONDS = 90
HEARTBEAT_SECONDS = 25
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "interrupted", "persistence_failed"})
_STORE_LOCK = Lock()
_STORE: PostgresResearchRunStore | None = None
_RUN_COLUMNS = (
    "sequence,user_id,run_id,session_id,query,request_fingerprint,user_message_id,assistant_message_id,"
    "status,worker_id,lease_expires_at,final_payload,created_at,updated_at,completed_at"
)


class ResearchRunConflict(ValueError):
    """同一运行或消息身份被用于不同请求。"""


def request_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def public_run(row: dict[str, Any]) -> dict[str, Any]:
    """恢复接口白名单，不返回工作进程、请求上下文或凭据。"""
    return {
        **{key: row[key] for key in ("run_id", "session_id", "status", "user_message_id", "assistant_message_id")},
        **{key: _epoch(row.get(key)) for key in ("created_at", "updated_at", "completed_at")},
        "result": _json(row.get("final_payload")),
    }


def terminal_status(event: dict[str, Any]) -> str:
    if event.get("run_status") in TERMINAL_STATUSES:
        return str(event["run_status"])
    if event.get("type") == "cancelled":
        return "cancelled"
    if event.get("type") == "error" or event.get("failure_kind") == "execution_error":
        return "failed"
    if event.get("failure_kind") == "persistence_error":
        return "persistence_failed"
    return "completed"


class PostgresResearchRunStore:
    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        self._engine = engine if engine is not None else create_core_engine(
            dsn=dsn, pool_size=3, max_overflow=2, pool_timeout=5, connect_args={"connect_timeout": 5},
        )

    @contextmanager
    def _transaction(self, user_id: str):
        owner = _authenticated_user_id(user_id)
        with self._engine.begin() as conn:
            _configure_owner(conn, owner)
            yield conn, owner

    def _get(self, conn: Any, owner: str, run_id: str, *, lock: bool = False) -> dict[str, Any] | None:
        row = conn.execute(text(
            f"SELECT {_RUN_COLUMNS},lease_expires_at<=now() AS lease_expired FROM research_runs "
            "WHERE user_id=:owner AND run_id=:run_id" + (" FOR UPDATE" if lock else "")
        ), {"owner": owner, "run_id": run_id}).mappings().first()
        return dict(row) if row else None

    def get(self, run_id: str, *, user_id: str, recover_expired: bool = True) -> dict[str, Any] | None:
        with self._transaction(user_id) as (conn, owner):
            row = self._get(conn, owner, run_id)
            if row and recover_expired and row["status"] == "running" and row["lease_expired"]:
                # 所有多表写入均先锁会话再锁运行，避免与完成事务互相死锁。
                current = _locked_thread(conn, owner, row["session_id"], create=False)
                row = self._get(conn, owner, run_id, lock=True)
                if current and row and row["status"] == "running" and row["lease_expired"]:
                    self._finish_locked(conn, owner, row, current, {
                        "type": "error", "code": "run_interrupted", "run_status": "interrupted",
                        "message": "生成进程已中断，已保留本次提问。请主动重新生成；恢复不会自动重复调用模型。",
                        "publishable": False, "failure_kind": "execution_error",
                    })
                    row = self._get(conn, owner, run_id)
            return row

    def begin(
        self, *, user_id: str, run_id: str, session_id: str, query: str, fingerprint: str,
        user_message_id: str | None = None, assistant_message_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if len(session_id.split(":")) != 3 or session_id.split(":")[1] != user_id:
            raise ResearchRunConflict("session owner mismatch")
        user_message_id = user_message_id or uuid.uuid4().hex
        assistant_message_id = assistant_message_id or uuid.uuid4().hex
        if user_message_id == assistant_message_id:
            raise ResearchRunConflict("user and assistant message IDs must differ")
        with self._transaction(user_id) as (conn, owner):
            current = _locked_thread(conn, owner, session_id)
            row = self._get(conn, owner, run_id, lock=True)
            if row:
                if row["session_id"] != session_id or row["request_fingerprint"] != fingerprint:
                    raise ResearchRunConflict("run_id belongs to another request")
                return row, False
            inserted = conn.execute(text(
                "INSERT INTO research_runs (user_id,run_id,session_id,query,request_fingerprint,"
                "user_message_id,assistant_message_id,worker_id,lease_expires_at) VALUES "
                "(:owner,:run_id,:sid,:query,:fingerprint,:user_message_id,:assistant_message_id,:worker_id,"
                "now()+make_interval(secs=>:lease)) ON CONFLICT DO NOTHING RETURNING " + _RUN_COLUMNS
            ), {"owner": owner, "run_id": run_id, "sid": session_id, "query": query, "fingerprint": fingerprint,
                "user_message_id": user_message_id, "assistant_message_id": assistant_message_id,
                "worker_id": WORKER_ID, "lease": LEASE_SECONDS}).mappings().first()
            if not inserted:
                row = self._get(conn, owner, run_id)
                if row and row["session_id"] == session_id and row["request_fingerprint"] == fingerprint:
                    return row, False
                raise ResearchRunConflict("run or assistant message ID already exists")
            row = dict(inserted)
            message = {"id": user_message_id, "role": "user", "content": query,
                       "timestamp": _epoch(row["created_at"]) * 1000, "run_id": run_id}
            self._insert_message(conn, owner, row, message)
            self._insert_message(conn, owner, row, {
                "id": assistant_message_id, "role": "assistant", "content": "正在生成回答…",
                "timestamp": _epoch(row["created_at"]) * 1000 + 1, "run_id": run_id,
                "reply_to": user_message_id, "run_sequence": row["sequence"],
                "run_status": "running", "answer_status": "running", "isLoading": True, "publishable": False,
            })
            messages = _merge_messages(current["messages"], [], _canonical_messages(conn, owner, session_id))
            _write_thread(conn, owner, session_id, current, messages)
            return row, True

    def _insert_message(
        self, conn: Any, owner: str, row: dict[str, Any], message: dict[str, Any], *, finalize: bool = False,
    ) -> None:
        on_conflict = "ON CONFLICT (user_id,session_id,message_id) DO NOTHING"
        if finalize:
            on_conflict = (
                "ON CONFLICT (user_id,session_id,message_id) DO UPDATE SET payload=excluded.payload "
                "WHERE conversation_messages.run_id=excluded.run_id AND conversation_messages.role='assistant' "
                "AND conversation_messages.payload->>'isLoading'='true'"
            )
        conn.execute(text(
            "INSERT INTO conversation_messages (user_id,session_id,message_id,run_id,role,payload) "
            "VALUES (:owner,:sid,:message_id,:run_id,:role,CAST(:payload AS jsonb)) " + on_conflict
        ), {"owner": owner, "sid": row["session_id"], "message_id": message["id"], "run_id": row["run_id"],
            "role": message["role"], "payload": json.dumps(message, ensure_ascii=False, default=str)})
        existing = conn.execute(text(
            "SELECT payload FROM conversation_messages WHERE user_id=:owner AND session_id=:sid AND message_id=:message_id"
        ), {"owner": owner, "sid": row["session_id"], "message_id": message["id"]}).scalar_one()
        existing = _json(existing)
        if existing.get("role") != message["role"] or existing.get("content") != message["content"]:
            raise ResearchRunConflict("message ID belongs to different content")

    def heartbeat(self, run_id: str, *, user_id: str) -> bool:
        with self._transaction(user_id) as (conn, owner):
            result = conn.execute(text(
                "UPDATE research_runs SET lease_expires_at=now()+make_interval(secs=>:lease),updated_at=now() "
                "WHERE user_id=:owner AND run_id=:run_id AND worker_id=:worker_id AND status='running'"
            ), {"owner": owner, "run_id": run_id, "worker_id": WORKER_ID, "lease": LEASE_SECONDS})
            return bool(result.rowcount)

    def finish(self, run_id: str, event: dict[str, Any], *, user_id: str) -> dict[str, Any]:
        with self._transaction(user_id) as (conn, owner):
            row = self._get(conn, owner, run_id)
            if row is None:
                raise ResearchRunConflict("run does not exist")
            current = _locked_thread(conn, owner, row["session_id"], create=False)
            row = self._get(conn, owner, run_id, lock=True)
            if current is None or row is None:
                raise ResearchRunConflict("conversation was deleted")
            if row["status"] != "running":
                return dict(_json(row["final_payload"]))
            if row["worker_id"] != WORKER_ID:
                raise ResearchRunConflict("run belongs to another worker")
            return self._finish_locked(conn, owner, row, current, event)

    def _finish_locked(
        self, conn: Any, owner: str, row: dict[str, Any], current: dict[str, Any], event: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(event)
        status = terminal_status(payload)
        content = str(payload.get("response") or payload.get("message") or "").strip()
        if not content:
            content = "本次生成已停止，请重新生成。" if status == "cancelled" else "本轮未返回可用回答，请重新生成。"
        failed = status in {"failed", "cancelled", "interrupted", "persistence_failed"}
        message = {
            "id": row["assistant_message_id"], "role": "assistant", "content": content,
            "timestamp": time.time() * 1000, "run_id": row["run_id"], "reply_to": row["user_message_id"],
            "run_sequence": row["sequence"], "run_status": status,
            "persistence_status": "saved",
            "answer_status": payload.get("answer_status", "unavailable" if failed else "answered"),
            "quality": payload.get("quality"), "publishable": bool(payload.get("publishable", not failed)),
            "isLoading": False, "canRetry": failed or bool(payload.get("quality_blocked")),
        }
        if failed:
            message["error"] = str(payload.get("message") or payload.get("error_code") or "本次生成未完成，可重试。")
        report = payload.get("report") or payload.get("blocked_report")
        if isinstance(report, dict):
            message["report"] = report
        self._insert_message(conn, owner, row, message, finalize=True)
        messages = _merge_messages(current["messages"], [], _canonical_messages(conn, owner, row["session_id"]))
        thread = _write_thread(conn, owner, row["session_id"], current, messages)
        payload.update({
            "run_id": row["run_id"], "session_id": row["session_id"], "run_status": status,
            "user_message_id": row["user_message_id"], "assistant_message_id": row["assistant_message_id"],
            "assistant_message": message, "conversation_version": thread["version"], "persistence_status": "saved",
        })
        conn.execute(text(
            "UPDATE research_runs SET status=:status,final_payload=CAST(:payload AS jsonb),"
            "completed_at=now(),updated_at=now() WHERE user_id=:owner AND run_id=:run_id AND status='running'"
        ), {"owner": owner, "run_id": row["run_id"], "status": status,
            "payload": json.dumps(payload, ensure_ascii=False, default=str)})
        return payload


def get_research_run_store() -> PostgresResearchRunStore | None:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            dsn = resolve_core_postgres_dsn(required=is_production_mode())
            if not dsn:
                return None  # 无外部配置的本地测试；生产启动时已要求 PostgreSQL。
            _STORE = PostgresResearchRunStore(dsn=dsn)
        return _STORE


def reset_research_run_store_cache() -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = None
