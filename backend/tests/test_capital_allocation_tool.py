"""资本分配的期间、来源与净股数合同回归。"""
from copy import deepcopy

import pytest

from backend.tools import capital_allocation as capital


def _entry(value, start="2025-07-01", end="2026-06-30", filed="2026-07-30", accession="annual", form="10-K"):
    row = {"val": value, "end": end, "filed": filed, "accn": accession, "form": form}
    if start:
        row["start"] = start
    return row


def _payload():
    rows = {"NetCashProvidedByUsedInOperatingActivities": 1000,
        "PaymentsToAcquirePropertyPlantAndEquipment": 500,
        "PaymentsOfDividendsCommonStock": 200, "PaymentsForRepurchaseOfCommonStock": 400}
    gaap = {key: {"units": {"USD": [_entry(value),
        _entry(value * .75, end="2026-03-31", filed="2026-04-30", accession="q3", form="10-Q")]}}
        for key, value in rows.items()}
    gaap["CommonStockSharesOutstanding"] = {"units": {"shares": [
        _entry(100, None, "2025-06-30", "2025-07-30", "previous-year"),
        _entry(97, None)]}}
    return {"cik": 789019, "facts": {"us-gaap": gaap}}


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "FinSight test@example.com")
    monkeypatch.setattr(capital.sec, "_load_ticker_map", lambda _: {"MSFT": {"title": "Microsoft", "cik": "0000789019"}})
    payload = _payload()
    monkeypatch.setattr(capital.sec, "_fetch_companyfacts", lambda *_: deepcopy(payload))
    return payload


def test_four_quarter_cash_flows_derive_same_interval_and_compute_surplus(source):
    result = capital.get_sec_capital_allocation("MSFT", as_of="2026-10-04T09:31:00Z")
    assert result["error"] is None
    assert (result["period_start"], result["period_end"]) == ("2026-04-01", "2026-06-30")
    assert result["operating_cash_flow"] == 250
    assert result["capital_expenditure"] == 125
    assert result["dividends_paid"] == 50
    assert result["repurchases_paid"] == 100
    assert result["capital_allocation_surplus"] == -25
    assert result["dividend_coverage"] == 2.5
    for key in capital._CASH_METRICS:
        fact = result["facts"][key]
        assert fact["frequency"] == "quarterly"
        assert fact["unit"] == "USD"
        assert [row["accession"] for row in fact["derivation_inputs"]] == ["annual", "q3"]


def test_annual_cash_and_same_basis_fiscal_year_end_net_shares(source):
    result = capital.get_sec_capital_allocation("MSFT", "annual", "2026-10-04T09:31:00Z")
    assert result["repurchases_paid"] == 400
    assert result["capital_allocation_surplus"] == -100
    assert result["shares_outstanding"] == 97
    assert result["net_share_change"] == -3
    assert result["share_count_change"]["net_reduction"] == 3
    assert result["share_count_change"]["start"]["period_end"] == "2025-06-30"
    assert result["share_count_change"]["end"]["period_end"] == "2026-06-30"
    assert result["facts"]["net_share_change"]["unit"] == "shares"
    assert result["net_share_change_record"]["value"] == -3


@pytest.mark.parametrize("bad", ["missing", "other_start", "eur", "authorization_only"])
def test_missing_or_incompatible_repurchases_never_become_zero_or_coverage(source, bad):
    gaap = source["facts"]["us-gaap"]
    concept = "PaymentsForRepurchaseOfCommonStock"
    if bad == "missing":
        del gaap[concept]
    elif bad == "authorization_only":
        gaap["StockRepurchaseProgramAuthorizedAmount"] = gaap.pop(concept)
    elif bad == "eur":
        gaap[concept]["units"] = {"EUR": gaap[concept]["units"]["USD"]}
    else:
        gaap[concept]["units"]["USD"][-1]["start"] = "2025-01-01"
    result = capital.get_sec_capital_allocation("MSFT", as_of="2026-10-04T09:31:00Z")
    assert result["repurchases_paid"] is None
    assert result["capital_allocation_surplus"] is None
    assert "repurchases_paid" in result["missing_metrics"]


def test_weighted_average_and_cover_page_shares_are_not_fiscal_year_end_outstanding(source):
    shares = source["facts"]["us-gaap"].pop("CommonStockSharesOutstanding")
    source["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"] = shares
    source["facts"]["dei"] = {"EntityCommonStockSharesOutstanding": shares}
    result = capital.get_sec_capital_allocation("MSFT", "annual", "2026-10-04T09:31:00Z")
    assert result["net_share_change"] is None
    assert result["shares_outstanding"] is None
    assert "net_share_change" in result["missing_metrics"]


