# -*- coding: utf-8 -*-
from __future__ import annotations

import copy

import pytest

from backend.graph.renderers.content_selection import select_fact_ids
from backend.graph.renderers.research_report import render_research_report
from backend.graph.synthesis.contracts import NormalizedEvidence, ReportSynthesisDraft, TaskSynthesisResult
from backend.graph.synthesis.contracts import Claim


def _fact(source_id, kind, payload, *, subject="INTC", text="来源事实。"):
    return NormalizedEvidence(source_id=source_id, task_ids=["task"], subject=subject, kind=kind, usage="fact", text=text, title=f"来源-{source_id}", url=f"https://example.invalid/{source_id}", as_of="2026-10-03", structured_data=payload)


def _task(**updates):
    return TaskSynthesisResult.model_validate({"task_id": "task", "title": "INTC 研究", "subject": "INTC", "operation": "investment_opinion", "priority": 0, "order_index": 0, "request_frame_id": "frame", "render_kind": "single", "render_group_id": "frame", "status": "answered", "conclusion": None, "claim_ids": [], "evidence_ids": [], "fact_ids": [], "proposed_direction": None, "direction_supporting_claim_ids": [], "agent_names": [], "agreements": [], "disagreements": [], "conflicts": [], "risks": [], "limitations": [], "fallback_used": False, "error_codes": [], **updates})


def _draft(facts, tasks):
    return ReportSynthesisDraft(status="answered", overall_conclusion=None, task_results=tasks, claim_index={}, evidence_index={item.source_id: item for item in facts}, citation_ids=[item.source_id for item in facts], conflicts=[], disagreements=[], risks=[], limitations=[], fallback_used=False)


def test_primary_policy_checks_qualified_facts_and_preserves_real_source_gaps():
    from backend.graph.synthesis.requirement_validation import evaluate_answer_requirements

    primary = _fact("primary", "filing_context", {"value": 100})
    primary.metric, primary.url = "revenue", "https://www.sec.gov/Archives/edgar/data/1/report.htm"
    secondary = _fact("secondary", "filing_context", {"value": 100})
    secondary.metric, secondary.url = "revenue", "https://finance.yahoo.com/quote/INTC/financials/"
    task = _task(status="partial", fact_ids=["primary", "secondary"], requested_subjects=["INTC"])
    requirement = {"requirement_id": "revenue", "metric": "revenue", "kind": "fact_attribute",
        "dimension": "fundamental_quality", "capability_status": "supported", "evidence_kinds": ["filing_context"],
        "constraints": [{"constraint_type": "source_policy", "source_requirement": "primary", "dimension": "fundamental"}]}
    index = {item.source_id: item for item in [primary, secondary]}
    evaluate_answer_requirements(result=task, requirements=[requirement], evidence_index=index, claim_index={}, subjects=["INTC"])
    assert task.status == "answered" and task.requirement_results[0]["evidence_ids"] == ["primary"]
    task.fact_ids, task.status = ["secondary"], "partial"
    evaluate_answer_requirements(result=task, requirements=[requirement], evidence_index=index, claim_index={}, subjects=["INTC"])
    assert task.status != "answered" and "requirement_primary_source_missing" in task.requirement_results[0]["reason"]


def test_raw_discovery_keeps_clickable_source_without_becoming_a_fact():
    article = _fact("article", "news_context", {"title": "Intel analysis"})
    article.usage = "raw"
    article.metadata = {"verification": "discovery_only"}
    draft = _draft([article], [_task(status="partial")])
    draft.citation_ids = []
    text = render_research_report(draft, output_mode="chat").markdown
    assert "仅为检索线索" in text
    assert "](https://example.invalid/article)" in text
    assert "**新闻与催化剂**" not in text
    assert draft.citation_ids == []
    assert draft.evidence_index["article"].usage == "raw"


