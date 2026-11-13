# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json

import pytest

from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
from backend.graph.execution.evidence_tools import append_tool_evidence, evidence_contract_metadata
from backend.graph.synthesis.contracts import ClaimValidationResult, TaskSynthesisResult
from backend.graph.synthesis.opinion_readiness import build_opinion_readiness
from backend.graph.synthesis.research_synthesis import normalize_evidence, validate_claims
from backend.graph.synthesis.task_outcomes import TaskDescriptor, TaskOutcome


@pytest.fixture(autouse=True)
def _disable_evidence_network_enrichment(monkeypatch):
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")


def _descriptor() -> TaskDescriptor:
    return TaskDescriptor(
        task_id="t1", title="INTC 研究", priority=20, order_index=0,
        operation="investment_opinion", subject_label="INTC", tickers=["INTC"],
        request_frame_id="frame-1", render_kind="single", render_group_id="frame-1",
        intent_status="ready", required_step_ids=[], required_evidence=[], error_codes=[],
    )


def test_news_selection_metadata_cannot_promote_client_context_to_verified_fact():
    item = {"id": "selected-news", "type": "news", "title": "INTC media opinion",
            "url": "https://www.reuters.com/intc", "snippet": "A media view.", "ts": "2026-10-03",
            "event_quality": {"content_kind": "opinion", "evidence_role": "opinion"}}
    artifacts = {}
    pool, _by_task, _count = normalize_execution_evidence(
        state={"subject": {"subject_type": "news_item", "selection_payload": [item]}},
        plan_ir={"steps": []}, artifacts=artifacts,
    )
    row = next(row for row in pool if row.get("id") == "selected-news")
    assert row["usage"] == "raw"
    assert row["meta"]["verification"] == "user_provided_selection"
    assert row["meta"]["event_quality"]["content_kind"] == "opinion"


def _execute_and_normalize(steps: list[dict], outputs: dict):
    artifacts = {"step_results": {key: {"output": value} for key, value in outputs.items()}}
    normalize_execution_evidence(state={"subject": {}}, plan_ir={"steps": steps}, artifacts=artifacts)
    agent_outputs = {
        step["id"]: outputs[step["id"]] for step in steps if step["kind"] == "agent"
    }
    normalized = normalize_evidence(
        task_descriptors=[_descriptor()], plan_steps=steps, agent_outputs=agent_outputs,
        raw_evidence_by_task=artifacts["evidence_by_task"],
    )
    return artifacts, normalized


@pytest.mark.parametrize("quote", [
    "INTC Current Price: $40.25 | Provider: twelve_data | As of: 2026-10-02T20:00:00Z | Currency: USD",
    {"provider": "twelve_data", "as_of": "2026-10-02T20:00:00Z", "data": {"price": 40.25, "currency": "USD"}},
    json.dumps({"price": 40.25, "source": "twelve_data", "as_of": "2026-10-02T20:00:00Z", "currency": "USD"}),
])
def test_execution_quote_reaches_synthesis_with_price_source_and_time(quote):
    steps = [{"id": "price", "kind": "tool", "name": "get_stock_price", "task_ids": ["t1"]}]
    artifacts, normalized = _execute_and_normalize(steps, {"price": quote})

    row = artifacts["evidence_by_task"]["t1"][0]
    evidence = normalized.evidence_index[row["source_id"]]
    assert evidence.kind == "price_snapshot"
    assert evidence.market_price == 40.25
    assert evidence.as_of == "2026-10-02T20:00:00Z"
    assert evidence.source_name == "twelve_data"
    assert evidence.task_ids == ["t1"]
    assert not normalized.rejected_evidence


def test_quote_without_real_time_does_not_receive_a_fabricated_as_of():
    steps = [{"id": "price", "kind": "tool", "name": "get_stock_price", "task_ids": ["t1"]}]
    _, normalized = _execute_and_normalize(steps, {"price": {"price": 40.25, "source": "fixture"}})

    evidence = next(iter(normalized.evidence_index.values()))
    assert evidence.market_price == 40.25
    assert evidence.as_of is None


