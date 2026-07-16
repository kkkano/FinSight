# -*- coding: utf-8 -*-
"""用户自选股 PostgreSQL 存储。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from backend.config.ticker_mapping import normalize_ticker
from backend.services.database import create_core_engine, resolve_core_postgres_dsn

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
    "WatchlistStore",
    "WatchlistStoreUnavailable",
    "get_watchlist_store",
    "list_watchlist",
    "reset_watchlist_store_cache",
]