def test_chat_selects_current_schema_fields_and_keeps_every_requested_dimension():
    facts = [
        _fact("financial", "filing_context", {"period_ends": ["2026-06-27"], "currency": "USD", "revenue": [16_128_000_000.0], "net_income": [-11_033_000_000.0], "operating_cash_flow": [None], "gross_profit": [6_509_000_000.0], "fact_metadata": {"revenue": [{"period_start": "2026-03-29", "period_end": "2026-06-27", "unit": "USD", "frequency": "quarterly"}]}}),
        _fact("technical", "technical_snapshot", {"rsi14": 72.193, "ma20": 111.635, "macd": 6.0886, "macd_signal": 5.6532}),
        _fact("risk", "risk_profile", {"factor_beta": {"market": 2.9451, "growth": 2.4804}, "max_drawdown": -0.419}),
        _fact("calendar", "event_calendar", {"days_ahead": 30, "earnings_events": [{"date": "2026-10-22", "title": "Earnings Date"}, {"date": "2026-10-22", "title": "Earnings Date"}], "macro_events": [{"date": "2026-10-07", "title": "FOMC Minutes"}, {"date": "2026-10-14", "title": "CPI"}, {"date": "2026-10-28", "title": "第四个未展示事件"}]}),
        _fact("news", "news_context", {"title": "Intel 新产品进展", "snippet": "这段长新闻原文仅保留在完整研究结果。"}),
        _fact("optional-profile", "company_profile", {"name": "Intel", "marketCap": 10_000_000, "currency": "USD"}),
    ]
    ids = [item.source_id for item in facts]
    task = _task(fact_ids=ids, evidence_ids=ids, requested_dimensions=["fundamental_quality", "technical_quality", "news_catalysts", "risk_level"])
    draft = _draft(facts, [task])
    original = copy.deepcopy(draft.model_dump())
    markdown = render_research_report(draft, output_mode="chat").markdown
    for term in ("营收 161.28 亿 USD", "净利润 -110.33 亿 USD", "经营现金流没有可验证", "RSI(14) 72.19", "因子 beta", "2026-10-22", "Intel 新产品进展"):
        assert term in markdown
    assert "毛利" not in markdown and "第四个未展示事件" not in markdown
    assert markdown.count("2026-10-22") == 1
    assert "optional-profile" not in markdown
    assert "长新闻原文" not in markdown
    assert draft.model_dump() == original
    assert "毛利" in render_research_report(draft).markdown


def test_chat_model_fact_selection_is_prioritized_and_dimension_minimum_is_added():
    facts = [_fact("quote-a", "price_snapshot", {"price": 110}, text="报价 A。"), _fact("quote-b", "price_snapshot", {"price": 120}, text="报价 B。"), _fact("tech", "technical_snapshot", {"rsi14": 62})]
    for fact in facts[:2]:
        fact.market_price = fact.structured_data["price"]
        fact.currency = "USD"
    task = _task(fact_ids=[item.source_id for item in facts], selected_fact_ids=["quote-b"], requested_dimensions=["technical_quality"])
    draft = _draft(facts, [task])
    selected = select_fact_ids(draft, task, "chat")
    assert selected == ["quote-b", "tech"]
    markdown = render_research_report(draft, output_mode="chat").markdown
    assert "120 USD" in markdown and "110 USD" not in markdown
    assert "RSI(14) 62" in markdown
    assert "https://example.invalid/quote-a" not in markdown
    assert draft.task_results[0].fact_ids == ["quote-a", "quote-b", "tech"]


def test_comparison_has_one_cross_asset_summary_and_each_asset_details_once():
    facts = [_fact("nvda", "filing_context", {"revenue": [100], "net_income": [30], "currency": "USD", "fact_metadata": {"revenue": [{"period_start": "2026-05-01", "period_end": "2026-07-31", "unit": "USD", "filed": "2026-08-20", "frequency": "quarterly"}]}}, subject="NVDA"), _fact("amd", "filing_context", {"revenue": [50], "net_income": [10], "currency": "USD", "fact_metadata": {"revenue": [{"period_start": "2026-04-01", "period_end": "2026-06-30", "unit": "USD", "filed": "2026-08-01", "frequency": "quarterly"}]}}, subject="AMD")]
    facts[0].task_ids = ["compare", "nvda-task"]
    facts[1].task_ids = ["compare", "amd-task"]
    tasks = [_task(task_id="compare", title="横向比较", render_kind="compare", operation="compare", fact_ids=["nvda", "amd"]), _task(task_id="nvda-task", title="NVDA", subject="NVDA", fact_ids=["nvda"], order_index=1), _task(task_id="amd-task", title="AMD", subject="AMD", fact_ids=["amd"], order_index=2)]
    markdown = render_research_report(_draft(facts, tasks)).markdown
    assert markdown.count("**横向证据比较**") == 1
    assert markdown.count("2026-05-01 至 2026-07-31") == 1
    assert markdown.count("2026-04-01 至 2026-06-30") == 1
    assert markdown.count("披露日 2026-08-20") == 1
    compare_section = markdown.split("## NVDA", 1)[0]
    assert "**财务与公告**" not in compare_section


def test_chat_and_comparison_eps_keep_current_next_quarter_without_year_table():
    facts = [_fact("eps", "earnings_estimates", {"currency": "USD", "earnings_estimate": [{"period": "0q", "avg": 0.39}, {"period": "+1q", "avg": 0.43}, {"period": "0y", "avg": 1.52}, {"period": "+1y", "avg": 2.06}]})]
    draft = _draft(facts, [_task(operation="earnings_performance", fact_ids=["eps"], requested_dimensions=["earnings_impact"])])
    markdown = render_research_report(draft, output_mode="chat").markdown
    assert "当前财政季度 共识 EPS 0.39" in markdown
    assert "下一财政季度 共识 EPS 0.43" in markdown
    assert "当前财年" not in markdown and "下一财年" not in markdown
    assert "下一财年" in render_research_report(draft).markdown


