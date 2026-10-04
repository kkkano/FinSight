"""使用首次真实回归保存的规范化模型输出，区分漏绑、漏展示与真正未回答。"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from backend.graph.renderers.research_report import render_research_report
from backend.graph.request_constraints import build_answer_requirements
from backend.graph.synthesis.analysis_requirements import analysis_task_modes
from backend.graph.synthesis.contracts import AgentFinding, Claim, ClaimValidationResult, EvidenceNormalizationResult, NormalizedEvidence, ReportSynthesisDraft, TaskSynthesisResult
from backend.graph.synthesis.requirement_validation import evaluate_answer_requirements
from backend.graph.synthesis.research_synthesis import evaluate_synthesis_quality, synthesize_report_draft, synthesize_task_results
from backend.graph.synthesis.task_outcomes import TaskOutcome
from backend.services.llm_retry import LLMCallContext


def _recorded():
    fixture = json.loads(Path(__file__).with_name("fixtures").joinpath("h01_orcl_earnings_normalized.json").read_text(encoding="utf-8"))
    task = TaskSynthesisResult.model_validate(fixture["task_result"])
    evidence = {key: NormalizedEvidence.model_validate(value) for key, value in fixture["evidence_index"].items()}
    claims = {key: Claim.model_validate(value) for key, value in fixture["claim_index"].items()}
    task.fact_ids = [source_id for source_id in task.fact_ids if source_id in evidence]
    task.requested_subjects = ["ORCL"]
    requirements = build_answer_requirements(fixture["query"], "request_task_1", {"shape": "answer", "dimensions": task.requested_dimensions}, ["fundamental_snapshot", "filing_context", "price_snapshot", "earnings_estimates", "news_context", "transcript_context"], {})
    return fixture, task, evidence, claims, requirements


def test_recorded_growth_analysis_counts_as_partial_financial_support_without_covering_cash_flow():
    _, task, evidence, claims, requirements = _recorded()
    evaluate_answer_requirements(result=task, requirements=requirements, evidence_index=evidence, claim_index=claims, subjects=["ORCL"])
    financial, impact = task.requirement_results
    assert financial["claim_ids"]
    assert financial["answered_components"] == ["revenue", "net_income"]
    assert financial["missing_components"] == ["cash_flow"]
    assert financial["status"] == "partial" and "requirement_explanation_missing" not in financial["reason"]
    assert "get_sec_company_facts_quarterly:s5" in impact["available_evidence_ids"]
    assert "get_stock_price:s15" in impact["evidence_ids"]
    assert impact["status"] == "partial" and impact["reason"] == "requirement_explanation_missing"
    assert "agent_claim:933d312dac76999f" not in financial["claim_ids"]  # 未被实际选中的现金流论据不能代答。


def test_renderer_rechecks_the_evidence_it_actually_shows_and_retains_real_gaps():
    _, task, evidence, claims, requirements = _recorded()
    evaluate_answer_requirements(result=task, requirements=requirements, evidence_index=evidence, claim_index=claims, subjects=["ORCL"], displayed_evidence_ids=task.selected_fact_ids, displayed_claim_ids=task.claim_ids)
    impact = task.requirement_results[1]
    assert not impact["evidence_ids"] and impact["available_evidence_ids"]
    assert "requirement_evidence_not_presented" in impact["reason"]
    draft = ReportSynthesisDraft(status="partial", overall_conclusion=None, task_results=[task], claim_index=claims,
                                 evidence_index=evidence, citation_ids=list(evidence), conflicts=[], disagreements=[], risks=[], limitations=[], fallback_used=False)
    rendered = render_research_report(draft, output_mode="chat")
    impact = draft.task_results[0].requirement_results[1]
    assert "get_sec_company_facts_quarterly:s5" in impact["evidence_ids"]
    assert "get_stock_price:s15" in impact["evidence_ids"]
    assert impact["reason"] == "requirement_explanation_missing"
    assert "现金流的事实解释尚未完成" in rendered.markdown
    assert "财报对股价的影响" in rendered.markdown
    assert rendered.markdown.count("营收同比增速与利润端扩张") == 1


@pytest.mark.asyncio
async def test_saved_duplicate_model_paragraph_is_emitted_once_by_synthesis(monkeypatch):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    fixture, task, evidence, all_claims, requirements = _recorded()
    model_claim = all_claims["synthesis:task_1:explanation"]
    native = {key: claim for key, claim in all_claims.items() if not key.startswith("synthesis:")}

    async def select(**kwargs):
        # 两个兼容输出槽接收到同一实际保存段落时，应合并为一个解释。
        return kwargs["schema"].model_validate({"claim_ids": [task.claim_ids[0]], "direction_supporting_claim_ids": [],
            "fact_ids": task.selected_fact_ids, "explanation": model_claim.text, "explanation_evidence_ids": model_claim.evidence_ids,
            "explanations": [{"text": model_claim.text, "evidence_ids": model_claim.evidence_ids}]})

    monkeypatch.setattr(module, "_invoke_structured", select)
    validation = ClaimValidationResult(valid_claims=native, rejected_claims=[], conflicts=[], quality_block_reasons=[])
    result = (await synthesize_task_results(
        task_outcomes=[TaskOutcome.model_validate(fixture["task_outcome"])], findings=[], claim_validation=validation,
        evidence_normalization=EvidenceNormalizationResult(evidence_by_task={task.task_id: list(evidence.values())}, evidence_index=evidence, rejected_evidence=[], quality_block_reasons=[]),
        llm_call_context_factory=lambda _: LLMCallContext.create(stage="synthesize"),
        requested_dimensions_by_task={task.task_id: task.requested_dimensions}, answer_requirements_by_task={task.task_id: requirements},
    ))[0]
    assert result.conclusion == model_claim.text
    assert len([claim_id for claim_id in result.claim_ids if claim_id.startswith("synthesis:")]) == 1
    assert result.requirement_results[0]["missing_components"] == ["cash_flow"]
    assert result.requirement_results[1]["status"] == "partial"


@pytest.mark.asyncio
async def test_deterministic_technical_facts_are_not_an_analysis_fallback():
    evidence = NormalizedEvidence(source_id="technical", task_ids=["task"], kind="technical_snapshot", usage="fact", subject="AVGO", text="RSI14为62。", structured_data={"rsi14": 62, "ma20": 150})
    normalization = EvidenceNormalizationResult(evidence_by_task={"task": [evidence]}, evidence_index={"technical": evidence}, rejected_evidence=[], quality_block_reasons=[])
    validation = ClaimValidationResult(valid_claims={}, rejected_claims=[], conflicts=[], quality_block_reasons=[])
    outcome = TaskOutcome(task_id="task", title="仅技术面", priority=0, order_index=0, operation="technical", subject_label="AVGO", tickers=["AVGO"], request_frame_id="frame", render_kind="single", render_group_id="frame", intent_status="ready", required_step_ids=["step"], required_evidence=["technical_snapshot"], error_codes=[], status="answered", successful_step_ids=["step"], evidence_ids=["technical"], missing_evidence=[])
    finding = AgentFinding(task_id="task", agent_name="technical_agent", status="partial", claim_ids=[], evidence_ids=[], risks=[], limitations=["该研究维度暂未提供通过引用校验的原生论据，已保留对应事实。"], fallback_used=True, error_codes=[])
    result = (await synthesize_task_results(task_outcomes=[outcome], findings=[finding], claim_validation=validation, evidence_normalization=normalization,
                                          llm_call_context_factory=lambda _: None, answer_requirements_by_task={"task": [{"requirement_id": "technical", "dimension": "technical_quality", "kind": "fact_attribute", "requires_analysis": False, "evidence_kinds": ["technical_snapshot"]}]}))[0]
    assert result.status == "answered" and not result.fallback_used and not result.limitations
    draft = await synthesize_report_draft(task_results=[result], claim_validation=validation, evidence_normalization=normalization, llm_call_context_factory=lambda: None)
    assert evaluate_synthesis_quality(draft=draft, requested_task_ids=["task"], evidence_index=normalization.evidence_index, require_claims=False).state == "pass"


@pytest.mark.parametrize("dimension,expected", [("news_catalysts", False), ("fundamental_quality", False), ("investment_attractiveness", True)])
def test_direction_notice_follows_compiled_requirement_not_legacy_operation(dimension, expected):
    _, task, evidence, claims, _ = _recorded()
    task.operation = "investment_opinion"
    task.requested_dimensions = [dimension]
    task.answer_requirements = []
    task.requirement_results = []
    draft = ReportSynthesisDraft(status="partial", overall_conclusion=None, task_results=[task], claim_index=claims, evidence_index=evidence,
                                 citation_ids=list(evidence), conflicts=[], disagreements=[], risks=[], limitations=[], fallback_used=False)
    markdown = render_research_report(draft, output_mode="chat", direction_readiness={task.task_id: {"direction_allowed": False}}).markdown
    assert ("当前证据不足以形成统一方向判断" in markdown) is expected


@pytest.mark.parametrize("mode", ["chat", "investment_report"])
def test_comparison_evidence_preparation_does_not_repeat_parent_analysis(mode):
    state = {"output_mode": mode, "tasks": [
        {"id": "comparison", "operation": "compare", "required_evidence": ["fundamental_snapshot"]},
        {"id": "company", "operation": "qa", "evidence_support_for": "comparison", "answer_requirements": [{"requirement_id": "legacy", "requires_analysis": True}]},
    ]}
    assert analysis_task_modes(state) == {"comparison": "research", "company": "deterministic"}


@pytest.mark.parametrize("text,expected_error", [(None, None), ("利润率达到999%，因此财务质量优秀。", "explanation_contains_unbound_number")])
def test_claim_only_explanation_references_map_to_verified_evidence_without_loosening_numbers(text, expected_error):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    _, task, evidence, claims, _ = _recorded()
    native = [claims[task.claim_ids[0]]]
    _, claim_aliases, evidence_aliases = module._task_reference_payload(native, list(evidence.values()))
    selection = module._TaskSynthesisSelection(claim_ids=[], direction_supporting_claim_ids=[], explanations=[{
        "text": text or claims["synthesis:task_1:explanation"].text, "claim_ids": ["C1"], "dimension": "fundamental_quality",
    }])
    selected, errors = module._validate_task_selection(selection, claims=native, materials=list(evidence.values()), claim_aliases=claim_aliases, evidence_aliases=evidence_aliases)
    if expected_error:
        assert not selected.explanations and errors[0]["code"] == expected_error
    else:
        assert not errors
        assert selected.explanations[0]["evidence_ids"] == native[0].evidence_ids


def test_missing_reference_diagnostics_keep_the_actual_fields_without_inventing_the_cause():
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    selection = module._TaskSynthesisSelection(claim_ids=[], direction_supporting_claim_ids=[], explanations=[{"text": "一段未绑定解释。", "dimension": "fundamental_quality"}])
    _, errors = module._validate_task_selection(selection, claims=[], materials=[], claim_aliases={}, evidence_aliases={})
    assert errors[0]["provided_fields"] == ["dimension", "text"]
    assert errors[0]["text_present"] is True
    assert errors[0]["claim_references"] == [] and errors[0]["evidence_references"] == []
