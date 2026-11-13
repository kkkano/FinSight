"""单任务问题从编译合同传到模型，省略号不能冒充有引用的解释。"""
from __future__ import annotations

import importlib
import json

import pytest

from backend.graph.synthesis.contracts import ClaimValidationResult, EvidenceNormalizationResult, NormalizedEvidence
from backend.graph.synthesis.research_synthesis import _task_reference_payload, _validate_explanation, synthesize_task_results
from backend.graph.synthesis.task_outcomes import build_task_descriptors, finalize_task_outcomes
from backend.services.llm_retry import LLMCallContext


def test_repeated_tool_body_is_sent_once_without_losing_distinct_financial_content():
    data = {"content": "经营现金流为120美元。", "period_end": "2026-06-30", "source_url": "https://example.invalid/filing"}
    evidence = NormalizedEvidence(source_id="source", task_ids=["task"], kind="filing_context", usage="fact",
        text=data["content"], structured_data={**data, "structured_data": dict(data)})
    original = evidence.model_dump()
    payload, _, _ = _task_reference_payload([], [evidence])
    serialized = json.dumps(payload, ensure_ascii=False)
    assert serialized.count(data["content"]) == 1
    assert data["period_end"] in serialized and data["source_url"] in serialized
    assert evidence.model_dump() == original


def _inputs():
    questions = ["如果原油价格走高，会怎样传导到美国通胀、利率预期与航空股？区分已发生的数据和假设推演。", "只解释 COST 现金流的经营含义，不讨论油价或航空股。"]
    tasks = [{"id": f"task_{index}", "title": title, "request_text": request, "operation": {"name": operation}, "subject_label": subject,
              "tickers": tickers, "order_index": index, "priority": 0, "request_frame_id": f"frame_{index}", "render_kind": "single", "render_group_id": f"frame_{index}", "required_evidence": [kind]}
             for index, (title, request, operation, subject, tickers, kind) in enumerate([
                 ("条件宏观分析", questions[0], "macro_brief", "原油及航空行业", [], "macro_context"),
                 ("公司财务", questions[1], "qa", "COST", ["COST"], "fundamental_snapshot"),
             ])]
    steps = [{"id": f"step_{index}", "kind": "tool", "name": "fixture", "task_ids": [task["id"]], "evidence_kinds": task["required_evidence"]} for index, task in enumerate(tasks)]
    descriptors = build_task_descriptors(understanding_tasks=tasks, blocked_tasks=[], plan_tasks=tasks, plan_steps=steps).descriptors
    evidence = [NormalizedEvidence(source_id=f"source_{index}", task_ids=[task["id"]], kind=task["required_evidence"][0], usage="fact", text="可用的已观测数据与来源。") for index, task in enumerate(tasks)]
    normalization = EvidenceNormalizationResult(evidence_by_task={item.task_ids[0]: [item] for item in evidence}, evidence_index={item.source_id: item for item in evidence}, rejected_evidence=[], quality_block_reasons=[])
    claims = ClaimValidationResult(valid_claims={}, rejected_claims=[], conflicts=[], quality_block_reasons=[])
    outcomes = finalize_task_outcomes(descriptors=descriptors, plan_steps=steps, task_results={step["id"]: {"output": "已取得事实"} for step in steps}, evidence_normalization=normalization, claim_validation=claims).outcomes
    return questions, outcomes, normalization, claims


@pytest.mark.asyncio
async def test_compiled_subquestion_and_requirement_description_reach_only_their_task_prompt(monkeypatch):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    questions, outcomes, normalization, claims = _inputs()
    payloads = []
    requirements = {outcome.task_id: [{"requirement_id": f"{outcome.task_id}:mechanism", "dimension": "macro_impact" if index == 0 else "fundamental_quality", "description": "解释原油向航空燃油成本的条件传导" if index == 0 else "解释COST现金流", "requires_analysis": True, "evidence_kinds": outcome.required_evidence}] for index, outcome in enumerate(outcomes)}

    async def select(**kwargs):
        payloads.append(json.loads(kwargs["prompt"].split("\n", 1)[1]))
        return kwargs["schema"].model_validate({"claim_ids": [], "direction_supporting_claim_ids": [], "explanations": [{"text": "条件成立时，经营成本的变化可能影响盈利。", "evidence_ids": ["E1"]}]})

    monkeypatch.setattr(module, "_invoke_structured", select)
    results = await synthesize_task_results(task_outcomes=outcomes, findings=[], claim_validation=claims, evidence_normalization=normalization,
                                           llm_call_context_factory=lambda outcome: LLMCallContext.create(stage="synthesize", agent=outcome.task_id), answer_requirements_by_task=requirements)
    assert [payload["task"]["request_text"] for payload in payloads] == questions
    assert [result.request_text for result in results] == questions
    assert payloads[0]["task"]["operation"] == "macro_brief"
    assert payloads[0]["task"]["answer_requirements"][0]["description"] == "解释原油向航空燃油成本的条件传导"
    assert "COST" not in json.dumps(payloads[0], ensure_ascii=False)
    assert payloads[1]["task"]["request_text"] != questions[0]


