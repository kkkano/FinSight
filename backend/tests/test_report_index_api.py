from __future__ import annotations

import secrets
from copy import deepcopy
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.report_router import ReportRouterDeps, create_report_router


class FakeReportStore:
    """Router contract fake; PostgreSQL behavior is covered by store tests."""

    def __init__(self) -> None:
        self.reports: dict[str, dict[str, Any]] = {}
        self.share_tokens: dict[str, str] = {}

    def add(
        self,
        *,
        user_id: str,
        session_id: str,
        report: dict[str, Any],
        publishable: bool = True,
    ) -> None:
        report_id = str(report["report_id"])
        self.reports[report_id] = {
            "user_id": user_id,
            "session_id": session_id,
            "report": deepcopy(report),
            "publishable": publishable,
        }

    def list_reports(
        self,
        *,
        session_id: str,
        user_id: str,
        ticker: str | None = None,
        query: str | None = None,
        source_type: str | None = None,
        include_blocked: bool = False,
        limit: int = 50,
        **_kwargs: Any,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for report_id, row in self.reports.items():
            report = row["report"]
            if row["user_id"] != user_id or row["session_id"] != session_id:
                continue
            if not include_blocked and not row["publishable"]:
                continue
            if ticker and str(report.get("ticker") or "").upper() != ticker.upper():
                continue
            if query and query.lower() not in str(report).lower():
                continue
            if source_type and report.get("source_type") != source_type:
                continue
            items.append({
                "report_id": report_id,
                "session_id": session_id,
                "ticker": report.get("ticker"),
                "title": report.get("title"),
                "summary": report.get("summary"),
                "quality_state": "pass" if row["publishable"] else "block",
                "publishable": row["publishable"],
            })
        return items[:limit]

    def get_report_replay(
        self,
        *,
        session_id: str,
        report_id: str,
        user_id: str,
        include_blocked: bool = False,
    ) -> dict[str, Any] | None:
        row = self.reports.get(report_id)
        if not row or row["user_id"] != user_id or row["session_id"] != session_id:
            return None
        if not include_blocked and not row["publishable"]:
            return None
        report = deepcopy(row["report"])
        return {
            "report": report,
            "trace_digest": {},
            "citations": deepcopy(report.get("citations") or []),
        }

    def create_share(self, *, report_id: str, user_id: str) -> str | None:
        row = self.reports.get(report_id)
        if not row or row["user_id"] != user_id or not row["publishable"]:
            return None
        existing = next((token for token, value in self.share_tokens.items() if value == report_id), None)
        if existing:
            return existing
        token = secrets.token_urlsafe(24)
        self.share_tokens[token] = report_id
        return token

    def revoke_share(self, *, report_id: str, user_id: str) -> bool:
        row = self.reports.get(report_id)
        if not row or row["user_id"] != user_id:
            return False
        token = next((value for value, target in self.share_tokens.items() if target == report_id), None)
        if not token:
            return False
        del self.share_tokens[token]
        return True

    def get_shared_report(self, *, token: str) -> dict[str, Any] | None:
        report_id = self.share_tokens.get(token)
        row = self.reports.get(report_id or "")
        if not row or not row["publishable"]:
            return None
        return deepcopy(row["report"])


def build_client(store: FakeReportStore, *, user_id: str) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = user_id
        return await call_next(request)

    app.include_router(create_report_router(ReportRouterDeps(
        resolve_thread_id=lambda value: str(value),
        get_report_index_store=lambda: store,
    )))
    return TestClient(app)


def test_report_history_and_replay_are_tenant_scoped() -> None:
    store = FakeReportStore()
    store.add(
        user_id="alice",
        session_id="web:alice:thread-1",
        report={
            "report_id": "rpt-1",
            "ticker": "AAPL",
            "title": "AAPL report",
            "summary": "summary",
            "citations": [{"source_id": "src-1", "url": "https://example.com"}],
        },
    )
    client = build_client(store, user_id="alice")

    history = client.get("/api/reports/index", params={"session_id": "web:alice:thread-1"})
    replay = client.get("/api/reports/replay/rpt-1", params={"session_id": "web:alice:thread-1"})

    assert history.status_code == 200
    assert history.json()["items"][0]["report_id"] == "rpt-1"
    assert replay.status_code == 200
    assert replay.json()["report"]["report_id"] == "rpt-1"
    assert replay.json()["citations"][0]["source_id"] == "src-1"

    assert client.get("/api/reports/index", params={"session_id": "web:bob:thread-1"}).status_code == 404
    assert build_client(store, user_id="public").get(
        "/api/reports/index", params={"session_id": "web:alice:thread-1"}
    ).status_code == 401


def test_blocked_report_requires_explicit_internal_replay_flag() -> None:
    store = FakeReportStore()
    store.add(
        user_id="alice",
        session_id="web:alice:thread-1",
        report={"report_id": "rpt-blocked", "ticker": "AAPL", "title": "blocked"},
        publishable=False,
    )
    client = build_client(store, user_id="alice")

    hidden = client.get("/api/reports/replay/rpt-blocked", params={"session_id": "web:alice:thread-1"})
    visible = client.get(
        "/api/reports/replay/rpt-blocked",
        params={"session_id": "web:alice:thread-1", "include_blocked": True},
    )

    assert hidden.status_code == 404
    assert visible.status_code == 200
