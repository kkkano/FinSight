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

from backend.data.migrations import ensure_column

logger = logging.getLogger(__name__)

# 数据目录默认值以本文件位置锚定到「仓库根/data」，避免依赖启动 CWD 造成
# split-brain（曾出现 data/portfolio.db 与 backend/data/portfolio.db 两份）。
# 层级：backend/services/portfolio_store.py → parents[0]=services, [1]=backend, [2]=仓库根。
# Docker 下 WORKDIR=/app、代码在 /app/backend/services/，parents[2]=/app，/app/data 与挂载一致。
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DB_DIR = Path(os.getenv("FINSIGHT_DATA_DIR") or _DEFAULT_DATA_DIR)
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
            user_id     TEXT NOT NULL DEFAULT 'public',
            session_id  TEXT NOT NULL,
            ticker      TEXT NOT NULL,
            shares      REAL NOT NULL,
            avg_cost    REAL,
            updated_at  TEXT NOT NULL,
            PRIMARY KEY (user_id, session_id, ticker)
        );

        CREATE TABLE IF NOT EXISTS rebalance_suggestions (
            user_id      TEXT NOT NULL DEFAULT 'public',
            suggestion_id TEXT NOT NULL,
            session_id    TEXT NOT NULL,
            data          TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'draft',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            PRIMARY KEY (user_id, suggestion_id)
        );
    """)
    ensure_column(
        conn,
        "portfolio_positions",
        "user_id",
        "user_id TEXT NOT NULL DEFAULT 'public'",
    )
    ensure_column(
        conn,
        "rebalance_suggestions",
        "user_id",
        "user_id TEXT NOT NULL DEFAULT 'public'",
    )
    _ensure_portfolio_primary_keys(conn)
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_portfolio_user_session
            ON portfolio_positions(user_id, session_id);
        CREATE INDEX IF NOT EXISTS idx_rebalance_user_session
            ON rebalance_suggestions(user_id, session_id, created_at DESC);
    """)
    conn.commit()


def _primary_key_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(row[1]) for row in sorted(rows, key=lambda row: int(row[5])) if row[5]]


def _ensure_portfolio_primary_keys(conn: sqlite3.Connection) -> None:
    if _primary_key_columns(conn, "portfolio_positions") != ["user_id", "session_id", "ticker"]:
        conn.executescript("""
            ALTER TABLE portfolio_positions RENAME TO portfolio_positions_legacy;
            CREATE TABLE portfolio_positions (
                user_id TEXT NOT NULL DEFAULT 'public',
                session_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                shares REAL NOT NULL,
                avg_cost REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, session_id, ticker)
            );
            INSERT OR REPLACE INTO portfolio_positions
                (user_id, session_id, ticker, shares, avg_cost, updated_at)
            SELECT user_id, session_id, ticker, shares, avg_cost, updated_at
            FROM portfolio_positions_legacy;
            DROP TABLE portfolio_positions_legacy;
        """)
    if _primary_key_columns(conn, "rebalance_suggestions") != ["user_id", "suggestion_id"]:
        conn.executescript("""
            ALTER TABLE rebalance_suggestions RENAME TO rebalance_suggestions_legacy;
            CREATE TABLE rebalance_suggestions (
                user_id TEXT NOT NULL DEFAULT 'public',
                suggestion_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                data TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, suggestion_id)
            );
            INSERT OR REPLACE INTO rebalance_suggestions
                (user_id, suggestion_id, session_id, data, status, created_at, updated_at)
            SELECT user_id, suggestion_id, session_id, data, status, created_at, updated_at
            FROM rebalance_suggestions_legacy;
            DROP TABLE rebalance_suggestions_legacy;
        """)


# ── Module-level singleton ──────────────────────────────────

_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _get_conn()
        _ensure_tables(_conn)
    return _conn


# ── Portfolio positions CRUD ────────────────────────────────