def test_chat_explanations_are_deduplicated_by_dimension_and_full_result_is_preserved():
    facts = [_fact("valuation", "company_profile", {"forwardPE": 20}), _fact("financial", "filing_context", {"revenue": [10]}), _fact("risk", "risk_profile", {"max_drawdown": -0.3})]
    claims = [Claim(claim_id="val", task_id="task", agent_name="research_analyst", text="估值依赖盈利兑现。", stance="unknown", assertion_type="opinion", dimension="valuation", confidence=0.6, evidence_ids=["valuation"], limitations=[], metric="valuation_reasonableness"), Claim(claim_id="duplicate", task_id="task", agent_name="research_analyst", text="估值依赖盈利兑现。", stance="unknown", assertion_type="opinion", dimension="valuation", confidence=0.6, evidence_ids=["valuation"], limitations=[]), Claim(claim_id="fund", task_id="task", agent_name="research_analyst", text="财务质量需结合现金流。", stance="unknown", assertion_type="opinion", dimension="fundamental", confidence=0.6, evidence_ids=["financial"], limitations=[], metric="fundamental_quality"), Claim(claim_id="risk-claim", task_id="task", agent_name="research_analyst", text="回撤事实意味着价格风险需要管理。", stance="unknown", assertion_type="opinion", dimension="risk", confidence=0.6, evidence_ids=["risk"], limitations=[], metric="risk_level")]
    task = _task(fact_ids=[item.source_id for item in facts], claim_ids=[claim.claim_id for claim in claims], requested_dimensions=["valuation_reasonableness", "fundamental_quality", "risk_level"])
    draft = _draft(facts, [task])
    draft.claim_index = {claim.claim_id: claim for claim in claims}
    original = copy.deepcopy(draft.model_dump())
    markdown = render_research_report(draft, output_mode="chat").markdown
    assert markdown.count("估值依赖盈利兑现。") == 1
    assert "财务质量需结合现金流。" in markdown and "价格风险需要管理。" in markdown
    assert draft.model_dump() == original
    assert render_research_report(draft).markdown.count("估值依赖盈利兑现。") == 1


@pytest.mark.parametrize("output_mode", ["chat", "investment_report"])
def test_business_and_competition_only_render_their_own_explanations(output_mode):
    facts = [_fact("profile", "company_profile", {"name": "Intel"}), _fact("technical", "technical_snapshot", {"rsi14": 62}), _fact("risk", "risk_profile", {"max_drawdown": -0.3})]
    claims = [
        Claim(claim_id=claim_id, task_id="task", agent_name="research_analyst", text=text,
              stance="unknown", dimension="unknown", confidence=0.6, evidence_ids=sources,
              limitations=[], metric=metric)
        for claim_id, text, sources, metric in [
            ("business", "业务依赖产品需求兑现。", ["profile"], "business_model"),
            ("competition", "竞争取决于产品迭代能力。", ["profile"], "competition"),
            ("valuation", "估值取决于盈利兑现。", ["profile"], "valuation_reasonableness"),
            ("risk-claim", "风险需要结合回撤管理。", ["profile", "risk"], "risk_level"),
            ("general", "通用研究解释保留审慎判断。", ["profile", "technical"], None),
        ]
    ]
    task = _task(fact_ids=[fact.source_id for fact in facts], claim_ids=[claim.claim_id for claim in claims], requested_dimensions=["business_model", "competition", "valuation_reasonableness", "risk_level", "technical_quality"])
    draft = _draft(facts, [task])
    draft.claim_index = {claim.claim_id: claim for claim in claims}
    original = copy.deepcopy(draft.model_dump())

    markdown = render_research_report(draft, output_mode=output_mode).markdown
    business = markdown.split("**业务与商业模式**", 1)[1].split("**竞争格局**", 1)[0]
    competition = markdown.split("**竞争格局**", 1)[1].split("**公司与估值**", 1)[0]
    general = markdown.split("**研究判断与风险**", 1)[1]
    assert claims[0].text in business and claims[1].text not in business
    assert claims[1].text in competition and claims[0].text not in competition
    for claim in claims[2:]:
        assert claim.text not in business and claim.text not in competition
        assert claim.text in general
    assert all(markdown.count(claim.text) == 1 for claim in claims)
    assert draft.model_dump() == original


