# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib

import pytest

from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
from backend.graph.nodes.analyze import analyze
from backend.graph.nodes.render_node import render_node


@pytest.fixture(autouse=True)
def _no_external_enrichment(monkeypatch):
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")


def _state(operation, tool, output, evidence_kind, *, subject="NVDA", dimensions=None):
    task = {"id": "task", "title": "本轮研究", "subject_type": "company", "subject_label": subject, "tickers": [subject], "operation": {"name": operation}, "priority": 0, "order_index": 0, "request_frame_id": "frame", "render_group_id": "frame", "render_kind": "single", "required_evidence": [evidence_kind], "required_step_ids": ["step"]}
    step = {"id": "step", "kind": "tool", "name": tool, "task_ids": ["task"], "inputs": {"ticker": subject}, "evidence_kinds": [evidence_kind], "subject_tickers": [subject]}
    state = {"query": "已编译的请求", "understanding": {"route": "research"}, "operation": {"name": operation}, "output_mode": "chat", "subject": {"subject_type": "company", "tickers": [subject]}, "tasks": [task], "plan_ir": {"tasks": [task], "steps": [step]}, "intent_contract": {"render_intent": {"dimensions": dimensions or []}}, "artifacts": {"step_results": {"step": {"output": output}}}, "trace": {}}
    normalize_execution_evidence(state=state, plan_ir=state["plan_ir"], artifacts=state["artifacts"])
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,tool,output,kind,expected", [
    ("price", "get_stock_price", {"price": 140.5, "currency": "USD", "as_of": "2026-10-02T20:00:00Z"}, "price_snapshot", "140.5 USD"),
    ("technical", "get_technical_snapshot", {"ticker": "NVDA", "rsi14": 72, "ma20": 140, "as_of": "2026-10-02"}, "technical_snapshot", "RSI(14) 72"),
    ("macro_brief", "get_official_macro_releases", {"releases": [{"title": "FOMC 决议", "snippet": "目标利率区间维持在 3.75-4.00%。", "published_date": "2026-10-02", "source": "Federal Reserve", "url": "https://example.invalid/fomc"}]}, "macro_context", "3.75-4.00%"),
])
async def test_real_analyze_entry_keeps_fact_tasks_zero_llm_and_consumes_one_result(monkeypatch, operation, tool, output, kind, expected):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    calls = []

    async def forbidden(**kwargs):
        calls.append(kwargs)
        raise AssertionError("事实短答不应调用供应商")

    monkeypatch.setattr(module, "_invoke_structured", forbidden)
    state = _state(operation, tool, output, kind)
    result = await analyze(state)
    assert "research_result" in result["artifacts"]
    rendered = render_node({**state, **result})
    assert expected in rendered["artifacts"]["draft_markdown"]
    assert not calls
    assert result["trace"]["analysis"]["llm_calls"] == 0


@pytest.mark.asyncio
async def test_verified_business_material_can_form_traceable_explanation_without_native_claims(monkeypatch):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    observed = []

    async def select(**kwargs):
        observed.append(kwargs)
        assert "business_model" in kwargs["prompt"] and "competition" in kwargs["prompt"]
        return kwargs["schema"].model_validate({"claim_ids": [], "conclusion_claim_id": None, "proposed_direction": None, "direction_supporting_claim_ids": [], "fact_ids": ["get_company_info:step"], "explanation": "公司的业务依赖数据中心客户；产品迭代与竞争会影响需求兑现，需结合利润率和客户投入跟踪。", "explanation_evidence_ids": ["get_company_info:step"]})

    monkeypatch.setattr(module, "_invoke_structured", select)
    state = _state("qa", "get_company_info", {"ticker": "NVDA", "description": "公司经营数据中心芯片业务，面临产品迭代和市场竞争。", "profitMargins": 0.5}, "company_profile", dimensions=["business_model", "competition"])
    result = await analyze(state)
    rendered = render_node({**state, **result})
    markdown = rendered["artifacts"]["draft_markdown"]
    assert len(observed) == 1
    assert "公司的业务依赖数据中心客户" in markdown
    assert "**业务与商业模式**" in markdown and "**竞争格局**" in markdown
    claim = result["artifacts"]["research_result"]["claim_index"]["synthesis:task:explanation"]
    assert claim["evidence_ids"] == ["get_company_info:step"] and claim["directional"] is False
    assert "synthesis:task:explanation" not in markdown


@pytest.mark.asyncio
async def test_unbound_numeric_explanation_is_rejected_with_reason_and_keeps_real_facts(monkeypatch):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")

    async def select(**kwargs):
        return kwargs["schema"].model_validate({"claim_ids": [], "conclusion_claim_id": None, "proposed_direction": None, "direction_supporting_claim_ids": [], "explanation": "利润率达到 999%，因此需求一定会增长。", "explanation_evidence_ids": ["get_company_info:step"]})

    monkeypatch.setattr(module, "_invoke_structured", select)
    state = _state("qa", "get_company_info", {"ticker": "NVDA", "profitMargins": 0.5}, "company_profile")
    result = await analyze(state)
    task = result["artifacts"]["research_result"]["task_results"][0]
    rendered = render_node({**state, **result})
    assert "structured_selection_invalid" in task["error_codes"]
    assert "999" not in rendered["artifacts"]["draft_markdown"]
    assert "净利率：50%" in rendered["artifacts"]["draft_markdown"]


@pytest.mark.asyncio
async def test_analysis_call_counts_use_observed_attempts_including_failure(monkeypatch):
    module = importlib.import_module("backend.graph.nodes.analyze")

    class Meter:
        calls = 0
        def summary(self):
            return {"llm_token_calls": self.calls, "failed_llm_calls": int(self.calls > 0), "usage_by_attribution": [{"calls": self.calls}]}
    meter = Meter()

    async def synthesize(state):
        meter.calls = 2
        return {"artifacts": {}, "trace": state["trace"]}

    monkeypatch.setattr(module, "get_token_accumulator", lambda: meter)
    monkeypatch.setattr(module, "synthesize", synthesize)
    result = await module.analyze({"understanding": {"route": "research"}, "operation": {"name": "qa"}, "trace": {}})
    assert result["trace"]["analysis"]["business_llm_calls"] == 2
    assert result["trace"]["analysis"]["failed_llm_calls"] == 1