def get_positions(session_id: str, user_id: str = "public") -> list[dict[str, Any]]:
    rows = _db().execute(
        "SELECT ticker, shares, avg_cost, updated_at FROM portfolio_positions WHERE session_id = ? AND user_id = ? ORDER BY ticker",
        (session_id, user_id),
    ).fetchall()
    return [
        {"ticker": r[0], "shares": r[1], "avg_cost": r[2], "updated_at": r[3]}
        for r in rows
    ]


def sync_positions(
    session_id: str,
    positions: list[dict[str, Any]],
    user_id: str = "public",
) -> int:
    """Replace all positions for *session_id* with the given list."""
    now = datetime.now(timezone.utc).isoformat()
    db = _db()
    db.execute(
        "DELETE FROM portfolio_positions WHERE session_id = ? AND user_id = ?",
        (session_id, user_id),
    )
    count = 0
    for pos in positions:
        ticker = str(pos.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        db.execute(
            "INSERT INTO portfolio_positions (user_id, session_id, ticker, shares, avg_cost, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, session_id, ticker, float(pos.get("shares", 0)), pos.get("avg_cost"), now),
        )
        count += 1
    db.commit()
    return count


def update_position(
    session_id: str,
    ticker: str,
    shares: float,
    avg_cost: float | None = None,
    user_id: str = "public",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _db().execute(
        """INSERT INTO portfolio_positions (user_id, session_id, ticker, shares, avg_cost, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, session_id, ticker) DO UPDATE SET shares=excluded.shares, avg_cost=excluded.avg_cost, updated_at=excluded.updated_at""",
        (user_id, session_id, ticker.upper(), shares, avg_cost, now),
    )
    _db().commit()


def remove_position(session_id: str, ticker: str, user_id: str = "public") -> None:
    _db().execute(
        "DELETE FROM portfolio_positions WHERE session_id = ? AND ticker = ? AND user_id = ?",
        (session_id, ticker.upper(), user_id),
    )
    _db().commit()


def list_session_ids(user_id: str = "public") -> list[str]:
    """返回所有持有持仓的 session id（去重）。供盯盘调度遍历用。"""
    rows = _db().execute(
        "SELECT DISTINCT session_id FROM portfolio_positions WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return [r[0] for r in rows]


def list_user_sessions() -> list[tuple[str, str]]:
    """返回全部用户与 session 组合，供后台盯盘调度逐租户扫描。"""
    rows = _db().execute(
        "SELECT DISTINCT user_id, session_id FROM portfolio_positions ORDER BY user_id, session_id"
    ).fetchall()
    return [(str(row[0]), str(row[1])) for row in rows]


# ── Rebalance suggestions CRUD ──────────────────────────────


def save_suggestion(
    suggestion_id: str,
    session_id: str,
    data: dict[str, Any],
    user_id: str = "public",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _db().execute(
        """INSERT INTO rebalance_suggestions (user_id, suggestion_id, session_id, data, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'draft', ?, ?)
           ON CONFLICT(user_id, suggestion_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
        (user_id, suggestion_id, session_id, json.dumps(data, ensure_ascii=False), now, now),
    )
    _db().commit()


def list_suggestions(
    session_id: str,
    limit: int = 10,
    user_id: str = "public",
) -> list[dict[str, Any]]:
    rows = _db().execute(
        "SELECT suggestion_id, data, status, created_at, updated_at FROM rebalance_suggestions WHERE session_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?",
        (session_id, user_id, limit),
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


def patch_suggestion(
    suggestion_id: str,
    status: str,
    user_id: str = "public",
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    cursor = _db().execute(
        "UPDATE rebalance_suggestions SET status = ?, updated_at = ? WHERE suggestion_id = ? AND user_id = ?",
        (status, now, suggestion_id, user_id),
    )
    _db().commit()
    return cursor.rowcount > 0


__all__ = [
    "get_positions",
    "sync_positions",
    "update_position",
    "remove_position",
    "list_session_ids",
    "list_user_sessions",
    "save_suggestion",
    "list_suggestions",
    "patch_suggestion",
]
