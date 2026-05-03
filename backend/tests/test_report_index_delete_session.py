# -*- coding: utf-8 -*-
from __future__ import annotations


def test_report_index_store_deletes_reports_and_citations_for_session(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_INDEX_SQLITE_PATH", str(tmp_path / "report_index.sqlite"))

    from backend.services.report_index import ReportIndexStore

    store = ReportIndexStore()
    report = {
        "report_id": "rpt-delete-session",
        "ticker": "AAPL",
        "title": "AAPL report",
        "summary": "summary",
        "generated_at": "2026-05-03T00:00:00Z",
        "citations": [
            {"title": "source", "url": "https://example.com/aapl", "snippet": "snippet"},
        ],
    }
    store.upsert_report(session_id="public:user:thread-a", report=report)
    store.upsert_report(
        session_id="public:user:thread-b",
        report={**report, "report_id": "rpt-keep-session"},
    )

    deleted = store.delete_session(session_id="public:user:thread-a")

    assert deleted == {"reports": 1, "citations": 1}
    assert store.list_reports(session_id="public:user:thread-a", include_blocked=True) == []
    assert len(store.list_reports(session_id="public:user:thread-b", include_blocked=True)) == 1
