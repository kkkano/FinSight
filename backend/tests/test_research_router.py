# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def _load_main_module(tmp_path, monkeypatch):
    sqlite_path = tmp_path / "research_report_index.sqlite"
    monkeypatch.setenv("REPORT_INDEX_SQLITE_PATH", str(sqlite_path))

    import backend.services.report_index as report_index

    report_index._REPORT_INDEX_STORE = None

    import backend.api.main as main

    importlib.reload(main)
    return main


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
        "debate": {
            "enabled": True,
            "status": "done",
            "ledger_id": "ledger:research-router",
            "judge_scorecard": {"evidence_balance": "mixed"},
            "consensus": "mixed",
            "open_questions": [],
        },
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


def test_research_artifact_read_endpoints_use_report_replay_session_access(tmp_path, monkeypatch):
    main = _load_main_module(tmp_path, monkeypatch)
    store = main.get_report_index_store()
    session_id = "tenant:user:research-thread"
    store.upsert_report(session_id=session_id, report=_report("rpt-research-1"), trace_digest={})

    client = TestClient(main.app)

    ledger_resp = client.get(
        "/api/research/ledger/rpt-research-1",
        params={"session_id": session_id},
    )
    assert ledger_resp.status_code == 200
    ledger_payload = ledger_resp.json()
    assert ledger_payload["success"] is True
    assert ledger_payload["session_id"] == session_id
    assert ledger_payload["ledger"]["ledger_id"] == "ledger:research-router"

    debate_resp = client.get(
        "/api/research/debate/rpt-research-1",
        params={"session_id": session_id},
    )
    assert debate_resp.status_code == 200
    assert debate_resp.json()["debate"]["judge_scorecard"]["evidence_balance"] == "mixed"

    denied_resp = client.get(
        "/api/research/ledger/rpt-research-1",
        params={"session_id": "tenant:user:other-thread"},
    )
    assert denied_resp.status_code == 404


def test_research_artifact_read_endpoints_respect_include_blocked_like_replay(tmp_path, monkeypatch):
    main = _load_main_module(tmp_path, monkeypatch)
    store = main.get_report_index_store()
    session_id = "tenant:user:research-blocked"
    store.upsert_report(
        session_id=session_id,
        report=_report("rpt-research-blocked", blocked=True),
        trace_digest={},
        include_blocked=True,
    )

    client = TestClient(main.app)

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


def test_run_debate_builds_artifact_from_ledger_payload_without_graph_run(tmp_path, monkeypatch):
    main = _load_main_module(tmp_path, monkeypatch)

    async def _fail_graph_runner():
        raise AssertionError("run-debate must not start a graph run")

    monkeypatch.setattr(main, "aget_graph_runner", _fail_graph_runner)

    client = TestClient(main.app)
    response = client.post(
        "/api/research/run-debate",
        json={"query": "NVDA debate", "ledger": _ledger()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["debate"]["status"] == "done"
    assert payload["debate"]["ledger_id"] == "ledger:research-router"
    assert payload["debate"]["bull_thesis"]["claim_count"] == 1
    assert payload["debate"]["bear_thesis"]["claim_count"] == 1


def test_holdings_endpoint_uses_read_only_holdings_tool(tmp_path, monkeypatch):
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
    main = _load_main_module(tmp_path, monkeypatch)
    client = TestClient(main.app)

    response = client.get("/api/research/holdings/aapl", params={"limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ticker"] == "AAPL"
    assert payload["holdings"]["holders"][0]["holder_name"] == "Example Capital"
    assert calls == [("AAPL", 5)]
