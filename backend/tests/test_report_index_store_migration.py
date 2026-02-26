# -*- coding: utf-8 -*-
import importlib
import sqlite3


def test_report_index_store_upgrades_legacy_schema_before_creating_quality_indexes(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "legacy_report_index.sqlite"

    with sqlite3.connect(sqlite_path) as conn:
        conn.executescript(
            """
            CREATE TABLE report_index (
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
                source_type TEXT NOT NULL DEFAULT 'ai_generated',
                filing_type TEXT,
                publisher TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX idx_report_index_session ON report_index(session_id);
            CREATE INDEX idx_report_index_ticker ON report_index(ticker);
            CREATE INDEX idx_report_index_generated_at ON report_index(generated_at);
            CREATE INDEX idx_report_index_source_type ON report_index(source_type);

            CREATE TABLE citation_index (
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
                created_at TEXT NOT NULL
            );
            CREATE INDEX idx_citation_index_report ON citation_index(report_id);
            CREATE INDEX idx_citation_index_session ON citation_index(session_id);
            CREATE INDEX idx_citation_index_url ON citation_index(url);
            """
        )
        conn.commit()

    monkeypatch.setenv("REPORT_INDEX_SQLITE_PATH", str(sqlite_path))

    import backend.services.report_index as report_index_module

    report_index_module = importlib.reload(report_index_module)
    store = report_index_module.ReportIndexStore()
    assert store.path == str(sqlite_path.resolve())

    with sqlite3.connect(sqlite_path) as conn:
        report_cols = {row[1] for row in conn.execute("PRAGMA table_info(report_index)").fetchall()}
        assert {"quality_state", "publishable", "quality_reasons_json"}.issubset(report_cols)

        index_names = {row[1] for row in conn.execute("PRAGMA index_list(report_index)").fetchall()}
        assert "idx_report_index_quality_state" in index_names
        assert "idx_report_index_publishable" in index_names

    assert store.list_reports(session_id="tenant:user:thread", limit=5) == []
