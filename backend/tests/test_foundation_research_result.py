# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from backend.graph.nodes.render_node import render_node
from backend.graph.renderers.research_report import render_research_report
from backend.graph.synthesis.contracts import Claim, NormalizedEvidence, ReportSynthesisDraft, TaskSynthesisResult
from backend.graph.synthesis.research_synthesis import _build_conflicts, clean_research_text


def _claim(claim_id: str, stance: str, **context):
    return Claim(claim_id=claim_id, task_id="task", agent_name="technical_agent", text="有来源支持的判断。", stance=stance, dimension="technical", confidence=0.8, evidence_ids=["source"], limitations=[], **context)


@pytest.mark.parametrize("changed", [{"subject": "AMD"}, {"horizon": "1d"}, {"scenario": "stress"}, {"metric": "rsi"}])
def test_different_entities_horizons_metrics_or_scenarios_do_not_form_conflicts(changed):
    context = {"subject": "NVDA", "metric": "trend", "horizon": "12m", "scenario": "base"}
    left = _claim("left", "bull", **context)
    right = _claim("right", "bear", **{**context, **changed})
    assert _build_conflicts({left.claim_id: left, right.claim_id: right}) == []


def test_unknown_semantic_context_and_neutral_stance_do_not_create_major_conflicts():
    claims = {"left": _claim("left", "bull"), "right": _claim("right", "bear")}
    assert _build_conflicts(claims) == []
    context = {"subject": "NVDA", "metric": "trend", "horizon": "12m", "scenario": "base"}
    assert _build_conflicts({"left": _claim("left", "bull", **context), "right": _claim("right", "neutral", **context)}) == []


def test_explicit_opposite_claims_on_the_same_proposition_form_material_conflict():
    context = {"subject": "NVDA", "metric": "trend", "horizon": "12m", "scenario": "base"}
    conflicts = _build_conflicts({"left": _claim("left", "bull", **context), "right": _claim("right", "bear", **context)})
    assert len(conflicts) == 1 and conflicts[0].material and conflicts[0].affects_direction


def _draft(evidence, *, missing=None, claims=None):
    claims = claims or {}
    task = TaskSynthesisResult(task_id="task", title="NVDA 技术面", subject="NVDA", operation="technical", priority=0, order_index=0, request_frame_id="frame", render_kind="single", render_group_id="frame", status="partial" if missing else "answered", conclusion=None, claim_ids=list(claims), evidence_ids=[evidence.source_id], fact_ids=[evidence.source_id], proposed_direction=None, direction_supporting_claim_ids=[], agent_names=[], agreements=[], disagreements=[], conflicts=[], risks=[], limitations=[], fallback_used=False, error_codes=[], missing_evidence=missing or [])
    return ReportSynthesisDraft(status=task.status, overall_conclusion=None, task_results=[task], claim_index=claims, evidence_index={evidence.source_id: evidence}, citation_ids=[evidence.source_id], conflicts=[], disagreements=[], risks=[], limitations=[], fallback_used=False)


def test_chat_preserves_real_tool_facts_when_direction_is_unavailable():
    evidence = NormalizedEvidence(source_id="internal-source-uuid", task_ids=["task"], subject="NVDA", kind="technical_snapshot", usage="fact", text="RSI 为 62。", source_name="market_provider", structured_data={"rsi14": 62, "ma20": 120})
    draft = _draft(evidence, missing=["news_context"])
    rendered = render_research_report(draft, output_mode="chat", direction_readiness={"task": {"direction_allowed": False}})
    assert "RSI(14) 62" in rendered.markdown and "MA20 120" in rendered.markdown
    assert "[数据缺失] 新闻与催化剂" in rendered.markdown
    assert "internal-source-uuid" not in rendered.markdown
    assert "technical_agent" not in rendered.markdown


def test_render_node_consumes_canonical_result_and_keeps_facts_in_blocked_report_preview():
    evidence = NormalizedEvidence(source_id="source", task_ids=["task"], subject="NVDA", kind="price_snapshot", usage="fact", text="源报价。", market_price=140.5, currency="USD", as_of="2026-10-02T20:00:00Z")
    draft = _draft(evidence)
    state = {"output_mode": "investment_report", "artifacts": {"research_result": draft.model_dump(), "research_requested_task_ids": ["task"]}}
    rendered = render_node(state)
    assert "140.5 USD" in rendered["artifacts"]["draft_markdown"]
    assert rendered["artifacts"]["quality_blocked"] is True
    assert rendered["artifacts"]["publishable"] is False


def test_search_format_headers_and_route_notes_are_not_research_facts():
    assert clean_research_text("综合搜索结果 (来自 Exa):\n=====\nSearch Results (Exa):") == ""
    assert clean_research_text("无ticker的宏观/主题问题应走宏观研究路径") == ""
    assert clean_research_text("Search Results (Exa):\n公司宣布新产品发布。") == "公司宣布新产品发布。"


def test_fiscal_period_end_and_metric_units_are_displayed_without_calendar_conversion():
    evidence = NormalizedEvidence(source_id="filing", task_ids=["task"], subject="NVDA", kind="filing_context", usage="fact", text="季度事实。", structured_data={"period_ends": ["2026-08-01"], "periods": ["2026Q2"], "revenue": [50.0], "fact_metadata": {"revenue": [{"period_start": "2026-05-03", "period_end": "2026-08-01", "unit": "USD", "frequency": "quarterly"}]}})
    markdown = render_research_report(_draft(evidence)).markdown
    assert "2026-08-01 营收 50 USD" in markdown
    assert "2026-05-03 至 2026-08-01" in markdown
    assert "2026-06-30" not in markdown and "2026Q2" not in markdown


def test_document_body_is_preserved_as_evidence_and_not_repeated_across_dimensions():
    body = "公司通过订阅提供软件，续约需要持续投入服务。" * 1000
    evidence = NormalizedEvidence(source_id="document", task_ids=["task"], subject="NVDA", kind="document_context", usage="fact", text=body,
                                  title="公司年度报告", url="https://example.com/report", structured_data={"content": body})
    draft = _draft(evidence)
    draft.task_results[0].requested_dimensions = ["business_model", "competition"]
    markdown = render_research_report(draft).markdown
    assert body not in markdown
    assert markdown.count("公司年度报告；已读取正文") == 1
    assert draft.evidence_index["document"].structured_data["content"] == body
    assert "对应解释" in markdown
    assert "## 来源" in markdown


def test_document_source_can_support_distinct_analyses_without_repeating_body():
    evidence = NormalizedEvidence(source_id="document", task_ids=["task"], subject="NVDA", kind="document_context", usage="fact", text="经核实的公司披露正文。",
                                  title="公司年度报告", url="https://example.com/report", structured_data={"content": "原始正文。" * 3000})
    claims = {
        dimension: Claim(claim_id=dimension, task_id="task", agent_name="research_analyst", text=text, stance="neutral", dimension="fundamental", metric=dimension,
                         confidence=0.8, evidence_ids=["document"], limitations=[])
        for dimension, text in (("business_model", "订阅收入依赖客户持续采用。"), ("competition", "竞争需要兼顾产品与服务能力。"))
    }
    draft = _draft(evidence, claims=claims)
    draft.task_results[0].requested_dimensions = list(claims)
    markdown = render_research_report(draft).markdown
    assert markdown.count("订阅收入依赖客户持续采用") == 1
    assert markdown.count("竞争需要兼顾产品与服务能力") == 1
    assert "原始正文" not in markdown
    assert "[1]" in markdown
