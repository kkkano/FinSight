"""独立验收暴露的引用、逐任务分析和需求完整性回归。"""
from __future__ import annotations

import importlib

import pytest
from langchain_core.messages import AIMessage

from backend.graph.nodes.analyze import _needs_research_analyst
from backend.graph.synthesis.analysis_requirements import analysis_task_modes
from backend.graph.synthesis.contracts import ClaimValidationResult, EvidenceNormalizationResult, NormalizedEvidence
from backend.graph.synthesis.research_synthesis import synthesize_task_results
from backend.graph.synthesis.task_outcomes import TaskOutcome
from backend.services.llm_retry import LLMCallContext


def _evidence(source_id="stable:filing:2026:business", **kwargs):
    return NormalizedEvidence(**{
        "source_id": source_id, "task_ids": ["task"], "kind": "company_profile",
        "usage": "fact", "subject": "CRM", "currency": "USD", "as_of": "2026-10-02",
        "period_start": "2026-05-01", "period_end": "2026-07-31",
        "text": "公司的业务收入依赖企业订阅，续约和产品竞争会影响现金流。",
        "structured_data": {"description": "企业订阅服务。"}, **kwargs,
    })


def _outcome(operation="qa"):
    return TaskOutcome(
        task_id="task", title="公司研究", priority=0, order_index=0,
        operation=operation, subject_label="CRM", tickers=["CRM"], request_frame_id="frame",
        render_kind="single", render_group_id="frame", intent_status="ready",
        required_step_ids=["step"], required_evidence=[], error_codes=[],
        status="answered", successful_step_ids=["step"], evidence_ids=[], missing_evidence=[],
    )


async def _run(monkeypatch, replies, *, rows=None, requirements=None, attempts=2, outcome=None):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    rows = rows or [_evidence()]
    normalization = EvidenceNormalizationResult(
        evidence_by_task={"task": rows}, evidence_index={item.source_id: item for item in rows},
        rejected_evidence=[], quality_block_reasons=[],
    )
    validation = ClaimValidationResult(valid_claims={}, rejected_claims=[], conflicts=[], quality_block_reasons=[])
    context = LLMCallContext.create(stage="synthesize", max_provider_attempts=attempts)
    calls = []

    async def invoke(**kwargs):
        calls.append(kwargs)
        kwargs["context"].budget.reserve_provider_attempt()
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return kwargs["schema"].model_validate({"claim_ids": [], "direction_supporting_claim_ids": [], **reply})

    monkeypatch.setattr(module, "_invoke_structured", invoke)
    results = await synthesize_task_results(
        task_outcomes=[outcome or _outcome()], findings=[], claim_validation=validation,
        evidence_normalization=normalization,
        llm_call_context_factory=lambda _: context if replies else None,
        requested_dimensions_by_task={"task": ["business_model", "competition", "fundamental_quality"]},
        answer_requirements_by_task={"task": requirements or []},
    )
    return results[0], validation, calls, context


@pytest.mark.asyncio
async def test_task_local_evidence_alias_preserves_source_period_currency_and_explanation(monkeypatch):
    result, claims, calls, _ = await _run(monkeypatch, [{
        "fact_ids": ["E1"], "explanations": [{"text": "企业续约表现会影响经营现金流的稳定性。", "evidence_ids": ["E1"], "dimension": "business_model"}],
    }])
    claim = claims.valid_claims[result.claim_ids[0]]
    assert claim.evidence_ids == ["stable:filing:2026:business"]
    assert result.selected_fact_ids == ["stable:filing:2026:business"]
    assert result.status == "answered"
    assert "2026-07-31" in calls[0]["prompt"] and '"currency": "USD"' in calls[0]["prompt"]
    assert "stable:filing:2026:business" not in calls[0]["prompt"]


@pytest.mark.asyncio
async def test_bad_fact_reference_does_not_discard_valid_explanation_or_accept_cross_task_source(monkeypatch):
    result, claims, _, _ = await _run(monkeypatch, [{
        "fact_ids": ["another-task:source"],
        "explanations": [
            {"text": "企业续约表现影响现金流稳定性。", "evidence_ids": ["E1"]},
            {"text": "其它公司的材料证明竞争占优。", "evidence_ids": ["another-task:source"]},
        ],
    }], attempts=1)
    assert result.conclusion == "企业续约表现影响现金流稳定性。"
    assert len(claims.valid_claims) == 1
    assert result.status == "partial"
    assert "task_synthesis_unknown_evidence_id" in result.error_codes
    assert result.synthesis_validation["repair_attempts"] == 0


