#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_db_path(raw: str | None) -> Path:
    path = (raw or os.getenv("REPORT_INDEX_SQLITE_PATH") or "backend/data/report_index.sqlite").strip()
    return Path(path).expanduser().resolve()


def _safe_unlink(path: Path, *, attempts: int = 20, sleep_seconds: float = 0.05) -> None:
    if not path.exists():
        return
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(sleep_seconds)
    if last_error is not None:
        raise last_error


def run_rollback(db_path: Path, backup_path: Path | None = None) -> dict[str, Any]:
    if backup_path is None:
        backup_path = db_path.with_suffix(db_path.suffix + ".pre_migration.bak")

    if not backup_path.exists():
        raise FileNotFoundError(f"backup not found: {backup_path}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    restored_from_backup = False

    backup_bytes = backup_path.read_bytes()
    last_error: Exception | None = None
    for _ in range(20):
        try:
            with open(db_path, 'wb') as handle:
                handle.write(backup_bytes)
            restored_from_backup = True
            break
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)

    if not restored_from_backup and last_error is not None:
        raise last_error

    for suffix in ('-wal', '-shm', '-journal'):
        try:
            _safe_unlink(Path(f"{db_path}{suffix}"), attempts=1)
        except PermissionError:
            # best effort cleanup; rollback result should not fail for sidecar locks
            pass

    return {
        "ok": True,
        "db_path": str(db_path),
        "backup_path": str(backup_path),
        "restored_from_backup": restored_from_backup,
        "rolled_back_at": _now_iso(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rollback report_index sqlite schema")
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
    result = run_rollback(db_path=db_path, backup_path=backup_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