@pytest.mark.parametrize("as_of,has_anchor", [("2026-10-02T20:00:00Z", True), (None, False)])
def test_actual_quote_anchor_does_not_bypass_directional_evidence_requirements(as_of, has_anchor):
    steps = [{"id": "price", "kind": "tool", "name": "get_stock_price", "task_ids": ["t1"]}]
    _, normalized = _execute_and_normalize(steps, {"price": {"price": 40.25, "as_of": as_of}})
    outcome = TaskOutcome(
        **_descriptor().model_dump(), status="partial", successful_step_ids=["price"],
        evidence_ids=list(normalized.evidence_index), missing_evidence=[],
    )
    result = TaskSynthesisResult(
        task_id="t1", title="INTC 研究", priority=20, order_index=0,
        request_frame_id="frame-1", render_kind="single", render_group_id="frame-1",
        status="partial", conclusion=None, claim_ids=[], evidence_ids=list(normalized.evidence_index),
        proposed_direction=None, direction_supporting_claim_ids=[], agent_names=[],
        agreements=[], disagreements=[], conflicts=[], risks=[], limitations=[],
        fallback_used=False, error_codes=[],
    )
    readiness = build_opinion_readiness(
        task_outcome=outcome, task_result=result, evidence_normalization=normalized,
        claim_validation=ClaimValidationResult(valid_claims={}, rejected_claims=[], conflicts=[], quality_block_reasons=[]),
    )
    assert (readiness.price_anchor_source_id is not None) is has_anchor
    assert ("missing_price_anchor" not in readiness.reason_codes) is has_anchor
    assert readiness.direction_allowed is False
    assert "unsupported_direction" in readiness.reason_codes


@pytest.mark.parametrize("tool_name,required,expected", [
    ("search", [], "unknown"),
    ("get_authoritative_media_news", [], "unknown"),
    ("get_authoritative_media_news", ["news_context", "macro_context"], "unknown"),
    ("get_authoritative_media_news", ["macro_context"], "macro_context"),
    ("get_authoritative_media_news", ["price_snapshot"], "unknown"),
    ("get_technical_snapshot", [], "technical_snapshot"),
    ("get_sec_company_facts_quarterly", [], "filing_context"),
])
def test_tool_kind_uses_registry_without_guessing_ambiguous_producers(tool_name, required, expected):
    pool = []
    append_tool_evidence(pool, tool_name, "step", {"text": "实际工具结果"}, required_evidence=required)
    if not pool:
        # 新闻工具按其公开 articles 容器接收证据。
        append_tool_evidence(pool, tool_name, "step", {"articles": [{"title": "实际新闻", "snippet": "实际工具结果"}]}, required_evidence=required)
    assert pool[0]["kind"] == expected
    assert pool[0]["source_id"]


def test_agent_native_metadata_and_source_ids_survive_both_normalization_paths():
    text = "带有完整原始信息的风险证据。" * 100
    native = {
        "text": text, "source": "risk_engine", "timestamp": "2026-10-01T20:00:00Z",
        "meta": {"source_id": "agent_source:risk-native", "method": "historical_drawdown", "sample_size": 100},
    }
    output = {"as_of": "2026-10-02T20:00:00Z", "evidence": [native], "raw_claims": [{
        "claim_id": "risk-claim", "task_id": "t1", "agent_name": "risk_agent",
        "text": "历史回撤风险需要控制。", "stance": "risk", "confidence": 0.8,
        "evidence_ids": ["agent_source:risk-native"], "limitations": [],
    }]}
    original = copy.deepcopy(output)
    steps = [{"id": "risk", "kind": "agent", "name": "risk_agent", "task_ids": ["t1"]}]
    artifacts, normalized = _execute_and_normalize(steps, {"risk": output})

    row = artifacts["evidence_by_task"]["t1"][0]
    evidence = normalized.evidence_index["agent_source:risk-native"]
    assert row["meta"] == native["meta"]
    assert row["text"] == text
    assert evidence.text == text
    assert evidence.as_of == native["timestamp"]
    assert evidence.kind == "risk_profile"
    assert evidence.agent_name == "risk_agent"
    assert not normalized.quality_block_reasons
    assert not normalized.rejected_evidence
    assert output == original
    claims = validate_claims(
        run_id="run-fixture", task_descriptors=[_descriptor()], plan_steps=steps,
        agent_outputs={"risk": output}, evidence_normalization=normalized,
    )
    assert claims.valid_claims["risk-claim"].dimension == "risk"
    assert not claims.rejected_claims


