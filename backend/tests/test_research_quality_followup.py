"""真实验收暴露的执行、文档身份与解释绑定断点。"""
from copy import deepcopy

import pytest

from backend.graph.dag_executor import execute_plan_dag
from backend.graph.synthesis.contracts import NormalizedEvidence
from backend.graph.synthesis.research_synthesis import _TaskSynthesisSelection, _validate_task_selection, normalize_evidence
from backend.graph.synthesis.task_outcomes import TaskDescriptor


def test_registry_json_is_structured_before_execution_and_agent_sharing(monkeypatch):
    from types import SimpleNamespace
    from backend.graph.adapters.tool_adapter import build_tool_invokers
    from backend.graph.execution import request_data
    from backend import langchain_tools

    monkeypatch.setattr(request_data, "current_request_data", lambda: None)
    monkeypatch.setattr(langchain_tools, "get_tool_by_name", lambda _name: SimpleNamespace(
        invoke=lambda _inputs: '{"error":"invalid_close_path","metrics":{}}'))
    assert build_tool_invokers(allowed_tools=["window"])["window"]({}) == {
        "error": "invalid_close_path", "metrics": {}}


@pytest.mark.asyncio
async def test_business_error_retains_output_and_only_skips_dependent_steps():
    async def bad(_inputs):
        return {"error": "invalid_close_path", "invalid_session_date": "2026-10-01", "metrics": {}}

    async def good(_inputs):
        return {"value": 10}

    steps = [
        {"id": "bad", "kind": "tool", "name": "bad", "inputs": {}, "depends_on": []},
        {"id": "dependent", "kind": "tool", "name": "good", "inputs": {}, "depends_on": ["bad"]},
        {"id": "independent", "kind": "tool", "name": "good", "inputs": {}, "depends_on": []},
    ]
    artifacts, _ = await execute_plan_dag({"steps": steps}, tool_invokers={"bad": bad, "good": good}, dry_run=False)
    assert artifacts["step_results"]["bad"]["status_reason"] == "error"
    assert artifacts["step_results"]["bad"]["output"]["invalid_session_date"] == "2026-10-01"
    assert len(artifacts["errors"]) == 1
    assert artifacts["step_results"]["dependent"]["status_reason"] == "upstream_failed"
    assert artifacts["step_results"]["independent"]["status_reason"] == "done"


def _descriptor(task_id, ticker):
    return TaskDescriptor(task_id=task_id, title=ticker, priority=0, order_index=0,
        operation="qa", subject_label=ticker, tickers=[ticker], request_frame_id=task_id,
        render_kind="single", render_group_id=task_id, intent_status="ready",
        required_step_ids=[], required_evidence=["document_context"], error_codes=[])


def test_shared_document_not_rebound_to_search_ticker_or_conflicted_by_call_score():
    evidence = {"source_id": "shared", "kind": "document_context", "text": "AMD product roadmap",
        "url": "https://example.com/amd", "meta": {"shared_document": True, "document_body": "AMD product roadmap"}}
    first, second = deepcopy(evidence), deepcopy(evidence)
    first["meta"]["evidence_quality"] = {"overall_score": .35}
    second["meta"]["evidence_quality"] = {"overall_score": .36}
    steps = [{"id": task_id, "kind": "agent", "name": "deep_search_agent", "task_ids": [task_id],
        "inputs": {"ticker": ticker}, "evidence_kinds": ["document_context"]}
        for task_id, ticker in [("a", "AMD"), ("n", "NVDA")]]
    result = normalize_evidence(task_descriptors=[_descriptor("a", "AMD"), _descriptor("n", "NVDA")],
        plan_steps=steps, agent_outputs={"a": {"evidence": [first]}, "n": {"evidence": [second]}}, raw_evidence_by_task={})
    assert not result.quality_block_reasons
    assert result.evidence_index["shared"].task_ids == ["a", "n"]
    assert result.evidence_index["shared"].subject is None


def test_same_identity_with_different_actual_content_still_blocks():
    rows = [{"source_id": "same", "kind": "fundamental_snapshot", "text": "reported value",
        "structured_data": {"value": value}, "task_ids": ["a"]} for value in (10, 20)]
    result = normalize_evidence(task_descriptors=[_descriptor("a", "AMD")], plan_steps=[],
        agent_outputs={}, raw_evidence_by_task={"a": rows})
    assert result.quality_block_reasons == ["evidence_id_content_conflict"]


def test_legacy_single_explanation_binds_to_unique_analysis_requirement():
    source = NormalizedEvidence(source_id="source", task_ids=["a"], kind="document_context",
        usage="fact", text="客户续约支持业务竞争优势。", metadata={"content_read": True, "document_body": "客户续约支持业务竞争优势。"})
    result, errors = _validate_task_selection(
        _TaskSynthesisSelection(claim_ids=[], direction_supporting_claim_ids=[], explanation="客户续约支持业务竞争优势。", explanation_evidence_ids=["E1"]),
        claims=[], materials=[source], claim_aliases={}, evidence_aliases={"E1": "source"},
        requirements=[{"requirement_id": "competition", "dimension": "competition", "requires_analysis": True, "requires_explicit_binding": True}],
    )
    assert not errors
    assert result.explanations[0]["requirement_ids"] == ["competition"]
    assert result.explanations[0]["dimension"] == "competition"


def test_ambiguous_explanation_requires_binding_instead_of_answering_every_dimension():
    source = NormalizedEvidence(source_id="source", task_ids=["a"], kind="document_context", usage="fact", text="业务资料")
    _, errors = _validate_task_selection(_TaskSynthesisSelection(claim_ids=[], direction_supporting_claim_ids=[], explanation="业务资料", explanation_evidence_ids=["E1"]),
        claims=[], materials=[source], claim_aliases={}, evidence_aliases={"E1": "source"},
        requirements=[{"requirement_id": dimension, "dimension": dimension, "requires_analysis": True, "requires_explicit_binding": True}
            for dimension in ["business_model", "competition"]])
    assert errors[0]["code"] == "task_synthesis_requirement_binding_missing"


def test_official_filing_body_without_section_labels_is_read_material_not_index():
    from backend.graph.synthesis.requirement_validation import _supports_dimension, evidence_is_document_index

    evidence = NormalizedEvidence(source_id="official", task_ids=["a"], kind="filing_context",
        usage="fact", text="实际业务及竞争正文", url="https://www.sec.gov/Archives/edgar/data/1/report.htm",
        structured_data={"content_read": True, "content_sections": {}, "document_body": "实际业务及竞争正文"})
    assert not evidence_is_document_index(evidence)
    assert _supports_dimension(evidence, "business_model")
    assert _supports_dimension(evidence, "competition")


def test_confirmed_report_contract_does_not_add_unrequested_enrichment(monkeypatch):
    from types import SimpleNamespace
    from backend.graph.planning import report_mode

    monkeypatch.setattr(report_mode, "_append_report_ticker_enrichment", lambda _ctx: pytest.fail("已确认的报告范围不能扩展"))
    report_mode._append_report_mode_enrichment_steps(SimpleNamespace(
        output_mode="investment_report", ready_tasks=[{"requirements_status": "confirmed"}]))
