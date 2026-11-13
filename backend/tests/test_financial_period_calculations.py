"""财期、两期计算与展示合同的离线回归，不调用外部服务。"""
from copy import deepcopy

import pytest

from backend.tools import sec
from backend.tools.financial_calculations import calculate_period_change
from backend.agent_runtime.adapters import adapt_result


def fact(value, start, end, **fields):
    return {"subject": "EXM", "metric": "revenue", "value": value, "unit": "USD", "frequency": "quarterly",
        "period_start": start, "period_end": end, "filed": "2026-08-01", "concept": "Revenues",
        "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json", **fields}


@pytest.mark.parametrize("changes", [{"unit": "CNY"}, {"concept": "OtherRevenue"},
    {"period_start": "2025-01-01"}, {"subject": "OTHER"}, {"value": 0}, {"value": -100}])
def test_growth_rejects_incomparable_or_nonpositive_baseline(changes):
    assert calculate_period_change(fact(150, "2026-04-01", "2026-06-30"),
        {**fact(100, "2025-04-01", "2025-06-30"), **changes}, operation="growth_rate", baseline="year_ago") is None


def test_sec_annual_scope_excludes_quarters_and_future_revisions(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "FinSight test@example.com")
    monkeypatch.setattr(sec, "_load_ticker_map", lambda headers: {"EXM": {"cik": "0000000001", "title": "Example"}})
    rows = [
        {"start": "2025-01-01", "end": "2025-12-31", "val": 150, "filed": "2026-02-01", "accn": "annual", "form": "10-K"},
        {"start": "2024-01-01", "end": "2024-12-31", "val": 100, "filed": "2025-02-01", "accn": "prior", "form": "10-K"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 900, "filed": "2026-11-01", "accn": "future", "form": "10-K/A"},
        {"start": "2026-04-01", "end": "2026-06-30", "val": 70, "filed": "2026-08-01", "accn": "quarter", "form": "10-Q"},
    ]
    monkeypatch.setattr(sec, "_fetch_companyfacts", lambda *args: {"cik": 1, "facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}})
    result = sec.get_sec_company_facts_quarterly("EXM", time_scope={"kind": "fiscal_year", "selection": "latest_complete", "as_of": "2026-10-07"},
        calculations=[{"metric": "revenue", "operation": "growth_rate", "baseline": "year_ago"}])
    assert result["error"] is None
    assert result["frequency"] == "annual"
    assert result["selected_period"] == "2025-12-31"
    assert result["revenue"] == [150, 100]
    assert result["calculations"][0]["value"] == .5
    envelope = adapt_result("get_sec_company_facts_quarterly", result, {"ticker": "EXM"})
    assert envelope.data["frequency"] == "annual"
    assert envelope.data["revenue"] == [150, 100]