@pytest.mark.asyncio
async def test_one_reference_repair_reuses_attempt_budget_and_retains_earlier_valid_paragraph(monkeypatch):
    result, claims, calls, context = await _run(monkeypatch, [
        {"explanations": [
            {"text": "企业续约影响收入稳定性。", "evidence_ids": ["E1"]},
            {"text": "竞争会影响现金流。", "evidence_ids": ["E404"]},
        ]},
        {"explanations": [{"text": "竞争会影响现金流。", "evidence_ids": ["E1"]}]},
    ])
    assert len(calls) == 2 and context.budget.remaining == 0
    assert calls[0]["context"] is calls[1]["context"]
    assert "task_synthesis_unknown_evidence_id" in calls[1]["prompt"]
    assert result.conclusion == "企业续约影响收入稳定性。\n竞争会影响现金流。"
    assert len(claims.valid_claims) == 2
    assert not result.fallback_used
    assert result.synthesis_validation["initial_errors"] and not result.synthesis_validation["remaining_errors"]


@pytest.mark.asyncio
async def test_failed_reference_repair_keeps_legal_explanation_and_rejects_unbound_number(monkeypatch):
    result, claims, calls, _ = await _run(monkeypatch, [
        {"explanations": [
            {"text": "续约有助于收入稳定。", "evidence_ids": ["E1"]},
            {"text": "收入增长 999%。", "evidence_ids": ["E1"]},
        ]},
        TimeoutError("provider timeout"),
    ])
    assert len(calls) == 2 and len(claims.valid_claims) == 1
    assert "999" not in result.conclusion
    assert "explanation_contains_unbound_number" in result.error_codes
    assert "llm_timeout" in result.error_codes


@pytest.mark.parametrize("operation", ["valuation_sanity", "qa", "investment_opinion"])
def test_analysis_selection_uses_every_task_and_keeps_quote_deterministic(operation):
    state = {"operation": {"name": "fetch"}, "tasks": [
        {"id": "quote", "operation": {"name": "price"}},
        {"id": "research", "operation": {"name": operation}},
    ]}
    assert _needs_research_analyst(state)
    assert analysis_task_modes(state) == {"quote": "deterministic", "research": "research"}


def test_explicit_macro_explanation_requirement_enables_analysis_without_financial_evidence_kind():
    state = {"operation": {"name": "macro_brief"}, "tasks": [{
        "id": "macro", "operation": {"name": "macro_brief"}, "required_evidence": ["macro_context"],
        "answer_requirements": [{"requirement_id": "macro:mechanism", "kind": "explanation", "requires_analysis": True}],
    }]}
    assert analysis_task_modes(state) == {"macro": "research"}


@pytest.mark.asyncio
async def test_quote_cannot_be_complete_when_requested_market_session_is_missing(monkeypatch):
    result, _, _, _ = await _run(monkeypatch, [], rows=[_evidence(kind="price_snapshot", market_price=200, text="CRM 200 USD。")], requirements=[{
        "requirement_id": "task:quote", "kind": "fact_attribute", "dimension": "price",
        "description": "报价的币种、来源时间与盘后属性", "evidence_kinds": ["price_snapshot"],
        "requires_analysis": False, "attributes": ["currency", "source_timestamp", "market_session"],
    }])
    assert result.status == "partial"
    assert result.requirement_results[0]["reason"] == "missing_attribute:market_session"
    assert result.missing_requirements[0]["description"] == "报价的币种、来源时间与盘后属性"


@pytest.mark.asyncio
async def test_cited_disclosure_index_does_not_satisfy_business_explanation(monkeypatch):
    result, _, _, _ = await _run(monkeypatch, [{"explanations": [{
        "text": "订阅业务依赖持续续约。", "evidence_ids": ["E1"], "dimension": "business_model", "requirement_ids": ["task:business"],
    }]}], rows=[_evidence(kind="filing_context", text="SEC EDGAR 10-Q filing. Filed: 2026-10-02. Quarterly report", structured_data={})], requirements=[{
        "requirement_id": "task:business", "kind": "explanation", "dimension": "business_model",
        "description": "解释商业模式", "evidence_kinds": ["filing_context"], "requires_analysis": True,
    }])
    assert result.status == "partial"
    assert result.requirement_results[0]["status"] == "missing"
    assert "requirement_evidence_missing" in result.requirement_results[0]["reason"]


