"""已有原文与数值跨工具/Agent 进入同一事实合同，不重新抓取或解释格式化金额。"""
from unittest.mock import MagicMock

from backend.agents.deep_search_agent import DeepSearchAgent
from backend.agents.fundamental_agent import FundamentalAgent
from backend.tools import disclosure_financial_facts
from backend.tools.local_disclosure import verified_disclosure_document


def test_fundamental_evidence_preserves_original_amount_without_rounding():
    agent = FundamentalAgent(None, MagicMock(), MagicMock())
    output = agent._format_output("财务事实", {"ticker": "0700.HK", "financials": {"source": "yfinance"},
        "normalized_metrics": {"metrics": {"revenue": {"latest": 204_779_123_456.78,
            "latest_period": "2026-06-30", "period_type": "quarterly", "currency": "CNY", "unit": "CNY"}}}})
    evidence = next(item for item in output.evidence if item.meta.get("metric") == "revenue")
    assert evidence.meta["value"] == 204_779_123_456.78
    assert "204.78B" in evidence.text


def test_official_document_requires_declared_issuer_and_website():
    body = "证券代码：300750\n发行人2025年度报告\n公司网址：www.issuer.example\n"
    assert verified_disclosure_document(body, "https://issuer.example/report.pdf", "300750.SZ")
    assert not verified_disclosure_document(body, "https://media.example/report.pdf", "300750.SZ")
    assert not verified_disclosure_document(body, "https://issuer.example/report.pdf", "600519.SS")


def test_deepsearch_reuses_read_official_document_and_retains_fact_contract(monkeypatch):
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    body = "[Page 1]\n发行人2025年年度报告\n证券代码：300750\n公司网址：www.issuer.example"
    original = [{"content": body, "url": "https://issuer.example/report.pdf", "title": "旧搜索标题", "degraded": False}]
    calls = []
    fact = {"subject": "300750.SZ", "metric": "operating_cash_flow", "value": 133219982000,
            "unit": "CNY", "frequency": "annual", "period_start": "2025-01-01", "period_end": "2025-12-31",
            "source_url": original[0]["url"], "quote": "现金流原文", "verification": "official_filing_body", "content_read": True}
    def extract(text, ticker, url, metrics, **kwargs):
        calls.append((text, kwargs))
        return [fact]
    monkeypatch.setattr(disclosure_financial_facts, "extract_financial_facts", extract)
    scope = {"kind": "fiscal_year", "period_end": "2025-12-31"}
    enriched = agent._extract_document_facts(original, "300750.SZ", ["operating_cash_flow", "unknown"], scope, "发行人")
    assert len(calls) == 1 and calls[0] == (body, {"time_scope": scope, "diagnostics": {}})
    assert "financial_facts" not in original[0]
    output = agent._format_output("报告", enriched, ticker="300750.SZ")
    assert output.evidence[0].title == "发行人2025年年度报告"
    assert output.evidence[0].meta["source_time_status"] == "unknown"
    assert output.evidence[1].meta["value"] == 133219982000
    assert output.evidence[1].meta["subject"] == "300750.SZ"


def test_shared_documents_do_not_claim_research_ticker_or_fake_publication_date():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    output = agent._format_output("资料", [{"content": "AMD发布新闻", "url": "https://media.example/news", "title": "AMD news", "fetched_at": "2026-10-08"}], ticker="NVDA")
    item = output.evidence[0]
    assert item.meta["shared_document"] and item.meta["subject"] is None
    assert item.meta["subject_binding"] == "document_context"
    assert item.meta["source_time_status"] == "unknown" and item.timestamp is None
    assert item.meta["fetched_at"] == "2026-10-08"


def test_explicit_period_ranks_matching_document_before_older_source():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    rows = [{"title": f"Company annual report {year}", "url": f"https://www.sec.gov/{year}.pdf", "snippet": "filing"} for year in (2024, 2025)]
    selected = agent._filter_results(rows, query="Company report", ticker="CMP", time_scope={"kind": "fiscal_year", "period_end": "2025-12-31"})
    assert "2025" in selected[0]["title"]


def test_local_and_deepsearch_share_two_document_extraction_budget(monkeypatch):
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    body = "[Page 1]\n发行人2025年年度报告\n证券代码：300750\n公司网址：www.issuer.example"
    docs = [{"content": body, "url": f"https://issuer.example/{index}.pdf", "financial_extraction": {"error": "no_financial_candidates"}} for index in (1, 2)]
    docs.append({"content": body, "url": "https://issuer.example/3.pdf"})
    extract = MagicMock()
    monkeypatch.setattr(disclosure_financial_facts, "extract_financial_facts", extract)
    agent._extract_document_facts(docs, "300750.SZ", ["operating_cash_flow"], {"kind": "fiscal_year"}, "发行人")
    extract.assert_not_called()


def test_frontmatter_publication_date_is_historical_but_fiscal_year_stays_unknown():
    docs = DeepSearchAgent._mark_document_time([
        {"content": "[Page 1]\n研究报告\n2019年10月22日\n正文", "fetched_at": "2026-10-08"},
        {"content": "2024年度报告\n报告期截至2024年12月31日", "fetched_at": "2026-10-08"},
        {"content": "Published: 2026-09-02\n本文内容"},
        {"content": "Published on October 22, 2024\nAnnual research"},
    ], {"selection": "latest_complete", "as_of": "2026-10-08"})
    assert docs[0]["published_at"] == "2019-10-22" and docs[0]["temporal_role"] == "historical"
    assert docs[1]["source_time_status"] == "unknown" and docs[1]["published_at"] is None
    assert docs[2]["published_at"] == "2026-09-02" and "temporal_role" not in docs[2]
    assert docs[3]["published_at"] == "2024-10-22" and docs[3]["temporal_role"] == "historical"
    assert docs[0]["fetched_at"] == "2026-10-08"
