# -*- coding: utf-8 -*-
"""WP6-F3 报告分享链接契约。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.report_router import ReportRouterDeps, create_report_router
from backend.tests.test_report_index_api import FakeReportStore


def _client(store, *, user_id: str) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = user_id
        return await call_next(request)

    app.include_router(
        create_report_router(
            ReportRouterDeps(
                resolve_thread_id=lambda value: str(value),
                get_report_index_store=lambda: store,
            )
        )
    )
    return TestClient(app)


def _contains_key(value, prohibited: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in prohibited or _contains_key(item, prohibited) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, prohibited) for item in value)
    return False


def test_report_share_create_anonymous_read_revoke_and_redact():
    store = FakeReportStore()
    store.add(
        user_id="alice",
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
            "sections": [{
                "title": "结论",
                "order": 1,
                "contents": [{
                    "type": "text",
                    "content": "公开正文",
                    "citation_refs": ["src-1"],
                    "metadata": {
                        "label": "公开标签",
                        "authorization": "Bearer secret",
                    },
                }],
            }],
            "citations": [{
                "source_id": "src-1",
                "title": "Source",
                "url": "javascript:alert(1)",
                "snippet": "公开摘录",
            }],
            "trace": {"secret": "internal"},
            "cost": {"usd": 1.23},
            "artifacts": {"tool_diagnostics": [{"raw": "internal"}]},
            "meta": {
                "thread_id": "public:alice:thread",
                "graph_trace": {"raw": "internal"},
                "report_builder_input": {
                    "query": "我的私密问题",
                    "draft_markdown": "内部草稿",
                    "render_vars": {"secret": "internal"},
                },
            },
            "run_result": {"events": ["internal"]},
            "evidence_ledger": {"query": "我的私密问题"},
        },
    )
    client = _client(store, user_id="alice")

    assert _client(store, user_id="public").post("/api/reports/rpt-share-1/share").status_code == 401
    assert _client(store, user_id="bob").post("/api/reports/rpt-share-1/share").status_code == 404
    created = client.post("/api/reports/rpt-share-1/share")
    assert created.status_code == 200
    share_url = created.json()["share_url"]
    assert share_url.startswith("/share/r/")

    repeated = client.post("/api/reports/rpt-share-1/share")
    assert repeated.status_code == 200
    assert repeated.json()["share_url"] == share_url

    token = share_url.rsplit("/", 1)[-1]
    anonymous = _client(store, user_id="public").get(f"/api/reports/shared/{token}")
    assert anonymous.status_code == 200
    assert anonymous.headers["cache-control"] == "private, no-store"
    payload = anonymous.json()
    assert payload["report"]["report_id"] == "rpt-share-1"
    assert payload["report"]["sections"][0]["contents"][0] == {
        "type": "text",
        "content": "公开正文",
        "citation_refs": ["src-1"],
    }
    assert payload["report"]["citations"][0]["url"] == ""
    assert not _contains_key(payload, {
        "trace",
        "cost",
        "tool_diagnostics",
        "meta",
        "graph_trace",
        "report_builder_input",
        "run_result",
        "evidence_ledger",
        "metadata",
        "session_id",
        "thread_id",
    })

    assert _client(store, user_id="bob").delete("/api/reports/rpt-share-1/share").status_code == 404
    assert _client(store, user_id="public").get(f"/api/reports/shared/{token}").status_code == 200

    revoked = client.delete("/api/reports/rpt-share-1/share")
    assert revoked.status_code == 204
    assert _client(store, user_id="public").get(f"/api/reports/shared/{token}").status_code == 404
