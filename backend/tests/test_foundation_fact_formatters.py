# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import re

import pytest

from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
from backend.graph.nodes.render_node import render_node
from backend.graph.renderers.fact_formatters import format_fact
from backend.graph.synthesis.contracts import NormalizedEvidence
from backend.graph.synthesis.research_synthesis import _validate_explanation
from backend.graph.synthesis.structured_orchestration import prepare_chat_task_contract, prepare_opinion_synthesis


def _evidence(kind, payload, *, text="结构化源事实。"):
    return NormalizedEvidence(source_id="fixture-source", task_ids=["task"], subject="INTC", kind=kind, usage="fact", text=text, structured_data=payload)


def test_eps_estimates_and_revisions_use_real_schema_and_disclose_missing_currency():
    payload = {"as_of": "2026-10-03T13:04:19.217543", "earnings_estimate": [{"period": "0q", "avg": 0.39065, "low": 0.37, "high": 0.48, "numberOfAnalysts": 35.0, "growth": 0.6985}], "eps_revisions": [{"period": "0q", "upLast7days": 0.0, "downLast7Days": 2.0, "upLast30days": 30.0, "downLast30days": 0.0}], "eps_trend": [{"period": "0q", "current": 0.39065, "30daysAgo": 0.38887}]}
    text = format_fact(_evidence("earnings_estimates", payload))
    assert "当前财政季度 共识 EPS 0.3906 [币种未提供]/股" in text
    assert "上修 0 次，下修 2 次" in text
    assert "69.85%" in text and payload["as_of"] in text
    assert not re.search(r"\{\s*['\"]", text)


def test_sec_latest_period_currency_and_missing_single_quarter_are_preserved():
    payload = {"period_ends": ["2026-06-27"], "currency": "USD", "revenue": [16_128_000_000.0], "eps": [-2.16], "operating_cash_flow": [None], "fact_metadata": {"revenue": [{"period_start": "2026-03-29", "period_end": "2026-06-27", "unit": "USD", "frequency": "quarterly", "filed": "2026-07-24"}], "eps": [{"period_start": "2026-03-29", "period_end": "2026-06-27", "unit": "USD/shares", "frequency": "quarterly"}]}}
    text = format_fact(_evidence("filing_context", payload))
    assert "2026-06-27 营收 161.28 亿 USD" in text
    assert "2026-03-29 至 2026-06-27" in text and "披露日 2026-07-24" in text
    assert "EPS -2.16 USD/shares" in text
    assert "[数据缺失] 2026-06-27 经营现金流" in text


def test_risk_factors_are_chinese_numbers_instead_of_python_repr():
    payload = {"as_of": "2026-10-03T13:04:21.251440", "lookback_days": 252, "positions": [{"ticker": "INTC", "weight": 1.0}], "factor_beta": {"market": 2.9451, "growth": 2.4804}, "annualized_volatility": 0.7699, "max_drawdown": -0.419, "market_r2": 0.2478, "observation_count": 251}
    text = format_fact(_evidence("risk_profile", payload))
    assert "市场 2.9451" in text and "成长 2.4804" in text
    assert "历史年化波动率 76.99%" in text and "最大回撤 -41.9%" in text
    assert "观察窗口 252 个交易日" in text and payload["as_of"] in text
    assert "positions" not in text and "{'" not in text


def test_calendar_deduplicates_dates_and_separates_unconfirmed_macro_discovery():
    payload = {"days_ahead": 30, "as_of": "2026-10-03", "earnings_events": [{"date": "2026-10-22", "title": "Earnings Date", "source": "yfinance_calendar"}, {"date": "2026-10-22", "title": "Earnings Date", "source": "yfinance_earnings_dates"}], "macro_events": [{"date": "2026-10-07", "title": "FOMC Minutes", "source": "search_macro_calendar"}, {"date": None, "title": "Calendar Header", "source": "search_macro_calendar"}]}
    text = format_fact(_evidence("event_calendar", payload))
    assert text.count("2026-10-22") == 1
    assert "搜索日历线索，仍需官方确认" in text
    assert "覆盖未来 30 天" in text
    assert "Calendar Header" not in text


def test_technical_indicator_precision_is_stable_and_financially_readable():
    text = format_fact(_evidence("technical_snapshot", {"close": 119.33, "ma20": 111.63500009999998, "rsi14": 72.19326383319968, "macd": 6.0886373862593075, "macd_signal": 5.65323109382947, "trend": "uptrend"}))
    assert "MA20 111.64" in text and "RSI(14) 72.19" in text and "MACD 6.0886" in text
    assert "上升趋势" in text
    assert not re.search(r"\d+\.\d{8,}", text)


def test_no_sentiment_observations_are_not_presented_as_neutral_market_sentiment():
    text = format_fact(_evidence("news_context", {"snapshot": {
        "sentiment_bias": {"sample_size": 0, "label": "neutral", "average_score": None},
        "heat": {"news_count": 0},
    }}))
    assert "舆情样本不足" in text
    assert "样本舆情中性" not in text


def test_unknown_structured_payload_is_an_explicit_gap_and_never_a_json_dump():
    text = format_fact(_evidence("technical_snapshot", {}, text='{"unsupported_field": [{"value": 42}'))
    assert "[数据缺失]" in text and "unsupported_field" not in text


@pytest.mark.parametrize("text", ["共识 EPS 约为 0.39。", "营收约 161.3 亿 USD。", "同比增长约 25.4%。", "1) 财报兑现仍需观察。\n2) 未来一季度跟踪现金流。"])
def test_explanation_accepts_arithmetic_unit_conversion_rounding_and_enumeration(text):
    evidence = _evidence("fundamental_snapshot", {"revenue": 16_128_000_000.0, "eps": 0.39065, "yoy": 0.2542188350571584})
    _validate_explanation(text, [evidence], [])


