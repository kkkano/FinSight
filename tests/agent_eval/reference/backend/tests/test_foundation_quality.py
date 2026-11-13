# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from backend.graph.nodes.validate import validate
from backend.graph.report_builder import _build_structured_report_payload
from backend.graph.synthesis.contracts import Claim, NormalizedEvidence, ReportSynthesisDraft, TaskSynthesisResult
from backend.report.evidence_policy import extract_report_quality, merge_quality_states, normalize_quality_state
from backend.report.quality_engine import evaluate_result_quality


def _result(*, supported: bool = True, facts_only: bool = False, missing: list[str] | None = None):
    evidence = NormalizedEvidence(source_id="fixture-source", task_ids=["task"], kind="fundamental_snapshot", usage="fact", text="经营现金流为 20 亿美元。", url="https://example.invalid/source")
    claim = Claim(claim_id="fixture-claim", task_id="task", agent_name="fundamental_agent", text="经营现金流能够覆盖部分资本开支。", stance="neutral", assertion_type="fact", dimension="fundamental", confidence=0.8, evidence_ids=[evidence.source_id], limitations=[])
    task = TaskSynthesisResult(task_id="task", title="公司研究", priority=0, order_index=0, request_frame_id="frame", render_kind="single", render_group_id="frame", status="partial" if missing else "answered" if supported else "unavailable", conclusion=claim.text if supported and not facts_only else None, claim_ids=[claim.claim_id] if supported and not facts_only else [], evidence_ids=[evidence.source_id] if supported else [], fact_ids=[evidence.source_id] if supported else [], proposed_direction=None, direction_supporting_claim_ids=[], agent_names=[], agreements=[], disagreements=[], conflicts=[], risks=[], limitations=[], fallback_used=False, error_codes=[], missing_evidence=missing or [])
    return ReportSynthesisDraft(status=task.status, overall_conclusion=task.conclusion, task_results=[task], claim_index={claim.claim_id: claim} if supported and not facts_only else {}, evidence_index={evidence.source_id: evidence} if supported else {}, citation_ids=[evidence.source_id] if supported else [], conflicts=[], disagreements=[], risks=[], limitations=[], fallback_used=False)


@pytest.mark.parametrize("legacy,expected", [("degraded", "warn"), ("warn", "warn"), ("block", "block"), ("unknown-state", "block")])
def test_quality_uses_one_enum_and_preserves_legacy_severity(legacy, expected):
    assert normalize_quality_state(legacy) == expected
    assert merge_quality_states("block", legacy, "pass") == "block"


def test_report_direct_quality_cannot_hide_nested_policy_block():
    quality = extract_report_quality({"report_quality": {"state": "pass", "reasons": []}, "meta": {"report_quality": {"state": "block", "reasons": [{"code": "SOURCE_INVALID", "severity": "block"}]}}})
    assert quality["state"] == "block"
    assert quality["reasons"][0]["code"] == "SOURCE_INVALID"


@pytest.mark.parametrize("supported", [True, False])
def test_structured_report_keeps_validator_source_and_coverage_block(supported):
    draft = _result(supported=supported)
    gate = {"state": "pass" if supported else "degraded", "reasons": [] if supported else ["missing_supported_task_conclusion"]}
    artifacts = {"research_result": draft.model_dump(), "research_synthesis": draft.model_dump(), "research_synthesis_gate": gate, "draft_markdown": "受限报告预览。"}
    state = {"output_mode": "investment_report", "subject": {"tickers": ["QA"]}, "artifacts": artifacts}
    report = _build_structured_report_payload(state=state, thread_id="qa-thread", artifacts=artifacts)
    quality = evaluate_result_quality(state=state, report=report)
    assert quality["state"] == "block"
    assert report["quality_blocked"] is True
    assert report["publishable"] is False
    assert "EVIDENCE_SOURCES_BELOW_MIN" in {reason["code"] for reason in quality["reasons"]}


def test_zero_claims_blocks_report_but_tool_facts_remain_supported_chat_content():
    artifacts = {"research_result": _result(facts_only=True).model_dump()}
    chat = evaluate_result_quality(state={"output_mode": "chat", "artifacts": artifacts})
    report = evaluate_result_quality(state={"output_mode": "investment_report", "artifacts": artifacts})
    assert chat["state"] == "pass" and chat["has_supported_content"] is True
    assert report["state"] == "block" and report["has_supported_content"] is True
    assert report["publishable"] is False


def test_chat_render_block_enters_the_same_quality_consumer_without_report():
    state = {"output_mode": "chat", "artifacts": {"draft_markdown": "不可用提示。", "quality_blocked": True, "error_code": "task_render_coverage_mismatch"}}
    quality = evaluate_result_quality(state=state)
    validated = validate(state)
    assert quality["state"] == "block" and quality["publishable"] is False
    assert validated["artifacts"]["result_quality"]["state"] == "block"


def test_per_subject_missing_requirement_stays_visible_in_chat_and_report():
    missing = {"task_id": "task", "subject": "MSFT", "evidence_kind": "technical_snapshot", "reason": "no_producer"}
    state = {"output_mode": "chat", "artifacts": {"research_result": _result(facts_only=True).model_dump()}, "trace": {"coverage_validator": {"missing_requirements": [missing]}}}
    chat = evaluate_result_quality(state=state)
    report = evaluate_result_quality(state={**state, "output_mode": "investment_report"})
    assert chat["state"] == "warn" and chat["answer_status"] == "partial"
    assert chat["missing_requirements"] == [missing]
    assert report["state"] == "block"


def test_completed_requirements_remain_answered_with_execution_warning():
    state = {"output_mode": "chat", "artifacts": {
        "research_result": _result().model_dump(),
        "research_result_quality": {"state": "warn", "reasons": [{"code": "RECOVERED_PROVIDER_FAILURE", "severity": "warn"}]},
    }}
    quality = evaluate_result_quality(state=state)
    assert quality["state"] == "warn"
    assert quality["answer_status"] == "answered" and quality["missing_requirements"] == []


def test_clarification_has_no_answered_or_publishable_terminal_state():
    state = {"understanding": {"route": "clarify"}, "artifacts": {"draft_markdown": "请补充公司名称。"}}
    quality = evaluate_result_quality(state=state)
    assert quality["answer_status"] == "clarification_required"
    assert quality["publishable"] is False and quality["has_supported_content"] is False
    from backend.report.quality_engine import should_publish_report
    from backend.services.report_index import _derive_quality_fields
    report = {"report_quality": quality}
    assert should_publish_report(report) is False
    assert _derive_quality_fields(report)[1] == 0
