"""类型合同、通用证券身份和单次语义入口的关键反例。"""
from __future__ import annotations

import asyncio
from importlib import import_module

import pytest

from backend.config.ticker_mapping import extract_tickers
from backend.graph.nodes.route_request import route_request
from backend.graph.request_compiler import compile_semantic_contract
from backend.graph.request_spec import RequestSpec, UnmappedRequirement
from backend.graph.semantic_requirements import extract_semantic_requirements
from backend.services.run_context import RunContext, run_context_scope


@pytest.mark.parametrize("query,ticker", [("600036 走势如何", "600036.SS"), ("002174 的业务有什么变化", "002174.SZ"),
                                         ("920118 走势如何", "920118.BJ")])
def test_numeric_security_identity_uses_exchange_shape(query, ticker):
    assert extract_tickers(query)["tickers"] == [ticker]


@pytest.mark.asyncio
@pytest.mark.parametrize("query,label,tickers", [("600036 走势如何", "600036", ["600036.SS"]),
                                                 ("未入别名表的公司经营情况如何", "未入别名表的公司", [])])
async def test_unfamiliar_subject_is_interpreted_once_and_can_request_retrieval(monkeypatch, query, label, tickers):
    calls = []
    async def extract(state, _seed):
        calls.append(state["query"])
        return {"route": "research", "subjects": [{"id": "company", "type": "company", "label": label, "tickers": tickers}],
            "requirements": [{"source_text": query, "description": query, "kind": "explanation", "metric": "business_model",
                              "subject_refs": ["company"]}]}, {"status": "confirmed"}

    monkeypatch.setattr(import_module("backend.graph.nodes.route_request"), "extract_semantic_requirements", extract)
    result = await route_request({"query": query, "output_mode": "chat"})
    assert calls == [query] and result["understanding"]["route"] == "research"
    assert result["tasks"] and result["tasks"][0]["required_evidence"]
    assert "direct_answer_request" not in result["artifacts"]
    RequestSpec.model_validate(result["understanding"]["semantic_contract"])


@pytest.mark.asyncio
async def test_extraction_validation_does_not_publish_or_change_run_mode(monkeypatch):
    query = "为 LUMA 形成研究材料"
    raw = {"route": "research", "output_mode": "investment_report", "subjects": [
        {"id": "company", "type": "company", "label": "LUMA", "tickers": ["LUMA"]}],
        "requirements": [{"source_text": query, "description": query, "kind": "explanation", "metric": "business_model",
                          "subject_refs": ["company"]}]}
    async def invoke(*_args, **_kwargs):
        return raw
    monkeypatch.setattr(import_module("backend.graph.semantic_requirements"), "ainvoke_configured_llm", invoke)
    run = RunContext.create(owner="public", entry="chat", budget_seconds=1)
    original_deadline = run.deadline
    with run_context_scope(run):
        semantic, diagnostics = await extract_semantic_requirements({"query": query}, {})
        assert semantic is not None and diagnostics["status"] == "confirmed"
        assert run.entry == "chat" and run.deadline == original_deadline and run.compiled_state is None
        result = compile_semantic_contract({"query": query}, semantic, diagnostics)
        assert run.entry == "investment_report" and run.compiled_state["tasks"] == result["tasks"]


def test_unmapped_metric_and_attribute_preserve_source_without_payload_key():
    query = "LUMA 的量子护城河与未知口径如何"
    semantic = {"route": "research", "subjects": [{"id": "company", "type": "company", "label": "LUMA", "tickers": ["LUMA"]}],
        "requirements": [{"source_text": query, "description": query, "kind": "explanation", "metric": "quantum_moat",
                          "attributes": ["unregistered_property"], "subject_refs": ["company"]}]}
    result = compile_semantic_contract({"query": query}, semantic, {})
    spec = RequestSpec.model_validate(result["understanding"]["semantic_contract"])
    row = spec.requirements[0]
    assert isinstance(row, UnmappedRequirement)
    assert row.metric == "unknown" and row.metric_text == "quantum_moat"
    assert row.source_text == query and row.attributes == []
    assert row.unmapped_qualifiers[0].name == "unregistered_property"
    assert row.capability_status == "unsupported"


def test_direct_route_cannot_skip_a_real_quote_requirement():
    query = "LUMA 当前报价"
    semantic = {"route": "direct", "subjects": [{"id": "company", "type": "company", "label": "LUMA", "tickers": ["LUMA"]}],
        "requirements": [{"source_text": query, "description": query, "kind": "fact_attribute", "metric": "quote", "subject_refs": ["company"]}]}
    with pytest.raises(ValueError, match="request_direct_route_retrieval_conflict"):
        compile_semantic_contract({"query": query}, semantic, {})


def test_compiler_rejects_identity_borrowed_only_from_unscoped_workspace():
    query = "这只股票最新股价"
    semantic = {"route": "research", "subjects": [{"id": "stock", "type": "company", "label": "AAPL", "tickers": ["AAPL"]}],
        "requirements": [{"source_text": query, "description": query, "kind": "fact_attribute", "metric": "quote", "subject_refs": ["stock"]}]}
    with pytest.raises(ValueError, match="request_subject_context_unbound"):
        compile_semantic_contract({"query": query}, semantic, {}, input_context={"ui_context": {"active_symbol": "AAPL"}})
    scoped = compile_semantic_contract({"query": query}, semantic, {},
                                      input_context={"ui_context": {"active_symbol": "AAPL", "view": "dashboard"}})
    assert scoped["tasks"][0]["tickers"] == ["AAPL"]


@pytest.mark.asyncio
async def test_unconfirmed_workspace_binding_does_not_execute_the_rule_seed(monkeypatch):
    async def unbound(_state, _seed):
        return None, {"status": "unconfirmed", "validation_code": "request_subject_context_unbound"}
    monkeypatch.setattr(import_module("backend.graph.nodes.route_request"), "extract_semantic_requirements", unbound)
    result = await route_request({"query": "这只股票最新股价", "ui_context": {"active_symbol": "AAPL"}})
    assert result["understanding"]["route"] == "clarify"
    assert result["subject"]["tickers"] == [] and not result["tasks"]
    assert result["understanding"]["semantic_contract"]["status"] == "unconfirmed"