@pytest.mark.parametrize("text", ["营收达到 999 亿 USD。", "下一次财报确定在 2027-12-31 发布。"])
def test_new_financial_number_or_date_still_fails_binding(text):
    with pytest.raises(ValueError):
        _validate_explanation(text, [_evidence("fundamental_snapshot", {"revenue": 16_128_000_000.0, "eps": 0.39065})], [])


@pytest.mark.asyncio
async def test_json_string_tools_preserve_full_payload_through_pipeline_and_unrelated_news_stays_out(monkeypatch):
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")
    task = {"id": "task", "title": "NVDA 研究", "subject_type": "company", "subject_label": "NVDA", "tickers": ["NVDA"], "operation": {"name": "qa"}, "priority": 0, "order_index": 0, "request_frame_id": "frame", "render_group_id": "frame", "render_kind": "single", "required_evidence": ["company_profile", "earnings_estimates", "news_context"], "required_step_ids": ["profile", "eps", "news"]}
    steps = [{"id": "profile", "kind": "tool", "name": "get_company_info", "task_ids": ["task"], "inputs": {"ticker": "NVDA"}, "evidence_kinds": ["company_profile"]}, {"id": "eps", "kind": "tool", "name": "get_earnings_estimates", "task_ids": ["task"], "inputs": {"ticker": "NVDA"}, "evidence_kinds": ["earnings_estimates"]}, {"id": "news", "kind": "tool", "name": "get_company_news", "task_ids": ["task"], "inputs": {"ticker": "NVDA"}, "evidence_kinds": ["news_context"]}]
    earnings = {"ticker": "NVDA", "padding": "x" * 900, "currency": "USD", "as_of": "2026-10-02", "earnings_estimate": [{"period": "+1q", "avg": 2.4}]}
    outputs = {"profile": "Company Profile (NVDA):\n- Name: NVIDIA Corporation\n- Market Cap: USD 1,000,000\n- Currency: USD", "eps": json.dumps(earnings), "news": [{"title": "NVIDIA announces new product", "snippet": "NVIDIA announced a new chip.", "url": "https://example.invalid/nvidia"}, {"title": "Nike shares drop", "snippet": "Nike reported weak sales.", "url": "https://example.invalid/nike"}, {"title": "G7 diesel forecast", "snippet": "Diesel trade weakens.", "url": "https://example.invalid/diesel"}]}
    state = {"output_mode": "chat", "tasks": [task], "plan_ir": {"tasks": [task], "steps": steps}, "subject": {"tickers": ["NVDA"]}, "artifacts": {"step_results": {key: {"output": value} for key, value in outputs.items()}}, "trace": {}}
    normalize_execution_evidence(state=state, plan_ir=state["plan_ir"], artifacts=state["artifacts"])
    prepared, contract = prepare_chat_task_contract(state, {})
    research = await prepare_opinion_synthesis(prepared, contract, structured_synthesis_mode="off", env_mode="stub")
    result = render_node(research)
    markdown = result["artifacts"]["draft_markdown"]
    assert "下一财政季度 共识 EPS 2.4 USD/股" in markdown
    assert "NVIDIA announces new product" in markdown
    assert "Nike shares" not in markdown and "G7 diesel" not in markdown
    evidence = research["artifacts"]["research_result"]["evidence_index"]
    assert evidence["get_earnings_estimates:eps"]["structured_data"] == earnings
    assert not re.search(r"\{\s*['\"]", markdown)


@pytest.mark.asyncio
async def test_invalid_explanation_segment_keeps_valid_segment_and_selected_claims(monkeypatch):
    from backend.tests.test_foundation_analysis_pipeline import _state
    from backend.graph.nodes.analyze import analyze
    import backend.graph.synthesis.research_synthesis as synthesis

    async def select(**kwargs):
        return kwargs["schema"].model_validate({"claim_ids": ["claim-safe"], "conclusion_claim_id": "claim-safe", "proposed_direction": None, "direction_supporting_claim_ids": [], "explanations": [{"text": "利润率达到999%，增长必定兑现。", "evidence_ids": ["get_company_info:step"]}, {"text": "利润率反映当前经营效率，需求兑现仍需后续财报验证。", "evidence_ids": ["get_company_info:step"]}]})
    monkeypatch.setattr(synthesis, "_invoke_structured", select)
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")
    state = _state("qa", "get_company_info", {"ticker": "NVDA", "profitMargins": 0.5}, "company_profile")
    state["plan_ir"]["steps"].append({"id": "agent", "name": "fundamental_agent", "kind": "agent", "task_ids": ["task"], "inputs": {"ticker": "NVDA"}})
    state["artifacts"]["step_results"]["agent"] = {"output": {"agent_name": "fundamental_agent", "summary": "公司净利率为50%。", "raw_claims": [{"claim_id": "claim-safe", "task_id": "task", "agent_name": "fundamental_agent", "text": "公司净利率为50%。", "stance": "neutral", "confidence": 0.8, "evidence_ids": ["get_company_info:step"], "limitations": []}]}}
    result = await analyze(state)
    task = result["artifacts"]["research_result"]["task_results"][0]
    markdown = render_node({**state, **result})["artifacts"]["draft_markdown"]
    assert "999" not in markdown and "需求兑现仍需后续财报验证" in markdown
    assert "净利率：50%" in markdown
    assert "claim-safe" in task["claim_ids"]
    assert "公司净利率为50%。" in result["artifacts"]["research_result"]["claim_index"]["claim-safe"]["text"]
    assert "explanation_contains_unbound_number" in task["error_codes"]
    assert task["status"] == "partial" and "部分完成" in markdown
