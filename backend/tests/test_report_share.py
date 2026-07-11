# -*- coding: utf-8 -*-
"""WP6-F3 报告分享链接契约。"""
from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def _load_main():
    import backend.api.main as main

    return importlib.reload(main)


def _contains_key(value, prohibited: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in prohibited or _contains_key(item, prohibited) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, prohibited) for item in value)
    return False


def test_report_share_create_anonymous_read_revoke_and_redact(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_INDEX_SQLITE_PATH", str(tmp_path / "report_index.sqlite"))
    monkeypatch.setenv("SUPABASE_AUTH_REQUIRED", "false")
    monkeypatch.delenv("API_PUBLIC_PATHS", raising=False)

    main = _load_main()
    store = main.get_report_index_store()
    store.upsert_report(
        session_id="public:alice:thread",
        report={
            "report_id": "rpt-share-1",
            "ticker": "AAPL",
            "company_name": "Apple",
            "title": "AAPL 报告",
            "summary": "公开摘要",
            "sentiment": "bullish",
            "confidence_score": 0.88,
            "generated_at": "2026-07-12T00:00:00Z",
            "sections": [],
            "citations": [],
            "trace": {"secret": "internal"},
            "cost": {"usd": 1.23},
            "artifacts": {"tool_diagnostics": [{"raw": "internal"}]},
        },
        trace_digest={"span_count": 9},
    )
    client = TestClient(main.app)

    created = client.post("/api/reports/rpt-share-1/share")
    assert created.status_code == 200
    share_url = created.json()["share_url"]
    assert share_url.startswith("/share/r/")

    repeated = client.post("/api/reports/rpt-share-1/share")
    assert repeated.status_code == 200
    assert repeated.json()["share_url"] == share_url

    token = share_url.rsplit("/", 1)[-1]
    monkeypatch.setenv("SUPABASE_AUTH_REQUIRED", "true")
    anonymous_main = _load_main()
    anonymous = TestClient(anonymous_main.app).get(f"/api/reports/shared/{token}")
    assert anonymous.status_code == 200
    payload = anonymous.json()
    assert payload["report"]["report_id"] == "rpt-share-1"
    assert not _contains_key(payload, {"trace", "cost", "tool_diagnostics"})

    monkeypatch.setenv("SUPABASE_AUTH_REQUIRED", "false")
    revoke_main = _load_main()
    revoked = TestClient(revoke_main.app).delete("/api/reports/rpt-share-1/share")
    assert revoked.status_code == 204
    assert TestClient(revoke_main.app).get(f"/api/reports/shared/{token}").status_code == 404
