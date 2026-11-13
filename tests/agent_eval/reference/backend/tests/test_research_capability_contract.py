"""能力声明与真实财务生产者、期间和口径一致。"""
from backend.graph.research_capabilities import CAPABILITIES, FINANCIAL_INPUTS, financial_metric_inputs
from backend.tools.financial_facts import derive_cash_flow_facts


def test_local_market_financial_capability_only_claims_actual_producer_outputs():
    assert CAPABILITIES["operating_cash_flow"].supports_market("CN")
    assert CAPABILITIES["free_cash_flow"].supports_market("HK")
    assert not CAPABILITIES["net_share_change"].supports_market("CN")
    assert CAPABILITIES["net_share_change"].supports_market("US")
    assert financial_metric_inputs(["free_cash_flow"]) == FINANCIAL_INPUTS["free_cash_flow"]


def test_cash_derivation_preserves_input_provenance_and_cannot_mix_periods_or_bases():
    common = {"subject": "issuer", "period_start": "2025-01-01", "period_end": "2025-12-31",
              "frequency": "annual", "unit": "CNY", "currency": "CNY", "reporting_basis": "consolidated",
              "source_url": "https://example.com/annual.pdf"}
    rows = [{**common, "metric": "operating_cash_flow", "value": 100}, {**common, "metric": "capital_expenditure", "value": 30}]
    result = derive_cash_flow_facts(rows, ["free_cash_flow"])[0]
    assert result["value"] == 70 and result["derivation_inputs"] == rows
    assert not derive_cash_flow_facts([rows[0], {**rows[1], "period_end": "2024-12-31"}], ["free_cash_flow"])
    assert not derive_cash_flow_facts([rows[0], {**rows[1], "reporting_basis": "parent"}], ["free_cash_flow"])
