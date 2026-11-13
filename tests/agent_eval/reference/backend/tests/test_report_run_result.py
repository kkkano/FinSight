# -*- coding: utf-8 -*-
from __future__ import annotations


def test_report_payload_collects_agent_run_result_for_dashboard_replay(monkeypatch) -> None:
    monkeypatch.setenv("ALERT_LOG_DIR", r"C:\Users\EDY\AppData\Local\Temp\claude\finsight-alert-logs")
    from backend.graph.report_builder import build_report_payload

    chart_spec = {
        "type": "bar",
        "title": "AAPL revenue",
        "data": {"labels": ["Q1"], "values": [92.0], "unit": "$B"},
    }
    state = {
        "output_mode": "investment_report",
        "ui_context": {"run_id": "run-dashboard-1", "source": "dashboard_deep_dive_financial"},
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": ["fundamental_agent"]},
        "plan_ir": {"steps": [{"id": "fund-step", "kind": "agent", "name": "fundamental_agent"}]},
        "artifacts": {
            "draft_markdown": "## AAPL 分析报告\n",
            "evidence_pool": [],
            "errors": [],
            "render_vars": {},
            "step_results": {
                "fund-step": {
                    "output": {
                        "agent_name": "fundamental",
                        "summary": "fundamental summary",
                        "confidence": 0.82,
                        "data_sources": ["yfinance"],
                        "evidence": [
                            {
                                "text": "Revenue: $92.00B",
                                "source": "yfinance",
                                "timestamp": "2026-03-31",
                                "meta": {"source_id": "agent_source:fundamental:1", "metric_key": "revenue"},
                            }
                        ],
                        "claims": [
                            {
                                "claim": "AAPL revenue growth remains positive.",
                                "evidence_ids": ["agent_source:fundamental:1"],
                                "metadata": {"claim_type": "growth_quality"},
                            }
                        ],
                        "chart_specs": [chart_spec],
                    }
                }
            },
        },
        "trace": {},
    }

    report = build_report_payload(state=state, query="分析 AAPL", thread_id="session-1")

    assert isinstance(report, dict)
    assert report["run_id"] == "run-dashboard-1"
    assert report["chart_specs"] == [chart_spec]
    run_result = report["run_result"]
    assert run_result["run_id"] == "run-dashboard-1"
    assert run_result["session_id"] == "session-1"
    assert run_result["chart_specs"] == [chart_spec]
    assert run_result["evidence"][0]["agent_name"] == "fundamental_agent"
    assert run_result["claims"][0]["agent_name"] == "fundamental_agent"
