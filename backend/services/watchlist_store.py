# -*- coding: utf-8 -*-
"""用户自选股 SQLite 存储。"""
from __future__ import annotations

import os
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from backend.config.ticker_mapping import normalize_ticker
from backend.services.database import create_core_engine, resolve_core_postgres_dsn

logger = logging.getLogger(__name__)
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DB_PATH = Path(os.getenv("FINSIGHT_DATA_DIR") or _DEFAULT_DATA_DIR) / "watchlist.db"


class LegacyWatchlistStore:
    """仅供一次性迁移读取/回滚验证的旧 SQLite 自选存储。"""

    def __init__(self, db_path: str | Path = _DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                user_id TEXT NOT NULL DEFAULT 'public',
                ticker TEXT NOT NULL,
                note TEXT DEFAULT '',
                added_at TEXT NOT NULL,
                PRIMARY KEY(user_id, ticker)
            );
            CREATE INDEX IF NOT EXISTS idx_watchlist_user_added
                ON watchlist(user_id, added_at);
            """
        )
        self._conn.commit()

    @staticmethod
    def _ticker(value: str) -> str:
        ticker = normalize_ticker(str(value or "").strip())
        if not ticker:
            raise ValueError("ticker is required")
        return ticker

    def list_items(self, user_id: str = "public") -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT ticker, note, added_at FROM watchlist WHERE user_id = ? ORDER BY added_at, ticker",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_item(
        self,
        ticker: str,
        note: str = "",
        user_id: str = "public",
    ) -> tuple[dict[str, Any], bool]:
        normalized = self._ticker(ticker)
        existing = self._conn.execute(
            "SELECT ticker, note, added_at FROM watchlist WHERE user_id = ? AND ticker = ?",
            (user_id, normalized),
        ).fetchone()
        if existing is not None:
            return dict(existing), False

        added_at = datetime.now(timezone.utc).isoformat()
        clean_note = str(note or "").strip()
        self._conn.execute(
            "INSERT INTO watchlist (user_id, ticker, note, added_at) VALUES (?, ?, ?, ?)",
            (user_id, normalized, clean_note, added_at),
        )
        self._conn.commit()
        return {
            "ticker": normalized,
            "note": clean_note,
            "added_at": added_at,
        }, True

    def remove_item(self, ticker: str, user_id: str = "public") -> bool:
        normalized = self._ticker(ticker)
        cursor = self._conn.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
            (user_id, normalized),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        self._conn.close()

    def migrate_legacy_profiles(self, memory_dir: str | Path) -> int:
        """把旧 ``data/memory/*.json`` 中的 watchlist 幂等迁入 SQLite。"""
        root = Path(memory_dir)
        if not root.exists():
            return 0
        migrated = 0
        for path in root.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                user_id = str(payload.get("user_id") or path.stem).strip()
                for ticker in payload.get("watchlist") or []:
                    _item, created = self.add_item(str(ticker), user_id=user_id)
                    migrated += int(created)
            except Exception as exc:
                logger.warning("旧自选股迁移失败 path=%s: %s", path, exc)
        return migrated


class WatchlistStoreUnavailable(RuntimeError):
    pass


class UnavailableWatchlistStore:
    def __getattr__(self, _name: str):
        def unavailable(*_args, **_kwargs):
            raise WatchlistStoreUnavailable("watchlist postgres unavailable")

        return unavailable


class WatchlistStore:
    """按 ``user_id`` 隔离的 PostgreSQL 自选存储。"""

    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        self._engine = engine if engine is not None else create_core_engine(dsn=dsn)

    @staticmethod
    def _ticker(value: str) -> str:
        ticker = normalize_ticker(str(value or "").strip())
        if not ticker:
            raise ValueError("ticker is required")
        return ticker

    @staticmethod
    def _owner(user_id: str) -> str:
        owner = str(user_id or "").strip()
        if not owner or owner == "public":
            raise WatchlistStoreUnavailable("watchlist requires authenticated user")
        return owner

    def list_items(self, user_id: str = "public") -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT ticker,note,added_at FROM watchlist_items "
                    "WHERE user_id=:user_id ORDER BY added_at,ticker"
                ),
                {"user_id": self._owner(user_id)},
            ).mappings().all()
        return [
            {
                "ticker": row["ticker"],
                "note": row["note"],
                "added_at": row["added_at"].isoformat() if hasattr(row["added_at"], "isoformat") else str(row["added_at"]),
            }
            for row in rows
        ]

    def add_item(
        self,
        ticker: str,
        note: str = "",
        user_id: str = "public",
    ) -> tuple[dict[str, Any], bool]:
        owner = self._owner(user_id)
        normalized = self._ticker(ticker)
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    "INSERT INTO watchlist_items(user_id,ticker,note) "
                    "VALUES (:user_id,:ticker,:note) ON CONFLICT(user_id,ticker) DO NOTHING "
                    "RETURNING ticker,note,added_at"
                ),
                {"user_id": owner, "ticker": normalized, "note": str(note or "").strip()},
            ).mappings().first()
            created = row is not None
            if row is None:
                row = conn.execute(
                    text(
                        "SELECT ticker,note,added_at FROM watchlist_items "
                        "WHERE user_id=:user_id AND ticker=:ticker"
                    ),
                    {"user_id": owner, "ticker": normalized},
                ).mappings().one()
        return {
            "ticker": row["ticker"],
            "note": row["note"],
            "added_at": row["added_at"].isoformat() if hasattr(row["added_at"], "isoformat") else str(row["added_at"]),
        }, created

    def remove_item(self, ticker: str, user_id: str = "public") -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM watchlist_items "
                    "WHERE user_id=:user_id AND ticker=:ticker"
                ),
                {"user_id": self._owner(user_id), "ticker": self._ticker(ticker)},
            )
        return bool(result.rowcount)


_store: WatchlistStore | UnavailableWatchlistStore | None = None


def get_watchlist_store() -> WatchlistStore | UnavailableWatchlistStore:
    global _store
    if _store is None:
        dsn = resolve_core_postgres_dsn(required=False)
        try:
            _store = WatchlistStore(dsn=dsn) if dsn else UnavailableWatchlistStore()
        except Exception:
            _store = UnavailableWatchlistStore()
    return _store


def list_watchlist(user_id: str = "public") -> list[dict[str, Any]]:
    return get_watchlist_store().list_items(user_id=user_id)


def reset_watchlist_store_cache() -> None:
    global _store
    _store = None


__all__ = [
    "LegacyWatchlistStore",
    "WatchlistStore",
    "WatchlistStoreUnavailable",
    "get_watchlist_store",
    "list_watchlist",
    "reset_watchlist_store_cache",
]