def test_dimension_bound_material_can_place_an_untagged_explanation():
    fact = _fact("competition-material", "document_context", {}, text="竞争材料。")
    fact.metric = "competition"
    claim = Claim(claim_id="competition", task_id="task", agent_name="research_analyst",
                  text="对应材料支持竞争格局解释。", stance="unknown", dimension="unknown",
                  confidence=0.6, evidence_ids=[fact.source_id], limitations=[])
    draft = _draft([fact], [_task(fact_ids=[fact.source_id], claim_ids=[claim.claim_id], requested_dimensions=["business_model", "competition"])])
    draft.claim_index = {claim.claim_id: claim}
    markdown = render_research_report(draft).markdown
    business, competition = markdown.split("**业务与商业模式**", 1)[1].split("**竞争格局**", 1)
    assert claim.text not in business and claim.text in competition
    assert markdown.count(claim.text) == 1


@pytest.mark.parametrize("dimension,label", [
    ("valuation_reasonableness", "估值合理性"), ("business_model", "业务与商业模式"),
    ("competition", "竞争格局"), ("trend_quality", "趋势质量"), ("earnings_impact", "财报影响"),
])
def test_missing_dimension_uses_human_label(dimension, label):
    draft = _draft([], [_task(status="partial", requested_dimensions=[dimension])])
    markdown = render_research_report(draft, output_mode="chat").markdown
    assert f"[数据缺失] {label}尚无可展示的已验证事实。" in markdown
    assert dimension not in markdown


@pytest.mark.asyncio
async def test_selected_fact_ids_survive_synthesis_while_all_facts_remain_in_artifact(monkeypatch):
    from backend.tests.test_foundation_analysis_pipeline import _state
    from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
    from backend.graph.nodes.analyze import analyze
    import backend.graph.synthesis.research_synthesis as synthesis

    async def select(**kwargs):
        return kwargs["schema"].model_validate({"claim_ids": [], "fact_ids": ["get_company_info:step"], "conclusion_claim_id": None, "proposed_direction": None, "direction_supporting_claim_ids": []})
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")
    monkeypatch.setattr(synthesis, "_invoke_structured", select)
    state = _state("qa", "get_company_info", {"ticker": "NVDA", "profitMargins": 0.5}, "company_profile")
    state["plan_ir"]["steps"].append({"id": "quote", "name": "get_stock_price", "kind": "tool", "task_ids": ["task"], "inputs": {"ticker": "NVDA"}, "evidence_kinds": ["price_snapshot"]})
    state["artifacts"]["step_results"]["quote"] = {"output": {"ticker": "NVDA", "price": 140, "as_of": "2026-10-02", "currency": "USD"}}
    normalize_execution_evidence(state=state, plan_ir=state["plan_ir"], artifacts=state["artifacts"])
    result = await analyze(state)
    task = result["artifacts"]["research_result"]["task_results"][0]
    assert task["selected_fact_ids"] == ["get_company_info:step"]
    assert "get_stock_price:quote" in task["fact_ids"]
    assert "get_stock_price:quote" in result["artifacts"]["research_result"]["evidence_index"]


@pytest.mark.asyncio
async def test_macro_search_material_is_raw_and_never_pasted_as_a_verified_fact(monkeypatch):
    from backend.tests.test_foundation_analysis_pipeline import _state
    from backend.graph.nodes.analyze import analyze
    from backend.graph.nodes.render_node import render_node

    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")
    material = "Search Results:\n来源：某经济转载网页\n" + "原始转载正文、旧日期、网站投资建议。" * 200
    state = _state("macro_brief", "search", material, "macro_context", subject="宏观")
    result = await analyze(state)
    evidence = result["artifacts"]["research_result"]["evidence_index"]["search:step"]
    assert evidence["usage"] == "raw" and evidence["metadata"]["verification"] == "discovery_only"
    assert "网站投资建议" in evidence["structured_data"]["text"]
    markdown = render_node({**state, **result})["artifacts"]["draft_markdown"]
    assert "原始转载正文" not in markdown and "网站投资建议" not in markdown
    assert "未核实的检索材料" in markdown and "仅为检索线索" in markdown


@pytest.mark.asyncio
@pytest.mark.parametrize("role,usage", [("reported_news", "fact"), ("opinion", "raw"), ("discovery", "raw"), ("historical_news", "raw")])
async def test_news_event_quality_role_is_preserved_in_normalized_evidence(monkeypatch, role, usage):
    from backend.tests.test_foundation_analysis_pipeline import _state
    from backend.graph.nodes.analyze import analyze
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")
    quality = {"version": "news-event-v1", "evidence_role": role, "published_at": "2026-10-02", "occurred_at": None, "independence": "unverified"}
    state = _state("qa", "get_company_news", [{"title": "NVDA product news", "snippet": "NVDA product update", "url": "https://example.invalid/news", "event_quality": quality}], "news_context")
    result = await analyze(state)
    evidence = next(item for item in result["artifacts"]["research_result"]["evidence_index"].values() if item["url"])
    assert evidence["usage"] == usage
    assert evidence["metadata"]["event_quality"] == quality