def test_explicit_evidence_kind_and_metadata_take_precedence_over_agent_defaults():
    native = {"source_id": "source:filing", "kind": "filing_context", "text": "公司公告正文。",
              "meta": {"source_id": "meta-source", "as_of": "2026-09-30", "evidence_kind": "technical_snapshot"}}
    steps = [{"id": "fundamental", "kind": "agent", "name": "fundamental_agent", "task_ids": ["t1"]}]
    _, normalized = _execute_and_normalize(steps, {"fundamental": {"as_of": "2026-10-02", "evidence": [native]}})

    evidence = normalized.evidence_index["source:filing"]
    assert evidence.kind == "filing_context"
    assert evidence.as_of == "2026-09-30"
    assert not normalized.quality_block_reasons


@pytest.mark.parametrize("field", ["text", "snippet", "summary"])
def test_agent_native_text_projections_remain_identical_for_long_evidence(field):
    text = "完整且不应被展示截断改变的证据。" * 100
    steps = [{"id": "risk", "kind": "agent", "name": "risk_agent", "task_ids": ["t1"]}]
    _, normalized = _execute_and_normalize(steps, {"risk": {
        "as_of": "2026-10-02", "evidence": [{"source_id": "source:long", field: text}],
    }})
    assert normalized.evidence_index["source:long"].text == text
    assert not normalized.quality_block_reasons
    assert not normalized.rejected_evidence


def test_explicit_unknown_is_not_upgraded_by_required_evidence():
    steps = [{"id": "risk", "kind": "agent", "name": "risk_agent", "task_ids": ["t1"],
              "inputs": {"required_evidence": ["risk_profile"]}}]
    _, normalized = _execute_and_normalize(steps, {"risk": {"evidence": [{
        "source_id": "source:unknown", "kind": "unknown", "text": "证据类型尚未确认。",
    }]}})
    assert normalized.evidence_index["source:unknown"].kind == "unknown"


def test_agent_summary_does_not_create_directional_claims():
    steps = [{"id": "fundamental", "kind": "agent", "name": "fundamental_agent", "task_ids": ["t1"]}]
    output = {"summary": "普通研究摘要。"}
    _, normalized = _execute_and_normalize(steps, {"fundamental": output})
    claims = validate_claims(
        run_id="run-fixture", task_descriptors=[_descriptor()], plan_steps=steps,
        agent_outputs={"fundamental": output}, evidence_normalization=normalized,
    )
    assert not claims.valid_claims


def test_metadata_adapter_does_not_mutate_original_meta():
    raw = {"id": "evidence-id", "text": "原始证据。", "meta": {"source_id": "native-id", "custom": {"value": 1}}}
    original = copy.deepcopy(raw)
    adapted = evidence_contract_metadata(raw, producer_name="risk_agent", producer_kind="agent")
    adapted["meta"]["new_field"] = True
    assert raw == original
    assert adapted["source_id"] == "native-id"


