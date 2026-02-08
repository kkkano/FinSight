from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATE_SCRIPT = REPO_ROOT / 'scripts' / 'report_index_migrate.py'
ROLLBACK_SCRIPT = REPO_ROOT / 'scripts' / 'report_index_rollback.py'


def _run_script(script: Path, *args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(REPO_ROOT),
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(proc.stdout)


def test_report_index_migrate_script_creates_tables_and_backup(tmp_path):
    db_path = tmp_path / 'report_index.sqlite'
    backup_path = tmp_path / 'report_index.sqlite.pre_migration.bak'

    # Create existing sqlite so migration should create backup.
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE seed_table(id INTEGER PRIMARY KEY, value TEXT)')
        conn.execute('INSERT INTO seed_table(value) VALUES (?)', ('seed',))
        conn.commit()

    result = _run_script(MIGRATE_SCRIPT, '--db', str(db_path), '--backup', str(backup_path))

    assert result.get('ok') is True
    assert result.get('backup_created') is True
    assert backup_path.exists()

    with sqlite3.connect(db_path) as conn:
        table_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert 'report_index' in table_names
        assert 'citation_index' in table_names

        report_cols = {row[1] for row in conn.execute('PRAGMA table_info(report_index)').fetchall()}
        citation_cols = {row[1] for row in conn.execute('PRAGMA table_info(citation_index)').fetchall()}

    assert {'report_id', 'session_id', 'report_json', 'created_at', 'updated_at'}.issubset(report_cols)
    assert {'report_id', 'session_id', 'source_id', 'citation_json', 'created_at'}.issubset(citation_cols)


def test_report_index_rollback_script_restores_backup(tmp_path):
    db_path = tmp_path / 'report_index.sqlite'
    backup_path = tmp_path / 'report_index.sqlite.pre_migration.bak'

    # Original snapshot.
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE legacy_state(id INTEGER PRIMARY KEY, note TEXT)')
        conn.execute('INSERT INTO legacy_state(note) VALUES (?)', ('before-migrate',))
        conn.commit()

    backup_path.write_bytes(db_path.read_bytes())

    # Mutate current db to emulate post-migration/corrupted state.
    db_path.write_bytes(b'corrupted-db-content')

    result = _run_script(ROLLBACK_SCRIPT, '--db', str(db_path), '--backup', str(backup_path))

    assert result.get('ok') is True
    assert result.get('restored_from_backup') is True

    with sqlite3.connect(db_path) as conn:
        table_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert 'legacy_state' in table_names
        assert 'report_index' not in table_names

        restored = conn.execute('SELECT note FROM legacy_state').fetchall()
    assert restored == [('before-migrate',)]
