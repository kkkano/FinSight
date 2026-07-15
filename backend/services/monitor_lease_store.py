# -*- coding: utf-8 -*-
"""页面高频监控 lease 的 PostgreSQL-only 租户存储。"""
from __future__ import annotations

import hashlib
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import text

from backend.services.database import create_core_engine, resolve_core_postgres_dsn


class MonitorLeaseStoreUnavailable(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


class UnavailableMonitorLeaseStore:
    def __getattr__(self, _name: str):
        def unavailable(*_args, **_kwargs):
            raise MonitorLeaseStoreUnavailable("monitor lease postgres unavailable")
        return unavailable


class MonitorLeaseStore:
    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        if engine is None:
            engine = create_core_engine(dsn=dsn)
        self._engine = engine

    def acquire(
        self,
        *,
        user_id: str,
        session_id: str,
        symbol: str,
        ttl_seconds: int = 90,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        issued_at = now or _utc_now()
        lease_id = str(uuid4())
        token = secrets.token_urlsafe(32)
        expires_at = issued_at + timedelta(seconds=max(30, min(int(ttl_seconds), 300)))
        params = {
            "id": lease_id,
            "user_id": str(user_id),
            "session_id": str(session_id),
            "symbol": str(symbol).strip().upper(),
            "lease_token_hash": _token_hash(token),
            "expires_at": expires_at,
            "updated_at": issued_at,
        }
        with self._engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO monitor_page_leases "
                "(id, user_id, session_id, symbol, lease_token_hash, expires_at, updated_at) "
                "VALUES (CAST(:id AS uuid), :user_id, :session_id, :symbol, :lease_token_hash, :expires_at, :updated_at)"
            ), params)
        return {
            "id": lease_id,
            "session_id": params["session_id"],
            "symbol": params["symbol"],
            "lease_token": token,
            "expires_at": expires_at,
        }

    def renew(
        self,
        lease_id: str,
        *,
        user_id: str,
        lease_token: str,
        ttl_seconds: int = 90,
        now: datetime | None = None,
    ) -> datetime | None:
        renewed_at = now or _utc_now()
        expires_at = renewed_at + timedelta(seconds=max(30, min(int(ttl_seconds), 300)))
        with self._engine.begin() as conn:
            result = conn.execute(text(
                "UPDATE monitor_page_leases SET expires_at = :expires_at, updated_at = :updated_at "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id "
                "AND lease_token_hash = :lease_token_hash AND expires_at > :updated_at"
            ), {
                "id": str(lease_id), "user_id": str(user_id),
                "lease_token_hash": _token_hash(lease_token),
                "expires_at": expires_at, "updated_at": renewed_at,
            })
        return expires_at if int(result.rowcount or 0) == 1 else None

    def release(self, lease_id: str, *, user_id: str, lease_token: str) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(text(
                "DELETE FROM monitor_page_leases WHERE id = CAST(:id AS uuid) "
                "AND user_id = :user_id AND lease_token_hash = :lease_token_hash"
            ), {
                "id": str(lease_id), "user_id": str(user_id),
                "lease_token_hash": _token_hash(lease_token),
            })
        return int(result.rowcount or 0) == 1

    def list_active(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id::text AS id, user_id, session_id, symbol, expires_at, updated_at "
                "FROM monitor_page_leases WHERE expires_at > :now ORDER BY user_id, session_id, symbol, id"
            ), {"now": now or _utc_now()}).mappings().all()
        return [dict(row) for row in rows]

    def cleanup_expired(self, *, now: datetime | None = None) -> int:
        with self._engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM monitor_page_leases WHERE expires_at <= :now"),
                {"now": now or _utc_now()},
            )
        return int(result.rowcount or 0)

    @contextmanager
    def realtime_tick_lock(self, lock_id: int = 913_240_17) -> Iterator[bool]:
        """用同一 PostgreSQL 连接持有 session advisory lock，退出时释放。"""
        with self._engine.connect() as conn:
            acquired = bool(conn.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": int(lock_id)}
            ).scalar())
            try:
                yield acquired
            finally:
                if acquired:
                    conn.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": int(lock_id)})


def _resolve_dsn() -> str:
    return resolve_core_postgres_dsn(required=False)


_store: MonitorLeaseStore | UnavailableMonitorLeaseStore | None = None
_lock = threading.Lock()


def get_monitor_lease_store() -> MonitorLeaseStore | UnavailableMonitorLeaseStore:
    global _store
    if _store is not None:
        return _store
    with _lock:
        if _store is None:
            try:
                dsn = _resolve_dsn()
                _store = MonitorLeaseStore(dsn=dsn) if dsn else UnavailableMonitorLeaseStore()
            except Exception:
                _store = UnavailableMonitorLeaseStore()
    return _store


def reset_monitor_lease_store_cache() -> None:
    global _store
    with _lock:
        _store = None


__all__ = [
    "MonitorLeaseStore", "MonitorLeaseStoreUnavailable", "UnavailableMonitorLeaseStore",
    "get_monitor_lease_store", "reset_monitor_lease_store_cache",
]