@pytest.mark.parametrize("quality_location", ["event_quality", "meta"])
def test_news_updates_keep_event_identity_metadata_and_original_row(quality_location):
    rows = []
    for event_id, published, role in [("old", "2026-09-01", "historical_news"), ("new", "2026-10-02", "discovery")]:
        quality = {"event_id": event_id, "published_at": published, "evidence_role": role}
        row = {"title": f"Intel product update {event_id}", "snippet": f"Intel original {event_id}",
               "url": "https://example.invalid/rolling-news", "published_at": published,
               "published_at_precision": "date", "retrieval_kind": "search_snippet",
               "supporting_reports": [{"url": "https://example.invalid/source", "published_at": published}]}
        row[quality_location] = quality if quality_location == "event_quality" else {"event_quality": quality}
        rows.append(row)
    original = copy.deepcopy(rows)
    steps = [{"id": "news", "kind": "tool", "name": "get_company_news", "task_ids": ["t1"],
              "inputs": {"ticker": "INTC"}, "evidence_kinds": ["news_context"]}]
    artifacts, normalized = _execute_and_normalize(steps, {"news": rows})

    assert len(artifacts["evidence_pool"]) == 2
    assert len(normalized.evidence_index) == 2
    for evidence in normalized.evidence_index.values():
        quality = evidence.metadata["event_quality"]
        source_row = next(row for row in rows if row["published_at"] == quality["published_at"])
        assert evidence.usage == "raw"
        assert evidence.structured_data["snippet"] == source_row["snippet"]
        assert evidence.structured_data["published_at_precision"] == "date"
        assert evidence.structured_data["retrieval_kind"] == "search_snippet"
        assert evidence.structured_data["supporting_reports"] == source_row["supporting_reports"]
    assert rows == original


def test_shared_financial_url_keeps_distinct_quarters_and_metrics():
    rows = [
        {"source_id": "q1-revenue", "task_ids": ["t1"], "url": "https://example.invalid/financials",
         "kind": "filing_context", "text": "第一季度营收。", "meta": {"metric_key": "revenue", "period_start": "2026-01-01", "period_end": "2026-03-31"}},
        {"source_id": "q2-revenue", "task_ids": ["t1"], "url": "https://example.invalid/financials",
         "kind": "filing_context", "text": "第二季度营收。", "meta": {"metric_key": "revenue", "period_start": "2026-04-01", "period_end": "2026-06-30"}},
        {"source_id": "q1-profit", "task_ids": ["t1"], "url": "https://example.invalid/financials",
         "kind": "filing_context", "text": "第一季度净利润。", "meta": {"metric_key": "net_income", "period_start": "2026-01-01", "period_end": "2026-03-31"}},
    ]
    duplicate = {**rows[0], "task_ids": ["t2"]}
    artifacts = {"evidence_pool": [*rows, duplicate]}
    normalized, _, _ = normalize_execution_evidence(state={"subject": {}}, plan_ir={"steps": []}, artifacts=artifacts)
    assert [row["source_id"] for row in normalized] == ["q1-revenue", "q2-revenue", "q1-profit"]
    assert normalized[0]["task_ids"] == ["t1", "t2"]


def test_unqualified_shared_url_preserves_existing_provenance_merge():
    artifacts = {"evidence_pool": [
        {"url": "https://example.invalid/document", "text": "原始材料。", "task_ids": ["t1"], "step_id": "s1"},
        {"url": "https://example.invalid/document", "text": "原始材料。", "task_ids": ["t2"], "step_id": "s2"},
    ]}
    normalized, _, _ = normalize_execution_evidence(state={"subject": {}}, plan_ir={"steps": []}, artifacts=artifacts)
    assert len(normalized) == 1
    assert normalized[0]["task_ids"] == ["t1", "t2"]
    assert normalized[0]["step_ids"] == ["s1", "s2"]


def test_news_company_alias_is_bound_without_a_company_profile_step():
    rows = [{"title": "Apple announces product update", "snippet": "Apple product release.",
             "url": "https://example.invalid/apple", "published_at": "2026-10-02",
             "event_quality": {"event_id": "apple-news", "evidence_role": "reported_news", "subject_match": "headline"}}]
    steps = [{"id": "news", "kind": "tool", "name": "get_company_news", "task_ids": ["t1"],
              "inputs": {"ticker": "AAPL"}, "evidence_kinds": ["news_context"]}]
    artifacts = {"step_results": {"news": {"output": rows}}}
    normalize_execution_evidence(state={"subject": {}}, plan_ir={"steps": steps}, artifacts=artifacts)
    normalized = normalize_evidence(task_descriptors=[_descriptor().model_copy(update={"subject_label": "AAPL", "tickers": ["AAPL"]})],
                                    plan_steps=steps, agent_outputs={"news": rows}, raw_evidence_by_task=artifacts["evidence_by_task"])
    evidence = next(iter(normalized.evidence_index.values()))
    assert evidence.kind == "news_context" and evidence.usage == "fact"
    assert "subject_binding" not in evidence.metadata