def test_issuer_mismatch_rejected(source):
    source["cik"] = 320193
    result = capital.get_sec_capital_allocation("MSFT", "annual", "2026-10-04T09:31:00Z")
    assert result["error"] == "issuer_mismatch"
    assert not result["facts"]


def test_as_of_excludes_future_and_same_date_filings(source):
    result = capital.get_sec_capital_allocation("MSFT", "annual", "2026-07-30T09:31:00Z")
    assert result["error"] == "no_disclosed_period"


def test_cash_output_declares_equity_scope_and_does_not_claim_announced_dividend(source):
    result = capital.get_sec_capital_allocation("MSFT", "annual", "2026-10-04T09:31:00Z")
    assert result["facts"]["dividends_paid"]["concept"] == "PaymentsOfDividendsCommonStock"
    assert "announced_dividend" not in result
    assert result["structured_data"]["facts"] == result["facts"]
    assert result["facts"]["dividends_paid"]["payment_scope"] == "common_equity"


@pytest.mark.parametrize("concept,metric", [
    ("PaymentsOfDividendsCommonStock", "dividends_paid"),
    ("PaymentsForRepurchaseOfCommonStock", "repurchases_paid"),
])
def test_distribution_difference_cannot_mix_a_new_amendment_with_old_predecessor(source, concept, metric):
    entries = source["facts"]["us-gaap"][concept]["units"]["USD"]
    entries.append(dict(entries[0], val=999, filed="2026-08-10", form="10-K/A", accn="amendment"))
    result = capital.get_sec_capital_allocation("MSFT", as_of="2026-10-04T09:31:00Z")
    assert result[metric] is None
    assert result["capital_allocation_surplus"] is None


def test_prior_cover_page_date_is_not_a_comparable_fiscal_year_end(source):
    entries = source["facts"]["us-gaap"]["CommonStockSharesOutstanding"]["units"]["shares"]
    entries[0]["end"] = "2025-07-25"
    result = capital.get_sec_capital_allocation("MSFT", "annual", "2026-10-04T09:31:00Z")
    assert result["net_share_change"] is None
    assert "net_share_change" in result["missing_metrics"]


def test_both_tools_have_langchain_registry_and_constrained_schemas():
    from backend.langchain_tools import get_tool_by_name
    price = get_tool_by_name("get_price_window_metrics")
    cash = get_tool_by_name("get_sec_capital_allocation")
    assert price and cash
    with pytest.raises(ValueError):
        price.args_schema(ticker="SPY", metrics=["five_days_magic"])
    with pytest.raises(ValueError):
        cash.args_schema(ticker="MSFT", frequency="YTD")


def test_explicit_date_cutoff_includes_filings_on_that_day(source):
    result = capital.get_sec_capital_allocation("MSFT", "annual", "2026-07-30")
    assert result["error"] is None
    assert result["repurchases_paid"] == 400


def _debt_source(source):
    gaap = source["facts"]["us-gaap"]
    for concept, value in {"LongTermDebtCurrent": 10, "LongTermDebtNoncurrent": 100,
        "CashAndCashEquivalentsAtCarryingValue": 30}.items():
        gaap[concept] = {"units": {"USD": [_entry(value, None)]}}


def test_debt_burden_verified_same_filing_end_balances_have_explicit_limited_basis(source):
    _debt_source(source)
    result = capital.get_sec_capital_allocation("MSFT", "annual", "2026-10-04")
    burden = result["debt_burden"]
    assert burden["complete_for_definition"] is True
    assert burden["long_term_debt_component_sum"] == 110
    assert burden["long_term_debt_minus_cash"] == 80
    assert "total_debt" not in burden
    assert burden["industrial_financial_subsidiary_split"] is None
    assert "debt_burden" not in result["missing_metrics"]
    assert all(fact["period_end"] == "2026-06-30" for fact in burden["components"].values())


@pytest.mark.parametrize("bad", ["different_period", "different_unit", "different_filing", "missing_noncurrent"])
def test_debt_balance_mismatch_keeps_partial_components_without_net_debt_claim(source, bad):
    _debt_source(source)
    gaap = source["facts"]["us-gaap"]
    rows = gaap["LongTermDebtNoncurrent"]["units"]["USD"]
    if bad == "different_period":
        rows[0]["end"] = "2026-03-31"
    elif bad == "different_unit":
        gaap["LongTermDebtNoncurrent"]["units"] = {"EUR": rows}
    elif bad == "different_filing":
        rows[0]["accn"] = "other-filing"
    else:
        del gaap["LongTermDebtNoncurrent"]
    result = capital.get_sec_capital_allocation("MSFT", "annual", "2026-10-04")
    assert result["debt_burden"]["complete_for_definition"] is False
    assert result["debt_burden"]["long_term_debt_minus_cash"] is None
    assert "debt_burden" in result["missing_metrics"]
