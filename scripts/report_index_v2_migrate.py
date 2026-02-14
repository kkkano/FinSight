"""研报库三层架构迁移: 为 report_index 表添加 source_type / filing_type / publisher 字段。

运行方式:
    python -m scripts.report_index_v2_migrate

变更:
    1. ALTER TABLE report_index ADD COLUMN source_type (ai_generated | official_filing | third_party)
    2. ALTER TABLE report_index ADD COLUMN filing_type (10-K, 10-Q, 8-K, annual, interim, prospectus 等)
    3. ALTER TABLE report_index ADD COLUMN publisher (券商/投行名称)
    4. 回填现有记录 source_type = 'ai_generated'
    5. 创建 idx_report_index_source_type 索引
"""
from __future__ import annotations

import os
import sqlite3
import sys


def _get_db_path() -> str:
    return os.path.abspath(os.getenv("REPORT_INDEX_SQLITE_PATH", "backend/data/report_index.sqlite"))


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def migrate(db_path: str | None = None) -> dict[str, str]:
    path = db_path or _get_db_path()
    if not os.path.exists(path):
        return {"status": "skipped", "reason": f"database not found: {path}"}

    conn = sqlite3.connect(path)
    results: list[str] = []

    try:
        # Step 1: 添加 source_type 字段
        if not _column_exists(conn, "report_index", "source_type"):
            conn.execute(
                "ALTER TABLE report_index ADD COLUMN source_type TEXT NOT NULL DEFAULT 'ai_generated'"
            )
            results.append("added column source_type")

        # Step 2: 添加 filing_type 字段
        if not _column_exists(conn, "report_index", "filing_type"):
            conn.execute("ALTER TABLE report_index ADD COLUMN filing_type TEXT")
            results.append("added column filing_type")

        # Step 3: 添加 publisher 字段
        if not _column_exists(conn, "report_index", "publisher"):
            conn.execute("ALTER TABLE report_index ADD COLUMN publisher TEXT")
            results.append("added column publisher")

        # Step 4: 回填现有记录
        conn.execute(
            "UPDATE report_index SET source_type = 'ai_generated' WHERE source_type IS NULL OR source_type = ''"
        )
        backfilled = conn.execute(
            "SELECT changes()"
        ).fetchone()[0]
        if backfilled:
            results.append(f"backfilled {backfilled} rows with source_type=ai_generated")

        # Step 5: 创建索引
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_report_index_source_type ON report_index(source_type)"
        )
        results.append("ensured index idx_report_index_source_type")

        conn.commit()
        return {"status": "ok", "changes": results, "db_path": path}
    except Exception as exc:
        conn.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        conn.close()


if __name__ == "__main__":
    result = migrate()
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["status"] in ("ok", "skipped") else 1)