def test_same_news_article_for_two_subjects_has_distinct_supported_source_ids():
    from backend.research.agent_quality_contract import assign_evidence_source_ids

    outputs = {}
    steps = []
    for step_id, subject in [("hk-news", "0700.HK"), ("us-news", "TCEHY")]:
        evidence = {"text": "Nike and G7 shared market news.", "source": "Reuters",
                    "url": "https://example.invalid/shared-news", "timestamp": "2026-10-02",
                    "kind": "news_context", "meta": {"subject": subject,
                    "event_quality": {"event_id": "shared-market-event", "published_at": "2026-10-02", "evidence_role": "discovery"}}}
        assign_evidence_source_ids([evidence], agent_name="news_agent")
        outputs[step_id] = {"evidence": [evidence]}
        steps.append({"id": step_id, "kind": "agent", "name": "news_agent", "task_ids": ["t1"], "inputs": {"ticker": subject}})

    artifacts, normalized = _execute_and_normalize(steps, outputs)
    assert len(artifacts["evidence_pool"]) == 2
    assert len(normalized.evidence_index) == 2
    assert {evidence.subject for evidence in normalized.evidence_index.values()} == {"0700.HK", "TCEHY"}
    assert not normalized.quality_block_reasons and not normalized.rejected_evidence


@pytest.mark.parametrize("agent_name,source,timestamp,meta", [
    ("technical_agent", "market_sentiment", "2026-10-02", {}),
    ("macro_agent", "FRED", "2026-09-01", {"indicator_key": "fed_rate", "period_end": "2026-09-01", "unit": "%"}),
    ("macro_agent", "CNN Fear & Greed", None, {}),
])
def test_global_evidence_keeps_shared_identity_without_company_or_agent_time(agent_name, source, timestamp, meta):
    native = {"text": "全市场原始观测。", "source": source, "timestamp": timestamp,
              "meta": {**meta, "source_id": "agent_source:global-fixture"}}
    extra = {"text": "AMD 公司证据。", "source": "fixture", "kind": "risk_profile",
             "meta": {"source_id": "agent_source:amd-extra", "subject": "AMD"}}
    steps = [
        {"id": "nvda", "kind": "agent", "name": agent_name, "task_ids": ["t1"], "inputs": {"ticker": "NVDA"}},
        {"id": "amd", "kind": "agent", "name": agent_name, "task_ids": ["t2"], "inputs": {"ticker": "AMD"}},
    ]
    outputs = {"nvda": {"as_of": "2026-10-03T01:00:00Z", "evidence": [copy.deepcopy(native)]},
               "amd": {"as_of": "2026-10-03T02:00:00Z", "evidence": [extra, copy.deepcopy(native)]}}
    artifacts = {"step_results": {key: {"output": value} for key, value in outputs.items()}}
    normalize_execution_evidence(state={"subject": {}}, plan_ir={"steps": steps}, artifacts=artifacts)
    descriptors = [_descriptor().model_copy(update={"subject_label": "NVDA", "tickers": ["NVDA"]}),
                   _descriptor().model_copy(update={"task_id": "t2", "subject_label": "AMD", "tickers": ["AMD"]})]
    normalized = normalize_evidence(task_descriptors=descriptors, plan_steps=steps,
                                    agent_outputs=outputs, raw_evidence_by_task=artifacts["evidence_by_task"])
    shared = normalized.evidence_index["agent_source:global-fixture"]
    assert shared.subject is None and shared.as_of == timestamp
    assert shared.task_ids == ["t1", "t2"]
    assert not normalized.rejected_evidence and not normalized.quality_block_reasons


def test_search_failure_is_diagnostic_without_document_evidence():
    steps = [{"id": "search", "kind": "tool", "name": "search", "task_ids": ["t1"], "evidence_kinds": ["document_context"]}]
    artifacts, normalized = _execute_and_normalize(steps, {"search": "Search error: 所有搜索源均失败，无法获取搜索结果。"})
    assert not artifacts["evidence_pool"] and not normalized.evidence_index
    assert artifacts["tool_diagnostics"][0]["step_id"] == "search"
