# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.report_builder import _archive_report_predictions


def test_report_archive_only_links_validated_prediction_from_eligible_agent(monkeypatch):
    calls = []

    class Store:
        def attach_report(self, prediction_id, *, user_id, report_id):
            calls.append((prediction_id, user_id, report_id))
            return True

    monkeypatch.setattr(
        "backend.services.agent_prediction_store.get_agent_prediction_store",
        lambda: Store(),
    )
    result = _archive_report_predictions(
        report_id="rpt-1",
        user_id="alice",
        plan_steps=[
            {"id": "eligible", "kind": "agent", "inputs": {"prediction_eligible": True}},
            {"id": "plain", "kind": "agent", "inputs": {}},
        ],
        step_results={
            "eligible": {"output": {"prediction": {"id": "00000000-0000-0000-0000-000000000001"}}},
            "plain": {"output": {"prediction": {"id": "must-not-link"}}},
        },
    )

    assert result["status"] == "archived"
    assert result["archived"] == 1
    assert calls == [("00000000-0000-0000-0000-000000000001", "alice", "rpt-1")]


def test_report_archive_records_prediction_missing_without_guessing_from_summary():
    result = _archive_report_predictions(
        report_id="rpt-1",
        user_id="alice",
        plan_steps=[{"id": "eligible", "kind": "agent", "inputs": {"prediction_eligible": True}}],
        step_results={"eligible": {"output": {"summary": "AAPL 看多，目标 220"}}},
    )

    assert result == {
        "eligible_steps": 1,
        "archived": 0,
        "prediction_ids": [],
        "status": "prediction_missing",
    }