@pytest.mark.parametrize("placeholder", ["…", "...", "……", "1. …", "（…）", "---", "💹"])
def test_punctuation_only_explanation_is_rejected_even_with_valid_sources(placeholder):
    evidence = NormalizedEvidence(source_id="fact", task_ids=["task"], kind="macro_context", usage="fact", text="有来源的数据。")
    with pytest.raises(ValueError, match="explanation_placeholder_output"):
        _validate_explanation(placeholder, [evidence], [])


@pytest.mark.asyncio
@pytest.mark.parametrize("attempts", [1, 2])
async def test_placeholder_is_removed_or_corrected_once_in_the_original_context(monkeypatch, attempts):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    questions, outcomes, normalization, claims = _inputs()
    context = LLMCallContext.create(stage="synthesize", max_provider_attempts=attempts)
    calls = []

    async def select(**kwargs):
        calls.append(kwargs)
        assert kwargs["context"] is context
        context.budget.reserve_provider_attempt()
        text = "…" if len(calls) == 1 else "如果原油继续走高，航空公司的燃油成本可能承压；这是条件推演。"
        return kwargs["schema"].model_validate({"claim_ids": [], "direction_supporting_claim_ids": [], "explanations": [{"text": text, "evidence_ids": ["E1"]}]})

    monkeypatch.setattr(module, "_invoke_structured", select)
    result = (await synthesize_task_results(task_outcomes=outcomes[:1], findings=[], claim_validation=claims, evidence_normalization=normalization, llm_call_context_factory=lambda _: context))[0]
    assert len(calls) == attempts and context.budget.remaining == 0
    assert result.synthesis_validation["initial_errors"][0]["code"] == "explanation_placeholder_output"
    if attempts == 1:
        assert result.conclusion is None and not result.claim_ids
        assert result.status == "partial"
    else:
        assert "航空公司的燃油成本" in result.conclusion
        assert result.synthesis_validation["repair_attempts"] == 1
        assert questions[0] in calls[1]["prompt"] and "explanation_placeholder_output" in calls[1]["prompt"]


@pytest.mark.asyncio
async def test_macro_targets_require_individual_binding_even_when_the_dimension_is_shared(monkeypatch):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    _, outcomes, normalization, claims = _inputs()
    requirements = [{"requirement_id": f"task_0:macro:{target}", "kind": "explanation", "dimension": "macro_impact", "description": target,
                     "requires_analysis": True, "requires_explicit_binding": True, "evidence_kinds": ["macro_context"]} for target in ("inflation", "rates", "sector")]

    async def select(**kwargs):
        return kwargs["schema"].model_validate({"claim_ids": [], "direction_supporting_claim_ids": [], "explanations": [{
            "text": "假设原油继续上涨，运输成本可能加大通胀压力。", "evidence_ids": ["E1"], "requirement_ids": ["task_0:macro:inflation"],
        }]})

    monkeypatch.setattr(module, "_invoke_structured", select)
    result = (await synthesize_task_results(task_outcomes=outcomes[:1], findings=[], claim_validation=claims, evidence_normalization=normalization,
                                           llm_call_context_factory=lambda _: LLMCallContext.create(stage="synthesize"), requested_dimensions_by_task={"task_0": ["macro_impact"]}, answer_requirements_by_task={"task_0": requirements}))[0]
    assert [check["status"] for check in result.requirement_results] == ["answered", "partial", "partial"]
    assert result.requirement_results[0]["claim_ids"]
    assert all(not check["claim_ids"] for check in result.requirement_results[1:])


def test_legacy_whole_explanation_does_not_repeat_its_validated_paragraphs():
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    first = {"text": "原油上涨可能加大通胀压力。", "evidence_ids": ["oil"], "dimension": "macro_impact"}
    second = {"text": "航空燃油成本可能上升。", "evidence_ids": ["airline"], "dimension": "macro_impact"}
    whole = {"text": first["text"] + "\n\n" + second["text"], "evidence_ids": ["oil", "airline"]}
    assert module._deduplicate_explanations([whole, first, second]) == [first, second]
