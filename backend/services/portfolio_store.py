# -*- coding: utf-8 -*-
"""
Independent portfolio storage (Gate-5).

Uses a dedicated SQLite database ``data/portfolio.db`` — intentionally
separated from the LangGraph checkpointer DB to avoid lock contention
and migration coupling.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DB_DIR = Path(os.getenv("FINSIGHT_DATA_DIR", "data"))
_DB_PATH = _DB_DIR / "portfolio.db"


def _get_conn() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS portfolio_positions (
            session_id  TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            shares      REAL NOT NULL,
            avg_cost    REAL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (session_id, ticker)
        );

        CREATE TABLE IF NOT EXISTS rebalance_suggestions (
            suggestion_id TEXT PRIMARY KEY,
            session_id    TEXT NOT NULL,
            data          TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'draft',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_rebalance_session
            ON rebalance_suggestions(session_id, created_at DESC);
    """)
    conn.commit()


# ── Module-level singleton ──────────────────────────────────

_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _get_conn()
        _ensure_tables(_conn)
    return _conn


# ── Portfolio positions CRUD ────────────────────────────────


def get_positions(session_id: str) -> list[dict[str, Any]]:
    rows = _db().execute(
        "SELECT ticker, shares, avg_cost, updated_at FROM portfolio_positions WHERE session_id = ? ORDER BY ticker",
        (session_id,),
    ).fetchall()
    return [
        {"ticker": r[0], "shares": r[1], "avg_cost": r[2], "updated_at": r[3]}
        for r in rows
    ]


def sync_positions(session_id: str, positions: list[dict[str, Any]]) -> int:
    """Replace all positions for *session_id* with the given list."""
    now = datetime.now(timezone.utc).isoformat()
    db = _db()
    db.execute("DELETE FROM portfolio_positions WHERE session_id = ?", (session_id,))
    count = 0
    for pos in positions:
        ticker = str(pos.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        db.execute(
            "INSERT INTO portfolio_positions (session_id, ticker, shares, avg_cost, updated_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, ticker, float(pos.get("shares", 0)), pos.get("avg_cost"), now),
        )
        count += 1
    db.commit()
    return count


def update_position(session_id: str, ticker: str, shares: float, avg_cost: float | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _db().execute(
        """INSERT INTO portfolio_positions (session_id, ticker, shares, avg_cost, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(session_id, ticker) DO UPDATE SET shares=excluded.shares, avg_cost=excluded.avg_cost, updated_at=excluded.updated_at""",
        (session_id, ticker.upper(), shares, avg_cost, now),
    )
    _db().commit()


def remove_position(session_id: str, ticker: str) -> None:
    _db().execute(
        "DELETE FROM portfolio_positions WHERE session_id = ? AND ticker = ?",
        (session_id, ticker.upper()),
    )
    _db().commit()


# ── Rebalance suggestions CRUD ──────────────────────────────


def save_suggestion(suggestion_id: str, session_id: str, data: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _db().execute(
        """INSERT INTO rebalance_suggestions (suggestion_id, session_id, data, status, created_at, updated_at)
           VALUES (?, ?, ?, 'draft', ?, ?)
           ON CONFLICT(suggestion_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
        (suggestion_id, session_id, json.dumps(data, ensure_ascii=False), now, now),
    )
    _db().commit()


def list_suggestions(session_id: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = _db().execute(
        "SELECT suggestion_id, data, status, created_at, updated_at FROM rebalance_suggestions WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for r in rows:
        try:
            parsed = json.loads(r[1])
        except json.JSONDecodeError:
            parsed = {}
        result.append({
            "suggestion_id": r[0],
            "data": parsed,
            "status": r[2],
            "created_at": r[3],
            "updated_at": r[4],
        })
    return result


def patch_suggestion(suggestion_id: str, status: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    cursor = _db().execute(
        "UPDATE rebalance_suggestions SET status = ?, updated_at = ? WHERE suggestion_id = ?",
        (status, now, suggestion_id),
    )
    _db().commit()
    return cursor.rowcount > 0


__all__ = [
    "get_positions",
    "sync_positions",
    "update_position",
    "remove_position",
    "save_suggestion",
    "list_suggestions",
    "patch_suggestion",
]
