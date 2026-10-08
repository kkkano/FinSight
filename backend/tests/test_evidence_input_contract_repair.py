"""真实工具输出形状经过执行、合成、需求核验和正文渲染的跨层回归。"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib

import pytest


def test_company_profile_business_description_and_provenance_survive_tool_normalization():
    from backend.graph.execution.evidence_tools import append_tool_evidence
    pool = []
    text = "Company Profile (MSFT):\n- Name: Microsoft\n- Description: 提供企业软件与云服务。\n- Source: yfinance\n- Source URL: https://finance.yahoo.com/quote/MSFT/profile/\n- Retrieved At: 2026-10-08T00:00:00Z"
    append_tool_evidence(pool, "get_company_info", "s1", text)
    assert pool[0]["structured_data"]["description"] == "提供企业软件与云服务。"
    assert pool[0]["url"] == "https://finance.yahoo.com/quote/MSFT/profile/"
    assert pool[0]["as_of"] == "2026-10-08T00:00:00Z"

from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
from backend.graph.nodes.analyze import analyze
from backend.graph.nodes.render_node import render_node
from backend.graph.synthesis.contracts import NormalizedEvidence
from backend.graph.synthesis.research_synthesis import _validate_explanation
from backend.research.news_event_quality import prepare_news_items


@pytest.fixture(autouse=True)
def _isolated_fixture_execution(monkeypatch):
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")


def _state(tool, output, kind, requirements, *, ticker="CRM", inputs=None):
    task = {
        "id": "task", "title": "用户要求", "subject_type": "company", "subject_label": ticker,
        "tickers": [ticker], "operation": {"name": "qa"}, "priority": 0, "order_index": 0,
        "request_frame_id": "frame", "render_group_id": "frame", "render_kind": "single",
        "required_evidence": [kind], "required_step_ids": ["step"], "answer_requirements": requirements,
    }
    step = {"id": "step", "kind": "tool", "name": tool, "task_ids": ["task"],
            "inputs": {"ticker": ticker, **(inputs or {})}, "evidence_kinds": [kind], "subject_tickers": [ticker]}
    state = {
        "query": "已编译的请求", "understanding": {"route": "research"}, "output_mode": "chat",
        "operation": task["operation"], "subject": {"subject_type": "company", "tickers": [ticker]},
        "tasks": [task], "plan_ir": {"tasks": [task], "steps": [step]},
        "artifacts": {"step_results": {"step": {"output": output}}}, "trace": {},
    }
    normalize_execution_evidence(state=state, plan_ir=state["plan_ir"], artifacts=state["artifacts"])
    return state


def _window_requirement(direction="past", value=72, unit="hours"):
    return {"requirement_id": "task:time_window", "kind": "event_window", "dimension": "news_catalysts",
            "description": "按请求窗口提供可核验事件", "evidence_kinds": ["news_context" if direction == "past" else "event_calendar"],
            "requires_analysis": False, "time_window": {"direction": direction, "value": value, "unit": unit}}


@pytest.mark.asyncio
@pytest.mark.parametrize("content_read", [True, False])
async def test_sec_disclosure_body_is_required_and_retained_through_answer_rendering(monkeypatch, content_read):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")
    business = "Item 1. Business. We provide enterprise subscription software and customer service applications."
    competition = "Competition. We compete with cloud application vendors on product capability, service, and pricing."
    filing = {"form": "10-K", "filing_date": "2026-09-01", "filing_url": "https://www.sec.gov/Archives/example/report.htm",
              "primary_doc_description": "Annual report", "content_read": content_read}
    if content_read:
        filing.update(content_sections={"business": business, "competition": competition},
                      content_excerpt=f"business: {business}\n\ncompetition: {competition}")
    requirements = [{"requirement_id": f"task:{dimension}", "kind": "explanation", "dimension": dimension,
                     "description": label, "evidence_kinds": ["filing_context"], "requires_analysis": True}
                    for dimension, label in (("business_model", "解释商业模式"), ("competition", "解释竞争因素"))]
    observed = []

    async def select(**kwargs):
        observed.append(kwargs)
        return kwargs["schema"].model_validate({"claim_ids": [], "direction_supporting_claim_ids": [], "fact_ids": ["E1"], "explanations": [
            {"text": "订阅业务需要维持企业客户的持续采用。", "evidence_ids": ["E1"], "dimension": "business_model", "requirement_ids": ["task:business_model"]},
            {"text": "云应用竞争要求兼顾产品能力、服务及定价。", "evidence_ids": ["E1"], "dimension": "competition", "requirement_ids": ["task:competition"]},
        ]})

    monkeypatch.setattr(module, "_invoke_structured", select)
    state = _state("get_sec_filings", {"ticker": "CRM", "source": "sec_edgar", "filings": [filing]}, "filing_context", requirements, inputs={"include_content": True})
    analyzed = await analyze(state)
    result = analyzed["artifacts"]["research_result"]
    task = result["task_results"][0]
    evidence = next(iter(result["evidence_index"].values()))
    markdown = render_node({**state, **analyzed})["artifacts"]["draft_markdown"]
    if content_read:
        assert evidence["structured_data"]["content_sections"]["competition"] == competition
        assert business in observed[0]["prompt"] and competition in observed[0]["prompt"]
        assert [item["status"] for item in task["requirement_results"]] == ["answered", "answered"]
        assert "已读取业务、竞争正文" in markdown
        assert business not in markdown and competition not in markdown
        assert "该来源为公告索引" not in markdown
    else:
        assert all(item["status"] == "missing" for item in task["requirement_results"])
        assert "explanation_requires_document_body" in task["error_codes"]
        assert "订阅业务需要维持" not in markdown
        assert evidence["usage"] == "raw"
        assert "部分材料仅为检索线索" in markdown


@pytest.mark.asyncio
async def test_news_applied_window_remains_bounded_after_execution_and_synthesis():
    now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
    articles = prepare_news_items([{
        "title": "Netflix (NFLX) announces advertising product update", "source": "Reuters",
        "url": "https://www.reuters.com/business/media/netflix-product-fixture",
        "snippet": "Netflix announced an update to its advertising product.",
        "published_at": "2026-10-03T12:00:00Z", "retrieval_kind": "rss",
    }], ticker="NFLX", now=now, max_age_hours=72)
    state = _state("get_authoritative_media_news", {"ticker": "NFLX", "articles": articles}, "news_context", [_window_requirement()], ticker="NFLX")
    analyzed = await analyze(state)
    result = analyzed["artifacts"]["research_result"]
    task = result["task_results"][0]
    check = task["requirement_results"][0]
    evidence = NormalizedEvidence.model_validate(next(iter(result["evidence_index"].values())))
    assert evidence.metadata["coverage_window"]["value"] == 72
    assert evidence.metadata["coverage_window"]["exhaustive"] is False
    assert check["status"] == "answered"
    assert check["window_coverage"]["status"] == "bounded"
    assert check["window_coverage"]["scope"] == "returned_articles"
    assert any("不能据此断言" in item for item in task["limitations"])
    with pytest.raises(ValueError, match="explanation_unsupported_window_absence"):
        _validate_explanation("过去72小时没有任何重大新闻。", [evidence], [])


@pytest.mark.asyncio
@pytest.mark.parametrize("actual_coverage", [True, False])
async def test_calendar_request_parameters_do_not_substitute_for_observed_provider_window(actual_coverage):
    window = {"direction": "future", "value": 90, "unit": "days", "days_ahead": 90,
              "scope": "provider_calendar", "as_of": "2026-10-04T12:00:00Z", "exhaustive": False}
    output = {"ticker": "CRM", "days_ahead": 90, "as_of": "2026-10-04T12:00:00Z",
              "request_window": window, "source": "yfinance_calendar",
              "earnings_events": [{"date": "2026-11-20", "title": "Earnings Date", "source": "yfinance_calendar", "verification": "provider_reported"}]}
    if actual_coverage:
        output["coverage_window"] = window
    state = _state("get_event_calendar", output, "event_calendar", [_window_requirement("future", 90, "days")], inputs={"days_ahead": 90})
    analyzed = await analyze(state)
    task = analyzed["artifacts"]["research_result"]["task_results"][0]
    check = task["requirement_results"][0]
    markdown = render_node({**state, **analyzed})["artifacts"]["draft_markdown"]
    if actual_coverage:
        assert check["status"] == "answered" and check["window_coverage"]["status"] == "bounded"
        assert "本轮供应商日历查询窗口为未来 90 天" in markdown
        assert "不代表已取得全部事件" in markdown and "日期以公司或官方披露为准" in markdown
    else:
        assert check["status"] == "partial"
        assert check["reason"] == "requirement_time_window_unverified"
        assert "本轮供应商日历查询窗口为未来 90 天" not in markdown


@pytest.mark.asyncio
@pytest.mark.parametrize("as_text", [True, False])
async def test_daily_close_quote_session_and_date_precision_survive_actual_input_path(as_text):
    output = {"price": 240.25, "currency": "USD", "source": "fixture_daily_close", "as_of": "2026-10-02",
              "market_session": "regular_close", "source_time_precision": "date", "source_time_status": "known"}
    if as_text:
        output = "Current Price: $240.25 | Currency: USD | Source: fixture_daily_close | As of: 2026-10-02 | Session: regular_close | Time precision: date | Time status: known"
    requirement = {"requirement_id": "task:quote_attributes", "kind": "fact_attribute", "dimension": "performance",
                   "description": "币种、来源时间和盘后属性", "evidence_kinds": ["price_snapshot"], "requires_analysis": False,
                   "attributes": ["currency", "source_timestamp", "market_session"]}
    state = _state("get_stock_price", output, "price_snapshot", [requirement], ticker="ADBE")
    analyzed = await analyze(state)
    result = analyzed["artifacts"]["research_result"]
    evidence = next(iter(result["evidence_index"].values()))
    markdown = render_node({**state, **analyzed})["artifacts"]["draft_markdown"]
    assert evidence["metadata"]["market_session"] == "regular_close"
    assert evidence["metadata"]["source_time_precision"] == "date"
    assert result["task_results"][0]["requirement_results"][0]["status"] == "answered"
    assert "240.25 USD" in markdown and "常规交易时段的日线收盘价，非盘后价格" in markdown
    assert "源日期：2026-10-02" in markdown and "不代表精确成交时刻" in markdown