@pytest.mark.asyncio
async def test_verified_business_material_and_bound_explanation_satisfy_only_the_answered_requirement(monkeypatch):
    requirements = [{"requirement_id": f"task:{dimension}", "kind": "explanation", "dimension": dimension,
                     "evidence_kinds": ["company_profile"], "requires_analysis": True} for dimension in ("business_model", "competition")]
    result, _, _, _ = await _run(monkeypatch, [{"explanations": [{
        "text": "企业续约有助于收入稳定。", "evidence_ids": ["E1"], "dimension": "business_model", "requirement_ids": ["task:business_model"],
    }]}], requirements=requirements)
    assert [item["status"] for item in result.requirement_results] == ["answered", "missing"]
    assert result.status == "partial"


@pytest.mark.asyncio
async def test_thirty_day_calendar_cannot_complete_ninety_day_requirement(monkeypatch):
    result, _, _, _ = await _run(monkeypatch, [], rows=[_evidence(kind="event_calendar", metadata={"coverage_window": {"days_ahead": 30}})], requirements=[{
        "requirement_id": "task:calendar", "kind": "event_window", "dimension": "catalysts",
        "evidence_kinds": ["event_calendar"], "requires_analysis": False,
        "time_window": {"direction": "future", "value": 90, "unit": "days"},
    }])
    assert result.status == "partial"
    assert result.requirement_results[0]["reason"] == "requirement_time_window_unverified"


@pytest.mark.asyncio
async def test_concept_direct_answer_uses_final_model_without_research_or_tools(monkeypatch):
    module = importlib.import_module("backend.graph.nodes.analyze")
    calls = []

    async def invoke(messages, **kwargs):
        calls.append((messages, kwargs))
        kwargs["context"].budget.reserve_provider_attempt()
        return AIMessage(content="虚构例子：净利润 100，折旧 20，资本支出 50，自由现金流为 70。")

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("概念直答不应进入研究合成")

    monkeypatch.setattr(module, "ainvoke_configured_llm", invoke)
    monkeypatch.setattr(module, "synthesize", forbidden)
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MAX_TOKENS", "65536")
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_TIMEOUT_SEC", "1200")
    result = await module.analyze({"understanding": {"route": "direct"}, "query": "用虚构数字解释现金流和净利润，不查行情。", "artifacts": {"direct_answer_request": {}, "draft_markdown": ""}})
    assert len(calls) == 1 and "虚构例子" in result["artifacts"]["draft_markdown"]
    assert result["artifacts"]["chat_responded"] is True
    assert result["trace"]["analysis"]["business_llm_calls"] == 1
    assert calls[0][1]["max_tokens"] == 65536 and calls[0][1]["request_timeout"] == 1200


@pytest.mark.asyncio
async def test_comparison_cannot_be_complete_with_different_cash_flow_periods(monkeypatch):
    outcome = _outcome("compare").model_copy(update={"render_kind": "compare", "tickers": ["V", "MA"]})
    result, _, _, _ = await _run(monkeypatch, [{"explanations": [{
        "text": "两家的现金流需要按相同期间进一步比较。", "evidence_ids": ["E1", "E2"], "dimension": "fundamental_quality", "requirement_ids": ["task:cashflow"],
    }]}], outcome=outcome, rows=[
        _evidence("source:MA", subject="MA", kind="fundamental_snapshot", period_start="2026-04-01", period_end="2026-06-30"),
        _evidence("source:V", subject="V", kind="fundamental_snapshot", period_start="2026-07-01", period_end="2026-09-30"),
    ], requirements=[{"requirement_id": "task:cashflow", "kind": "comparison", "dimension": "fundamental_quality", "requires_analysis": True, "evidence_kinds": ["fundamental_snapshot"]}])
    assert result.status == "partial"
    assert result.requirement_results[0]["reason"] == "comparison_period_or_currency_unverified"
