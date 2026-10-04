"""SEC 公开现金流观察值的无网络回归；衍生季度必须保留两份申报来源。"""
from copy import deepcopy

import pytest

from backend.tools import sec


OCF = "NetCashProvidedByUsedInOperatingActivities"
CAPEX = "PaymentsToAcquirePropertyPlantAndEquipment"
ALT_OCF = "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"


def _entry(value, start, end, filed, accession, *, form="10-Q"):
    return {"val": value, "start": start, "end": end, "filed": filed, "accn": accession, "form": form}


def _ma_rows():
    return [
        _entry(2_999_000_000, "2026-01-01", "2026-03-31", "2026-04-30", "0001141391-26-000031"),
        _entry(6_772_000_000, "2026-01-01", "2026-06-30", "2026-07-30", "0001141391-26-000083"),
    ]


def _payload(concepts):
    return {"facts": {"us-gaap": {name: {"units": {"USD": rows}} for name, rows in concepts.items()}}}


def _extract(payload, *, concepts=(OCF,), metric="operating_cash_flow", subject="MA", units=("USD",)):
    return sec._extract_companyfacts_facts(payload, concepts=concepts, unit_candidates=units,
        subject=subject, metric=metric, source_url=f"https://data.sec.gov/api/xbrl/companyfacts/{subject}.json")


@pytest.mark.parametrize("reverse", [False, True])
def test_ma_observed_ytd_difference_keeps_actual_quarter_and_both_filings(reverse):
    rows = _ma_rows()
    facts = _extract(_payload({OCF: list(reversed(rows)) if reverse else rows}))
    fact = facts["2026-06-30"]
    assert fact.value == 3_773_000_000
    assert (fact.period_start, fact.period_end, fact.frequency, fact.subject, fact.unit) == (
        "2026-04-01", "2026-06-30", "quarterly", "MA", "USD",
    )
    metadata = fact.metadata()
    assert metadata["derivation"] == "ytd_difference"
    assert [item["accession"] for item in metadata["derivation_inputs"]] == [rows[1]["accn"], rows[0]["accn"]]
    assert [item["value"] for item in metadata["derivation_inputs"]] == [6_772_000_000, 2_999_000_000]
    assert all(item["concept"] == OCF and item["period_start"] == "2026-01-01" for item in metadata["derivation_inputs"])


def test_visa_fiscal_year_spanning_calendar_year_preserves_march_latest():
    rows = [
        _entry(6_780_000_000, "2025-10-01", "2025-12-31", "2026-01-30", "0001403161-26-000045"),
        _entry(9_788_000_000, "2025-10-01", "2026-03-31", "2026-04-29", "0001403161-26-000079"),
    ]
    facts = _extract(_payload({OCF: rows}), subject="V")
    assert facts["2026-03-31"].value == 3_008_000_000
    assert facts["2026-03-31"].period_start == "2026-01-01"
    assert max(facts) == "2026-03-31"


def test_direct_quarter_takes_priority_over_ytd_and_conflicting_direct_is_not_bypassed():
    rows = _ma_rows() + [_entry(3_800_000_000, "2026-04-01", "2026-06-30", "2026-07-30", "direct-quarter")]
    assert _extract(_payload({OCF: rows}))["2026-06-30"].value == 3_800_000_000
    rows.append({**rows[-1], "val": 3_810_000_000})
    assert "2026-06-30" not in _extract(_payload({OCF: rows}))


@pytest.mark.parametrize("change", ["other_fiscal_start", "missing_adjacent", "different_concept", "different_unit"])
def test_ytd_difference_rejects_incompatible_inputs(change):
    rows = _ma_rows()
    payload = _payload({OCF: rows})
    if change == "other_fiscal_start":
        rows[0]["start"] = "2025-01-01"
    elif change == "missing_adjacent":
        rows[1]["end"] = "2026-09-30"
    elif change == "different_concept":
        payload = _payload({OCF: [rows[1]], ALT_OCF: [rows[0]]})
    else:
        payload["facts"]["us-gaap"][OCF]["units"] = {"USD": [rows[1]], "EUR": [rows[0]]}
    facts = _extract(payload, concepts=(OCF, ALT_OCF), units=("USD", "EUR"))
    assert rows[1]["end"] not in facts


