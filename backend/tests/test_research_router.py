# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.research_router import ResearchRouterDeps, create_research_router


class _ReportStore:
    def __init__(self):
        self._reports: dict[tuple[str, str], tuple[dict, bool]] = {}

    def add(self, *, session_id: str, report: dict, blocked: bool = False) -> None:
        self._reports[(session_id, str(report["report_id"]))] = (report, blocked)

    def get_report_replay(self, *, session_id: str, report_id: str, include_blocked: bool = False):
        entry = self._reports.get((session_id, report_id))
        if entry is None:
            return None
        report, blocked = entry
        if blocked and not include_blocked:
            return None
        return {"report": report, "citations": list(report.get("citations") or [])}


def _build_client(store: _ReportStore) -> TestClient:
    app = FastAPI()
    app.include_router(create_research_router(ResearchRouterDeps(
        resolve_thread_id=lambda value: str(value or "").strip(),
        get_report_index_store=lambda: store,
    )))
    return TestClient(app)


def _ledger() -> dict:
    return {
        "ledger_id": "ledger:research-router",
        "query": "NVDA debate",
        "subject": {"tickers": ["NVDA"]},
        "claims": [
            {
                "claim_id": "c-bull",
                "claim": "NVDA demand remains resilient.",
                "stance": "bull",
                "evidence_ids": ["s-1"],
                "confidence": 0.8,
            },
            {
                "claim_id": "c-risk",
                "claim": "Valuation can reset if AI capex slows.",
                "stance": "risk",
                "evidence_ids": ["s-2"],
                "confidence": 0.7,
            },
        ],
        "sources": [
            {"source_id": "s-1", "title": "Demand note", "source": "filing", "reliability": 0.8},
            {"source_id": "s-2", "title": "Risk note", "source": "market", "reliability": 0.7},
        ],
        "uncertainties": ["AI capex durability is uncertain."],
        "contradictions": [],
        "coverage_targets": [],
        "created_at": "2026-05-18T00:00:00+00:00",
    }


def _report(report_id: str, *, blocked: bool = False) -> dict:
    report = {
        "report_id": report_id,
        "ticker": "NVDA",
        "title": "NVDA research",
        "summary": "summary",
        "generated_at": "2026-05-18T00:00:00Z",
        "evidence_ledger": _ledger(),
        "citations": [],
    }
    if blocked:
        report["report_quality"] = {
            "state": "block",
            "reasons": [
                {
                    "code": "EVIDENCE_COVERAGE_BELOW_MIN",
                    "severity": "block",
                    "metric": "coverage",
                    "actual": 0.2,
                    "threshold": 0.8,
                    "message": "coverage too low",
                }
            ],
        }
    return report


def test_research_artifact_read_endpoints_use_report_replay_session_access():
    store = _ReportStore()
    session_id = "tenant:user:research-thread"
    store.add(session_id=session_id, report=_report("rpt-research-1"))

    client = _build_client(store)

    ledger_resp = client.get(
        "/api/research/ledger/rpt-research-1",
        params={"session_id": session_id},
    )
    assert ledger_resp.status_code == 200
    ledger_payload = ledger_resp.json()
    assert ledger_payload["success"] is True
    assert ledger_payload["session_id"] == session_id
    assert ledger_payload["ledger"]["ledger_id"] == "ledger:research-router"

    denied_resp = client.get(
        "/api/research/ledger/rpt-research-1",
        params={"session_id": "tenant:user:other-thread"},
    )
    assert denied_resp.status_code == 404


def test_research_artifact_read_endpoints_respect_include_blocked_like_replay():
    store = _ReportStore()
    session_id = "tenant:user:research-blocked"
    store.add(
        session_id=session_id,
        report=_report("rpt-research-blocked", blocked=True),
        blocked=True,
    )

    client = _build_client(store)

    default_resp = client.get(
        "/api/research/ledger/rpt-research-blocked",
        params={"session_id": session_id},
    )
    assert default_resp.status_code == 404

    include_resp = client.get(
        "/api/research/ledger/rpt-research-blocked",
        params={"session_id": session_id, "include_blocked": True},
    )
    assert include_resp.status_code == 200
    assert include_resp.json()["ledger"]["ledger_id"] == "ledger:research-router"


def test_holdings_endpoint_uses_read_only_holdings_tool(monkeypatch):
    import backend.tools.sec_holdings as sec_holdings

    calls: list[tuple[str, int]] = []

    def _fake_holdings(ticker: str, limit: int = 50) -> dict:
        calls.append((ticker, limit))
        return {
            "ticker": ticker,
            "source": "sec_13f",
            "supported_market": "US",
            "holders": [{"holder_name": "Example Capital", "shares": 100}],
            "limit": limit,
            "error": None,
        }

    monkeypatch.setattr(sec_holdings, "get_institution_holdings_by_ticker", _fake_holdings)
    client = _build_client(_ReportStore())

    response = client.get("/api/research/holdings/aapl", params={"limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ticker"] == "AAPL"
    assert payload["holdings"]["holders"][0]["holder_name"] == "Example Capital"
    assert calls == [("AAPL", 5)]
