"""公告财务值必须由原文支持，跨财期事实保持独立。"""
from types import SimpleNamespace

import pytest

from backend.graph.execution.evidence_tools import append_tool_evidence
from backend.tools import local_disclosure
from backend.tools.disclosure_financial_facts import _table_context, validate_financial_facts


BODY = "[Page 1]\n证券代码：600519\n[Page 85]\n单位：万元 币种：人民币\n2025年度 2024年度\n经营活动产生的现金流量净额 12,345.67 8,901.23"
ROW = {
    "metric": "operating_cash_flow", "amount_text": "12,345.67", "scale": 10000,
    "currency": "CNY", "period_start": "2025-01-01", "period_end": "2025-12-31",
    "page": 85, "quote": "经营活动产生的现金流量净额 12,345.67 8,901.23",
    "unit_quote": "单位：万元 币种：人民币", "period_quote": "2025年度 2024年度",
}


def _extract(row):
    return validate_financial_facts({"facts": [row]}, text=BODY, ticker="600519.SS", source_url="https://www.cninfo.com.cn/report.pdf")


def test_financial_fact_preserves_original_unit_period_and_source_page():
    fact = _extract(ROW)[0]
    assert fact["value"] == pytest.approx(123_456_700)
    assert fact["frequency"] == "annual" and fact["unit"] == "CNY"
    assert fact["page"] == 85 and fact["period_end"] == "2025-12-31"


def test_pdf_adjacent_numeric_columns_keep_complete_first_amount():
    body = BODY.replace("12,345.67", "12,345.6745,678.90")
    row = {**ROW, "quote": ROW["quote"].replace("12,345.67", "12,345.6745,678.90")}
    assert validate_financial_facts({"facts": [row]}, text=body, ticker="600519.SS", source_url="https://example.com/report.pdf")
    assert not validate_financial_facts({"facts": [{**row, "amount_text": "12,345"}]}, text=body, ticker="600519.SS", source_url="https://example.com/report.pdf")


def test_disclosure_queries_keep_semantic_identity_and_requested_period():
    queries = local_disclosure._build_queries("600519.SS", "CN", "贵州茅台", "2025 财年经营现金流")
    assert all("贵州茅台 600519" in query and "2025 财年经营现金流" in query for query in queries)
    assert all(".SS" not in query for query in queries)
    assert local_disclosure._issuer_identity("公司代码：600519\n贵州茅台股份有限公司", "600519.SS") == "document_stock_code"
    assert local_disclosure._issuer_identity("公司代码：600016", "600519.SS") is None


@pytest.mark.parametrize("changes", [
    {"amount_text": "12,345"}, {"page": 2}, {"scale": 1}, {"currency": "USD"},
    {"period_start": "2026-01-01", "period_end": "2026-12-31"},
    {"unit_quote": "单位：亿元 币种：人民币"},
])
def test_ungrounded_amount_page_unit_currency_and_year_are_rejected(changes):
    assert _extract({**ROW, **changes}) == []


def test_financial_evidence_is_separate_from_announcement_metadata():
    facts = _extract(ROW)
    quarterly = {**facts[0], "period_start": "2026-01-01", "period_end": "2026-03-31", "frequency": "quarterly", "value": 30}
    pool = []
    append_tool_evidence(pool, "get_local_market_filings", "s1", {
        "ticker": "600519.SS", "market": "CN", "filings": [{
            "filing_url": facts[0]["source_url"], "issuer_verified": True,
            "issuer_ticker": "600519.SS", "financial_facts": [*facts, quarterly],
        }],
    })
    assert len(pool) == 3
    assert [item["frequency"] for item in pool[1:]] == ["annual", "quarterly"]
    assert pool[1]["kind"] == "capital_allocation"
    assert pool[1]["structured_data"]["metrics"]["operating_cash_flow"]["value"] == pytest.approx(123_456_700)


def test_disclosure_pdf_reads_financial_pages_beyond_identity_frontmatter(monkeypatch):
    response = SimpleNamespace(status_code=200, iter_content=lambda **_: iter([b"%PDF fixture"]), close=lambda: None)
    monkeypatch.setattr(local_disclosure, "_http_get_no_retry", lambda *_, **__: response)
    import pypdf
    monkeypatch.setattr(pypdf, "PdfReader", lambda _: SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda number=number: f"body {number}") for number in range(1, 86)]))
    text = local_disclosure._fetch_disclosure_text("https://www.cninfo.com.cn/report.pdf", full_document=True)
    assert "[Page 85]\nbody 85" in text
    assert "[Page 4]" not in local_disclosure._fetch_disclosure_text("https://www.cninfo.com.cn/report.pdf")


def test_large_document_keeps_numeric_tables_with_original_page_numbers():
    text = "[Page 1]\n" + "叙述" * 100 + "\n[Page 85]\n" + ROW["quote"]
    selected = _table_context(text, limit=100)
    assert "[Page 85]" in selected and ROW["quote"] in selected


def test_financial_extraction_runs_once_after_issuer_verification(monkeypatch):
    from backend.tools import disclosure_financial_facts
    monkeypatch.setattr(local_disclosure, "search", lambda _: "1. 年报\nhttps://www.cninfo.com.cn/report.pdf")
    monkeypatch.setattr(local_disclosure, "_fetch_disclosure_text", lambda *_, **__: BODY)
    calls = []
    monkeypatch.setattr(disclosure_financial_facts, "extract_financial_facts", lambda *args: calls.append(args) or _extract(ROW))
    result = local_disclosure.get_local_market_filings("600519.SS", include_financial_facts=True)
    assert len(calls) == 1 and result["filings"][0]["financial_facts"][0]["unit"] == "CNY"


@pytest.mark.parametrize("ticker", ["600519.SS", "0700.HK"])
def test_numeric_local_financial_requirement_enables_original_table_extraction(ticker):
    from backend.graph.nodes.policy_gate import policy_gate
    from backend.graph.planning.rule_planner import rule_based_planner
    from backend.graph.request_compiler import compile_semantic_contract

    query = "最近完整年度经营现金流是多少？"
    semantic = {"subjects": [{"id": "company", "type": "company", "label": ticker, "tickers": [ticker]}],
                "requirements": [{"source_text": query, "description": query, "kind": "fact_attribute",
                                  "metric": "operating_cash_flow", "subject": ticker, "subject_refs": ["company"],
                                  "time_scope": {"kind": "fiscal_year", "count": 1}}]}
    state = {"query": query, "output_mode": "chat", "understanding": {"original_query": query}}
    state.update(compile_semantic_contract(state, semantic, {}))
    state.update(policy_gate(state))
    state.update(rule_based_planner(state))
    local_step = next(step for step in state["plan_ir"]["steps"] if step["name"] == "get_local_market_filings")
    assert local_step["inputs"]["include_financial_facts"] is True
