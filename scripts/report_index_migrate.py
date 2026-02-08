#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_db_path(raw: str | None) -> Path:
    path = (raw or os.getenv("REPORT_INDEX_SQLITE_PATH") or "backend/data/report_index.sqlite").strip()
    return Path(path).expanduser().resolve()


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _ensure_report_index(conn: sqlite3.Connection) -> dict[str, Any]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS report_index (
            report_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            ticker TEXT,
            title TEXT,
            summary TEXT,
            tags_json TEXT,
            generated_at TEXT,
            confidence_score REAL,
            is_favorite INTEGER NOT NULL DEFAULT 0,
            trace_digest_json TEXT,
            report_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    expected = {
        "report_id": "TEXT",
        "session_id": "TEXT",
        "ticker": "TEXT",
        "title": "TEXT",
        "summary": "TEXT",
        "tags_json": "TEXT",
        "generated_at": "TEXT",
        "confidence_score": "REAL",
        "is_favorite": "INTEGER NOT NULL DEFAULT 0",
        "trace_digest_json": "TEXT",
        "report_json": "TEXT NOT NULL",
        "created_at": "TEXT NOT NULL",
        "updated_at": "TEXT NOT NULL",
    }

    existing = _column_names(conn, "report_index")
    added: list[str] = []
    for name, col_def in expected.items():
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE report_index ADD COLUMN {name} {col_def}")
        added.append(name)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_report_index_session ON report_index(session_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_report_index_ticker ON report_index(ticker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_report_index_generated_at ON report_index(generated_at)")

    return {"table": "report_index", "added_columns": added}


def _ensure_citation_index(conn: sqlite3.Connection) -> dict[str, Any]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS citation_index (
            row_id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            source_id TEXT,
            title TEXT,
            url TEXT,
            snippet TEXT,
            published_date TEXT,
            confidence REAL,
            citation_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(report_id) REFERENCES report_index(report_id) ON DELETE CASCADE
        )
        """
    )

    expected = {
        "row_id": "INTEGER",
        "report_id": "TEXT",
        "session_id": "TEXT",
        "source_id": "TEXT",
        "title": "TEXT",
        "url": "TEXT",
        "snippet": "TEXT",
        "published_date": "TEXT",
        "confidence": "REAL",
        "citation_json": "TEXT NOT NULL",
        "created_at": "TEXT NOT NULL",
    }

    existing = _column_names(conn, "citation_index")
    added: list[str] = []
    for name, col_def in expected.items():
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE citation_index ADD COLUMN {name} {col_def}")
        added.append(name)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_citation_index_report ON citation_index(report_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_citation_index_session ON citation_index(session_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_citation_index_url ON citation_index(url)")

    return {"table": "citation_index", "added_columns": added}


def run_migration(db_path: Path, backup_path: Path | None = None) -> dict[str, Any]:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if backup_path is None:
        backup_path = db_path.with_suffix(db_path.suffix + ".pre_migration.bak")

    backup_created = False
    if db_path.exists() and not backup_path.exists():
        shutil.copy2(db_path, backup_path)
        backup_created = True

    with sqlite3.connect(str(db_path)) as conn:
        report_meta = _ensure_report_index(conn)
        citation_meta = _ensure_citation_index(conn)
        conn.commit()

    return {
        "ok": True,
        "db_path": str(db_path),
        "backup_path": str(backup_path),
        "backup_created": backup_created,
        "migrated_at": _now_iso(),
        "tables": [report_meta, citation_meta],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate report_index sqlite schema")
    parser.add_argument("--db", dest="db", default=None, help="SQLite path (default: REPORT_INDEX_SQLITE_PATH)")
    parser.add_argument(
        "--backup",
        dest="backup",
        default=None,
        help="Backup sqlite file path (default: <db>.pre_migration.bak)",
    )
    args = parser.parse_args()

    db_path = _resolve_db_path(args.db)
    backup_path = Path(args.backup).expanduser().resolve() if args.backup else None
    result = run_migration(db_path=db_path, backup_path=backup_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
