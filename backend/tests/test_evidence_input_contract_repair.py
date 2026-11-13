"""原供应商事实通过新信封与来源账本时，正文和原始口径不可丢失。"""
from copy import deepcopy

import pytest

from backend.agent_runtime.adapters import adapt_result
from backend.agent_runtime.data import RunData


@pytest.mark.parametrize("tool,payload", [
    ("get_company_info", {"ticker": "TEST_A", "businessSummary": "生产半导体设备", "currency": "HKD", "marketCap": 4_000_000_000,
                          "source_url": "https://example.invalid/profile", "source": "fixture"}),
    ("get_sec_filings", {"filings": [{"form": "10-K", "content": "原报告正文：营业收入204779123456.78元。",
                                    "url": "https://example.invalid/10k", "filing_date": "2026-03-01"}]}),
    ("get_company_news", {"news": [{"title": "已取得的报道", "url": "https://example.invalid/news",
                                   "published_at": "2026-03-01", "event_quality": {"verification": "discovery_only"}}],
                          "applied_max_age_hours": 48}),
    ("get_event_calendar", {"events": [], "requested_days_ahead": 30, "observed_window": None}),
    ("get_stock_price", {"price": 42.25, "currency": "USD", "as_of": "2026-03-01", "session": "closed",
                         "source_time_precision": "date", "source": "fixture"}),
])
def test_supplier_fact_fields_survive_adapter_and_authoritative_data_record(tool, payload):
    before = deepcopy(payload)
    envelope = adapt_result(tool, payload, {"ticker": "TEST_A"})
    data = RunData("fixture-owner", "fixture-session", "fixture-run", "保留原始资料")
    reference = data.record(tool, {"ticker": "TEST_A"}, envelope.data, envelope=envelope)
    assert payload == before
    assert data.records[reference]["output"] == before
    if "as_of" in payload:
        assert envelope.as_of is None  # 日期精度不伪造成午夜时间。


def test_financial_amount_and_filing_identity_do_not_round_or_inherit_other_issuer():
    fact = {"subject": "0700.HK", "metric": "revenue", "value": 204_779_123_456.78,
            "currency": "CNY", "unit": "CNY", "frequency": "quarterly", "period_end": "2026-06-30",
            "source_url": "https://example.invalid/report.pdf", "page": 42}
    payload = {"filings": [{"title": "公告索引", "url": fact["source_url"]}], "financial_facts": [fact]}
    envelope = adapt_result("get_local_market_filings", payload, {"ticker": "NVDA"})
    assert envelope.data["financial_facts"] == [fact]
    assert envelope.data["financial_facts"][0]["value"] == 204_779_123_456.78
    assert envelope.data["financial_facts"][0]["subject"] == "0700.HK"
    assert "value" not in envelope.data["filings"][0]
