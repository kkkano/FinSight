# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

from backend.graph.report_builder import build_report_payload
from backend.research.query_coverage import build_answer_targets, coverage_warning_text, evaluate_coverage


def _ledger() -> dict:
    return {
        "ledger_id": "ledger:aapl:test",
        "query": "AAPL 估值、风险、未来三个月看什么",
        "subject": {"tickers": ["AAPL"]},
        "claims": [
            {
                "claim_id": "claim:valuation",
                "claim": "AAPL valuation remains supported by services margin and PE multiple discipline.",
                "stance": "neutral",
                "evidence_ids": ["source:1"],
                "confidence": 0.7,
            },
            {
                "claim_id": "claim:risk",
                "claim": "主要 risk 是需求下行和宏观利率扰动。",
                "stance": "risk",
                "evidence_ids": ["source:2"],
                "confidence": 0.65,
            },
        ],
        "sources": [],
    }


def test_build_answer_targets_from_tasks_reply_contract_and_query() -> None:
    state = {
        "query": "AAPL 估值、风险、未来三个月看什么",
        "tasks": [
            {"id": "t1", "operation": {"name": "generate_report"}},
            {"id": "t2", "operation": {"name": "analyze_impact"}},
            {"id": "t3", "operation": {"name": "technical"}},
        ],
        "reply_contract": {"continuation_target": {"label": "最后直接回答是否继续持有"}},
    }

    targets = build_answer_targets(state)
    target_ids = {item["target_id"] for item in targets}

    assert {"valuation", "risk", "catalyst", "technical", "direct_answer"}.issubset(target_ids)
    assert any(item.get("source") == "continuation_target" for item in targets)


def test_evaluate_coverage_marks_missing_targets() -> None:
    targets = [
        {"target_id": "valuation", "label": "估值"},
        {"target_id": "risk", "label": "风险"},
        {"target_id": "catalyst", "label": "未来三个月"},
    ]

    coverage = evaluate_coverage(_ledger(), targets)

    answered_ids = {item["target_id"] for item in coverage["answered_targets"]}
    unanswered_ids = {item["target_id"] for item in coverage["unanswered_targets"]}
    assert {"valuation", "risk"}.issubset(answered_ids)
    assert "catalyst" in unanswered_ids
    assert coverage_warning_text(coverage).startswith("以下问题尚未被证据账本充分覆盖")


def test_build_report_payload_surfaces_query_coverage_gap() -> None:
    coverage = evaluate_coverage(
        _ledger(),
        [
            {"target_id": "valuation", "label": "估值"},
            {"target_id": "risk", "label": "风险"},
            {"target_id": "catalyst", "label": "未来三个月"},
        ],
    )
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": []},
        "plan_ir": {"steps": []},
        "artifacts": {
            "draft_markdown": "## 投资研报：AAPL\n\n",
            "evidence_ledger": _ledger(),
            "query_coverage": coverage,
            "evidence_pool": [
                {
                    "title": "AAPL valuation update",
                    "url": "https://example.com/aapl",
                    "snippet": "AAPL valuation and downside risk are discussed.",
                    "source": "example",
                    "published_date": "2026-05-18T00:00:00Z",
                    "confidence": 0.8,
                }
            ],
            "step_results": {},
            "errors": [],
            "render_vars": {"investment_summary": "测试摘要"},
        },
        "trace": {},
    }

    report = build_report_payload(state=state, query="AAPL 估值、风险、未来三个月看什么", thread_id="t-coverage")

    assert report["query_coverage"] == coverage
    assert "query_coverage_gap" in (report.get("tags") or [])
    assert (report.get("report_hints") or {}).get("query_coverage") == coverage
    assert any("尚未被证据账本充分覆盖" in str(item) for item in report.get("risks") or [])


def test_synthesize_adds_query_coverage_artifact(monkeypatch) -> None:
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")
    from backend.graph.nodes.synthesize import synthesize

    state = {
        "query": "AAPL 估值、风险、未来三个月看什么",
        "output_mode": "brief",
        "operation": {"name": "generate_report", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_payload": []},
        "artifacts": {"evidence_ledger": _ledger(), "evidence_pool": []},
        "trace": {},
    }

    result = asyncio.run(synthesize(state))
    coverage = (result.get("artifacts") or {}).get("query_coverage") or {}

    assert coverage.get("targets")
    assert any(item.get("target_id") == "catalyst" for item in coverage.get("unanswered_targets") or [])
