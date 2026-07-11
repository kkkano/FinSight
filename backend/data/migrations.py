"""小型 SQLite 幂等迁移助手。"""

from __future__ import annotations

import re
import sqlite3


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validated_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"非法 SQLite 标识符: {value!r}")
    return value


def ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    ddl: str,
) -> None:
    """探测表结构，缺列时执行一次 ``ALTER TABLE ... ADD COLUMN``。"""

    safe_table = _validated_identifier(table)
    safe_column = _validated_identifier(column)
    columns = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({safe_table})").fetchall()
    }
    if safe_column not in columns:
        conn.execute(f"ALTER TABLE {safe_table} ADD COLUMN {ddl}")


__all__ = ["ensure_column"]
