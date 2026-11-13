"""就业存量月差、报告月份与真实发布时间的隔离回归。"""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.tools import macro, macro_official


def _fred_source(monkeypatch, *, payroll=None, unemployment_month="2026-09-01", payroll_units="Thousands of Persons"):
    calls = []
    monkeypatch.setattr(macro, "FRED_API_KEY", "fixture-key")
    payroll = payroll or [{"date": "2026-09-01", "value": "159250"}, {"date": "2026-08-01", "value": "159000"}]
    def fetch(url, *, params, **kwargs):
        calls.append((url, deepcopy(params)))
        sid = params["series_id"]
        if url.endswith("/series"):
            data = {"seriess": [{"id": sid, "frequency": "Monthly", "seasonal_adjustment": "Seasonally Adjusted",
                "units": payroll_units if sid == "PAYEMS" else "Percent", "last_updated": "2026-10-02 07:45:00-05:00"}]}
        else:
            data = {"observations": payroll if sid == "PAYEMS" else [{"date": unemployment_month, "value": "4.3"}]}
        return SimpleNamespace(status_code=200, json=lambda: deepcopy(data))
    monkeypatch.setattr(macro, "_http_get", fetch)
    return calls


def test_payems_adjacent_level_difference_is_people_not_level_or_percent(monkeypatch):
    calls = _fred_source(monkeypatch)
    payload = macro.get_fred_data(indicators=["nonfarm_payroll_change", "unemployment"], as_of="2026-10-04")
    assert payload["nonfarm_payroll_change"] == 250_000
    assert payload["unemployment"] == 4.3
    metadata = payload["indicator_metadata"]["nonfarm_payroll_change"]
    assert (metadata["report_month"], metadata["period_end"], metadata["unit"]) == ("2026-09", "2026-09-30", "persons")
    assert metadata["observation_date"] == "2026-09-01"
    assert metadata["published_at"] is None
    assert metadata["source_updated_at"] == "2026-10-02T12:45:00+00:00"
    assert metadata["timestamp_semantics"] == "source_update"
    assert len(metadata["derivation_inputs"]) == 2
    assert payload["employment_report"]["periods_match"] is True
    assert payload["employment_report"]["published_at"] is None
    assert "fixture-key" not in str(payload)
    assert all(params["realtime_start"] == "2026-10-04" for _, params in calls)
    assert "250,000 人" in payload["nonfarm_payroll_change_formatted"]


@pytest.mark.parametrize("payroll", [
    [{"date": "2026-09-01", "value": "159250"}],
    [{"date": "2026-09-01", "value": "159250"}, {"date": "2026-07-01", "value": "159000"}],
    [{"date": "2026-09-01", "value": "."}, {"date": "2026-08-01", "value": "159000"}],
])
def test_missing_latest_or_adjacent_month_does_not_substitute_older_gain(monkeypatch, payroll):
    _fred_source(monkeypatch, payroll=payroll)
    result = macro.get_fred_data(indicators=["nonfarm_payroll_change", "unemployment"])
    assert result["nonfarm_payroll_change"] is None
    assert "nonfarm_payroll_change" in result["metric_gaps"]
    assert result["unemployment"] == 4.3


def test_payroll_unit_not_confirmed_cannot_be_assumed_thousands(monkeypatch):
    _fred_source(monkeypatch, payroll_units="Persons")
    result = macro.get_fred_data(indicators=["nonfarm_payroll_change"])
    assert result["nonfarm_payroll_change"] is None
    assert "nonfarm_payroll_change" in result["metric_gaps"]


def test_mismatched_latest_months_are_two_facts_not_one_employment_report(monkeypatch):
    _fred_source(monkeypatch, unemployment_month="2026-08-01")
    result = macro.get_fred_data(indicators=["nonfarm_payroll_change", "unemployment"])
    assert result["employment_report"]["periods_match"] is False
    assert result["employment_report"]["report_month"] is None
    assert "report_month_alignment" in result["employment_report"]["missing_metrics"]
    assert result["indicator_metadata"]["unemployment"]["report_month"] == "2026-08"


def test_default_six_series_contract_does_not_start_extra_employment_requests(monkeypatch):
    calls = _fred_source(monkeypatch)
    result = macro.get_fred_data()
    assert len(calls) == 6
    assert "nonfarm_payroll_change" not in result
    assert not any(params["series_id"] == "PAYEMS" for _, params in calls)


def _bls_body():
    return ("Transmission of material in this news release is embargoed until 8:30 a.m. (ET) Friday, October 2, 2026\n"
        "THE EMPLOYMENT SITUATION -- SEPTEMBER 2026\n"
        "Total nonfarm payroll employment rose by 250,000 in September, and the unemployment rate remained at 4.3 percent.\n"
        + "This news release presents statistics from two monthly surveys, household and establishment. " * 4)


def _release():
    return {"title": "Employment Situation", "url": "https://www.bls.gov/news.release/empsit.nr0.htm", "source": "BLS",
        "published_date": "2026-10-02T12:30:00Z", "domain": "bls.gov", "is_official": True}


def test_bls_real_body_preserves_publication_time_month_and_survey_units(monkeypatch):
    rows = [_release(), {**_release(), "url": "https://www.bls.gov/news.release/archives/empsit_old.htm", "published_date": "2026-09-04T12:30:00Z"}]
    monkeypatch.setattr(macro_official, "search_official_macro_releases", lambda *args, **kwargs: deepcopy(rows))
    calls = []
    def document(url, **kwargs):
        calls.append(url)
        return {"final_url": url, "content": _bls_body()}
    monkeypatch.setattr(macro_official, "fetch_url_document", document)
    result = macro_official.get_official_macro_releases("就业报告", include_content=True)
    assert len(calls) == 1
    item = result["releases"][0]
    assert item["content_read"] is True
    report = item["employment_report"]
    assert report["report_month"] == "2026-09"
    assert report["published_at"] == "2026-10-02T12:30:00+00:00"
    assert report["nonfarm_payroll_change"] == 250_000
    assert report["unemployment"] == 4.3
    assert item["structured_data"]["body"] == _bls_body()
    assert result["releases"][1]["content_read"] is False


def test_rss_publication_without_actual_body_does_not_become_verified_report(monkeypatch):
    monkeypatch.setattr(macro_official, "search_official_macro_releases", lambda *args, **kwargs: [_release()])
    monkeypatch.setattr(macro_official, "fetch_url_document", lambda *args, **kwargs: None)
    result = macro_official.get_official_macro_releases("employment", include_content=True)
    assert result["releases"][0]["content_read"] is False
    assert result["releases"][0]["employment_report"] is None


def _agent_tools(fred, official=None):
    return SimpleNamespace(get_fred_data=fred, get_official_macro_releases=official or (lambda **kwargs: {"releases": []}),
        get_market_sentiment=lambda: "", get_economic_events=lambda: "", search=lambda query: "")


def test_fred_selector_and_official_body_flags_registered_for_direct_planning():
    from backend.langchain_tools import get_tool_by_name
    assert get_tool_by_name("get_fred_data").args_schema(indicators=["nonfarm_payroll_change", "unemployment"]).indicators
    assert get_tool_by_name("get_official_macro_releases").args_schema(include_content=True).include_content
