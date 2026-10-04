"""旧h12对拍：补充事实不毒化相关解释，未核实引用和总论仍受门禁约束。"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from backend.graph.renderers.research_report import render_research_report
from backend.graph.report_builder import _build_structured_report_payload
from backend.graph.synthesis.contracts import Claim, ClaimValidationResult, EvidenceNormalizationResult, NormalizedEvidence, ReportSynthesisDraft, TaskSynthesisResult
from backend.graph.synthesis.requirement_validation import claim_has_reliable_sources, evaluate_answer_requirements, overall_conclusion_block_reasons
from backend.graph.synthesis.research_synthesis import synthesize_report_draft
from backend.services.llm_retry import LLMCallContext


def _h12():
    path = Path(__file__).with_name("fixtures") / "h12_requirement_gate_projection.json"
    return ReportSynthesisDraft.model_validate(json.loads(path.read_text(encoding="utf-8"))["draft"])


def _check(draft):
    task = draft.task_results[0]
    evaluate_answer_requirements(result=task, requirements=task.answer_requirements, evidence_index=draft.evidence_index, claim_index=draft.claim_index, subjects=["CRM"])
    return {item["requirement_id"].split(":")[-1]: item for item in task.requirement_results}


def test_h12_body_and_calendar_explanations_survive_other_reliable_citations():
    checks = _check(_h12())
    assert checks["business_model"]["status"] == "answered"
    assert checks["business_model"]["claim_ids"] == ["synthesis:task_1:explanation:5"]
    assert checks["competition"]["status"] == "answered"
    assert checks["news_catalysts"]["status"] == "answered"
    assert checks["time_window"]["claim_ids"] == ["synthesis:task_1:explanation:7"]
    assert checks["time_window"]["status"] == "partial"
    assert checks["time_window"]["reason"] == "requirement_observation_conditions_missing"
    for dimension in ("valuation_reasonableness", "risk_level"):
        assert checks[dimension]["status"] == "partial"
        assert checks[dimension]["claim_ids"] == []
        assert checks[dimension]["reason"] == "requirement_explanation_missing"


def _single(extra):
    core = NormalizedEvidence(source_id="core", task_ids=["task"], kind="company_profile", usage="fact", subject="CRM", text="Forward P/E 20。", structured_data={"forwardPE": 20})
    evidence = {"core": core, "extra": extra}
    claim = Claim(claim_id="claim", task_id="task", agent_name="research_analyst", text="估值需要结合盈利预期评估。", stance="unknown", assertion_type="opinion", dimension="valuation", metric="valuation_reasonableness", confidence=0.6, evidence_ids=["core", "extra"], limitations=[])
    requirement = {"requirement_id": "valuation", "kind": "explanation", "dimension": "valuation_reasonableness", "requires_analysis": True, "evidence_kinds": ["company_profile"]}
    task = TaskSynthesisResult(task_id="task", title="估值", priority=0, order_index=0, request_frame_id="frame", render_kind="single", render_group_id="frame", status="answered", conclusion=claim.text, claim_ids=[claim.claim_id], evidence_ids=list(evidence), fact_ids=list(evidence), proposed_direction=None, direction_supporting_claim_ids=[], agent_names=[], agreements=[], disagreements=[], conflicts=[], risks=[], limitations=[], fallback_used=False, error_codes=[], requested_subjects=["CRM"], answer_requirements=[requirement])
    return task, evidence, {claim.claim_id: claim}


@pytest.mark.parametrize("mutation,expected", [({}, "answered"), ({"usage": "raw"}, "partial"), ({"subject": "MSFT"}, "partial"), ({"task_ids": ["other_task"]}, "partial"), ({"metadata": {"subject_binding": "unverified"}}, "partial")])
def test_supplementary_fact_can_differ_in_kind_but_must_be_reliable_and_in_scope(mutation, expected):
    extra = NormalizedEvidence(**{"source_id": "extra", "task_ids": ["task"], "kind": "earnings_estimates", "usage": "fact", "subject": "CRM", "text": "盈利预期快照。", **mutation})
    task, evidence, claims = _single(extra)
    evaluate_answer_requirements(result=task, requirements=task.answer_requirements, evidence_index=evidence, claim_index=claims, subjects=["CRM"])
    assert task.requirement_results[0]["status"] == expected
    assert bool(task.requirement_results[0]["claim_ids"]) is (expected == "answered")


def test_reliable_supplementary_fact_alone_cannot_replace_required_valuation_evidence():
    extra = NormalizedEvidence(source_id="extra", task_ids=["task"], kind="earnings_estimates", usage="fact", subject="CRM", text="盈利预期快照。")
    task, evidence, claims = _single(extra)
    task.fact_ids = ["extra"]
    claims["claim"].evidence_ids = ["extra"]
    evaluate_answer_requirements(result=task, requirements=task.answer_requirements, evidence_index=evidence, claim_index=claims, subjects=["CRM"])
    assert task.requirement_results[0]["status"] == "missing"
    assert not task.requirement_results[0]["claim_ids"]


def test_incomplete_h12_hides_overall_and_raw_dependent_claims_but_keeps_qualified_sections():
    draft = _h12()
    original_overall = draft.overall_conclusion
    _check(draft)
    markdown = render_research_report(draft).markdown
    assert draft.overall_conclusion is None
    assert "无法判断" in markdown and original_overall not in markdown
    assert "公司披露其定位为 CRM 技术全球领导者" in markdown
    assert "竞争差异需按对象类型区分" in markdown
    assert "未来 90 天窗口" in markdown
    assert "均低于 5 年中位数" not in markdown
    assert "信用评级遭下调" not in markdown
    assert "synthesis:task_1:explanation:2" in draft.claim_index  # 原始候选保留作诊断，不能作为成立的研究判断展示。
    assert "answer_requirements_incomplete" in draft.synthesis_validation["overall_block_reasons"]


def test_report_builder_keeps_blocked_overall_unknown_and_preserves_local_explanations():
    draft = _h12()
    artifacts = {"research_result": draft.model_dump(), "research_synthesis": draft.model_dump(), "research_synthesis_gate": {"state": "warn", "reasons": ["answer_requirements_incomplete"]}, "draft_markdown": "## 总判断\n\n" + draft.overall_conclusion}
    state = {"output_mode": "investment_report", "subject": {"tickers": ["CRM"]}, "artifacts": artifacts}
    report = _build_structured_report_payload(state=state, thread_id="fixture", artifacts=artifacts)
    assert report["summary"].startswith("无法判断")
    assert report["sentiment"] == "unknown" and report["confidence_score"] is None
    assert report["report_quality"]["conclusion_status"] == "unavailable"
    assert report["quality_blocked"] is True and report["publishable"] is False
    assert "低估值与高不确定性并存" not in report["draft_markdown"]
    assert "公司披露其定位为 CRM 技术全球领导者" in report["draft_markdown"]


@pytest.mark.asyncio
async def test_incomplete_h12_never_calls_a_model_to_promote_a_global_conclusion():
    draft = _h12()
    _check(draft)

    def forbidden():
        raise AssertionError("缺失义务不能通过另一次总论调用绕过")

    result = await synthesize_report_draft(task_results=draft.task_results,
        claim_validation=ClaimValidationResult(valid_claims=draft.claim_index, rejected_claims=[], conflicts=[], quality_block_reasons=[]),
        evidence_normalization=EvidenceNormalizationResult(evidence_by_task={"task_1": list(draft.evidence_index.values())}, evidence_index=draft.evidence_index, rejected_evidence=[], quality_block_reasons=[]),
        llm_call_context_factory=forbidden)
    assert result.overall_conclusion is None
    assert result.synthesis_validation["overall_block_reasons"]


@pytest.mark.asyncio
@pytest.mark.parametrize("invented_number", [False, True])
async def test_complete_report_still_checks_generated_overall_against_its_facts(monkeypatch, invented_number):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    extra = NormalizedEvidence(source_id="extra", task_ids=["task"], kind="earnings_estimates", usage="fact", subject="CRM", text="盈利预期快照。")
    task, evidence, claims = _single(extra)
    evaluate_answer_requirements(result=task, requirements=task.answer_requirements, evidence_index=evidence, claim_index=claims, subjects=["CRM"])
    candidate = "估值需要结合盈利预期评估。" if not invented_number else "估值对应的市值为999999亿美元。"

    async def response(**kwargs):
        return kwargs["schema"].model_validate({"overall_conclusion": candidate, "supporting_task_ids": ["task"]})

    monkeypatch.setattr(module, "_invoke_structured", response)
    result = await synthesize_report_draft(task_results=[task], claim_validation=ClaimValidationResult(valid_claims=claims, rejected_claims=[], conflicts=[], quality_block_reasons=[]),
        evidence_normalization=EvidenceNormalizationResult(evidence_by_task={"task": list(evidence.values())}, evidence_index=evidence, rejected_evidence=[], quality_block_reasons=[]),
        llm_call_context_factory=lambda: LLMCallContext.create(stage="report_synthesize"))
    assert result.overall_conclusion == task.conclusion
    assert result.fallback_used is invented_number
    assert ("explanation_contains_unbound_number" in result.error_codes) is invented_number
    assert not overall_conclusion_block_reasons(result)