@pytest.mark.parametrize("revision", ["prior_after_current", "current_amended", "prior_recast", "conflicting_latest"])
def test_ytd_difference_never_mixes_corrections_with_another_filing_version(revision):
    rows = _ma_rows()
    if revision == "prior_after_current":
        rows.append({**rows[0], "val": 3_100_000_000, "filed": "2026-08-01", "form": "10-Q/A", "accn": "q1-amended"})
    elif revision == "current_amended":
        rows.append({**rows[1], "val": 6_800_000_000, "filed": "2026-08-01", "form": "10-Q/A", "accn": "q2-amended"})
    elif revision == "prior_recast":
        rows.append({**rows[0], "val": 3_100_000_000, "filed": "2026-07-01", "accn": "q1-recast"})
    else:
        rows.append({**rows[1], "val": 6_800_000_000})
    assert "2026-06-30" not in _extract(_payload({OCF: rows}))


def test_same_amended_filing_can_supply_both_consistent_endpoints():
    rows = _ma_rows()
    rows += [dict(row, val=value, filed="2026-08-01", accn="same-amendment", form="10-Q/A")
        for row, value in zip(deepcopy(rows), (3_100_000_000, 6_800_000_000))]
    fact = _extract(_payload({OCF: rows}))["2026-06-30"]
    assert fact.value == 3_700_000_000
    assert {row["accession"] for row in fact.metadata()["derivation_inputs"]} == {"same-amendment"}


def test_annual_minus_nine_month_cash_flow_has_real_q4_interval():
    rows = [
        _entry(12_646_000_000, "2025-01-01", "2025-09-30", "2025-10-30", "0001141391-25-000193"),
        _entry(17_648_000_000, "2025-01-01", "2025-12-31", "2026-02-11", "0001141391-26-000013", form="10-K"),
    ]
    fact = _extract(_payload({OCF: rows}))["2025-12-31"]
    assert (fact.value, fact.period_start) == (5_002_000_000, "2025-10-01")


def test_eps_is_never_derived_even_with_matching_cumulative_intervals():
    payload = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": _ma_rows()}}}}}
    facts = _extract(payload, concepts=("EarningsPerShareDiluted",), metric="eps", units=("USD/shares",))
    assert "2026-06-30" not in facts


def test_cash_flow_output_keeps_capex_basis_and_source_as_of(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "FinSight test@example.com")
    monkeypatch.setattr(sec, "_load_ticker_map", lambda _: {"MA": {"cik": "0001141391", "title": "Mastercard"}})
    capex = [dict(row, val=value) for row, value in zip(_ma_rows(), (154_000_000, 445_000_000))]
    payload = _payload({OCF: _ma_rows(), CAPEX: capex,
        "PaymentsToAcquireSoftware": [dict(row, val=value) for row, value in zip(_ma_rows(), (181_000_000, 368_000_000))]})
    monkeypatch.setattr(sec, "_fetch_companyfacts", lambda *_: payload)
    result = sec.get_sec_company_facts_quarterly("MA")
    assert result["periods"][0] == "2026-06-30"
    assert result["source_latest_filed"] == "2026-07-30"
    assert result["operating_cash_flow"][0] == 3_773_000_000
    assert result["free_cash_flow"][0] == 3_482_000_000
    metadata = result["fact_metadata"]["free_cash_flow"][0]
    assert metadata["capital_expenditures_concept"] == CAPEX
    assert [row["concept"] for row in metadata["derivation_inputs"]] == [OCF, CAPEX]
    assert all(len(row["derivation_inputs"]) == 2 for row in metadata["derivation_inputs"])


def test_productive_assets_is_not_silently_relabelled_as_ppe():
    facts = _extract(_payload({"PaymentsToAcquireProductiveAssets": _ma_rows()}),
        concepts=sec._COMPANYFACTS_METRIC_MAP["capital_expenditures"][0], metric="capital_expenditures", subject="V")
    assert facts == {}
