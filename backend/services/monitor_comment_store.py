# -*- coding: utf-8 -*-
"""实时点评的 PostgreSQL-only 租户存储与游标合同。"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, text

from backend.services.agent_prediction_store import get_agent_prediction_store


class MonitorCommentStoreUnavailable(RuntimeError):
    pass


class MonitorComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    symbol: str
    ts: datetime
    level: str = Field(pattern="^(info|warn|alert|error)$")
    text: str = Field(min_length=1, max_length=500)
    trigger: dict[str, str]
    source: str = Field(pattern="^(agent|system)$")
    escalated: bool = False
    prediction_id: str | None = None


def trigger_fingerprint(*, symbol: str, trigger_kind: str, trigger_detail: str, observed_at: str) -> str:
    raw = "\n".join((symbol.upper(), trigger_kind, trigger_detail, observed_at))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _encode_cursor(ts: datetime, item_id: str) -> str:
    raw = json.dumps({"ts": ts.isoformat(), "id": item_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        return datetime.fromisoformat(payload["ts"]), str(payload["id"])
    except Exception as exc:
        raise ValueError("invalid comment cursor") from exc


class UnavailableMonitorCommentStore:
    def __getattr__(self, _name: str):
        def unavailable(*_args, **_kwargs):
            raise MonitorCommentStoreUnavailable("monitor comments postgres unavailable")
        return unavailable


class MonitorCommentStore:
    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        if engine is None:
            normalized = str(dsn or "").strip()
            if not normalized.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("monitor comment store 只允许 PostgreSQL DSN")
            engine = create_engine(normalized, future=True, pool_pre_ping=True)
        self._engine = engine
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def ensure_schema(self) -> bool:
        if self._schema_ready:
            return True
        with self._schema_lock:
            if self._schema_ready:
                return True
            prediction_store = get_agent_prediction_store()
            if hasattr(prediction_store, "ensure_schema") and not prediction_store.ensure_schema():
                raise MonitorCommentStoreUnavailable("agent_predictions schema unavailable")
            with self._engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS monitor_comments ("
                    "id UUID NOT NULL PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT NOT NULL, "
                    "symbol TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL, level TEXT NOT NULL, text TEXT NOT NULL, "
                    "trigger_kind TEXT NOT NULL, trigger_detail TEXT NOT NULL, trigger_observed_at TEXT NOT NULL, "
                    "trigger_fingerprint TEXT NOT NULL, source TEXT NOT NULL, escalated BOOLEAN NOT NULL, "
                    "prediction_id UUID NULL, UNIQUE(user_id, session_id, trigger_fingerprint), "
                    "FOREIGN KEY(prediction_id, user_id) REFERENCES agent_predictions(id, user_id))"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_monitor_comments_tenant_time "
                    "ON monitor_comments(user_id, session_id, ts DESC, id DESC)"
                ))
            self._schema_ready = True
        return True

    def create(self, *, user_id: str, session_id: str, symbol: str, ts: datetime,
               level: str, text_value: str, trigger_kind: str, trigger_detail: str,
               trigger_observed_at: str, source: str, escalated: bool,
               prediction_id: str | None = None) -> MonitorComment | None:
        self.ensure_schema()
        item_id = str(uuid4())
        fingerprint = trigger_fingerprint(
            symbol=symbol, trigger_kind=trigger_kind,
            trigger_detail=trigger_detail, observed_at=trigger_observed_at,
        )
        params = {
            "id": item_id, "user_id": user_id, "session_id": session_id,
            "symbol": symbol.upper(), "ts": ts, "level": level, "text": text_value,
            "trigger_kind": trigger_kind, "trigger_detail": trigger_detail,
            "trigger_observed_at": trigger_observed_at, "trigger_fingerprint": fingerprint,
            "source": source, "escalated": bool(escalated), "prediction_id": prediction_id,
        }
        with self._engine.begin() as conn:
            result = conn.execute(text(
                "INSERT INTO monitor_comments (id,user_id,session_id,symbol,ts,level,text,trigger_kind,"
                "trigger_detail,trigger_observed_at,trigger_fingerprint,source,escalated,prediction_id) "
                "VALUES (CAST(:id AS uuid),:user_id,:session_id,:symbol,:ts,:level,:text,:trigger_kind,"
                ":trigger_detail,:trigger_observed_at,:trigger_fingerprint,:source,:escalated,"
                "CAST(:prediction_id AS uuid)) ON CONFLICT (user_id,session_id,trigger_fingerprint) DO NOTHING"
            ), params)
        if int(result.rowcount or 0) != 1:
            return None
        return MonitorComment(
            id=item_id, session_id=session_id, symbol=symbol.upper(), ts=ts,
            level=level, text=text_value,
            trigger={"kind": trigger_kind, "detail": trigger_detail, "observed_at": trigger_observed_at},
            source=source, escalated=escalated, prediction_id=prediction_id,
        )

    def list(self, *, user_id: str, session_id: str, day: date | None = None,
             cursor: str | None = None, limit: int = 50) -> tuple[list[MonitorComment], str | None]:
        self.ensure_schema()
        page_size = max(1, min(int(limit), 100))
        params: dict[str, Any] = {"user_id": user_id, "session_id": session_id, "limit": page_size + 1}
        where = ["user_id=:user_id", "session_id=:session_id"]
        if day is not None:
            start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            params.update({"start": start, "end": start + timedelta(days=1)})
            where += ["ts >= :start", "ts < :end"]
        decoded = _decode_cursor(cursor)
        if decoded:
            params.update({"cursor_ts": decoded[0], "cursor_id": decoded[1]})
            where.append("(ts, id) < (:cursor_ts, CAST(:cursor_id AS uuid))")
        sql = "SELECT * FROM monitor_comments WHERE " + " AND ".join(where) + " ORDER BY ts DESC,id DESC LIMIT :limit"
        with self._engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        items = [self._row(row) for row in rows[:page_size]]
        next_cursor = _encode_cursor(items[-1].ts, items[-1].id) if len(rows) > page_size and items else None
        return items, next_cursor

    def list_after(self, *, user_id: str, session_id: str, last_event_id: str, limit: int = 100) -> list[MonitorComment]:
        self.ensure_schema()
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT c.* FROM monitor_comments c JOIN monitor_comments anchor "
                "ON anchor.id=CAST(:last_id AS uuid) AND anchor.user_id=:user_id AND anchor.session_id=:session_id "
                "WHERE c.user_id=:user_id AND c.session_id=:session_id AND (c.ts,c.id)>(anchor.ts,anchor.id) "
                "ORDER BY c.ts,c.id LIMIT :limit"
            ), {"last_id": last_event_id, "user_id": user_id, "session_id": session_id,
                "limit": max(1, min(int(limit), 200))}).mappings().all()
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row: Any) -> MonitorComment:
        data = dict(row)
        return MonitorComment(
            id=str(data["id"]), session_id=data["session_id"], symbol=data["symbol"], ts=data["ts"],
            level=data["level"], text=data["text"],
            trigger={"kind": data["trigger_kind"], "detail": data["trigger_detail"],
                     "observed_at": data["trigger_observed_at"]},
            source=data["source"], escalated=bool(data["escalated"]),
            prediction_id=str(data["prediction_id"]) if data.get("prediction_id") else None,
        )


def _resolve_dsn() -> str:
    return (os.getenv("MONITOR_COMMENT_POSTGRES_DSN") or os.getenv("AGENT_PREDICTION_POSTGRES_DSN")
            or os.getenv("RAG_V2_POSTGRES_DSN") or os.getenv("LANGGRAPH_CHECKPOINT_POSTGRES_DSN") or "").strip()


_store: MonitorCommentStore | UnavailableMonitorCommentStore | None = None
_lock = threading.Lock()


def get_monitor_comment_store():
    global _store
    if _store is not None:
        return _store
    with _lock:
        if _store is None:
            try:
                dsn = _resolve_dsn()
                _store = MonitorCommentStore(dsn=dsn) if dsn else UnavailableMonitorCommentStore()
            except Exception:
                _store = UnavailableMonitorCommentStore()
    return _store


def reset_monitor_comment_store_cache() -> None:
    global _store
    with _lock:
        _store = None


__all__ = ["MonitorComment", "MonitorCommentStore", "get_monitor_comment_store",
           "reset_monitor_comment_store_cache", "trigger_fingerprint"]
