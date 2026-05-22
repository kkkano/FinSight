# -*- coding: utf-8 -*-
import pytest

from backend.tools.python_compute import run_python_compute
from backend.tools.python_sandbox import PythonComputeRejected, validate_compute_request


def test_python_compute_growth_rates_from_quarterly_facts():
    result = run_python_compute(
        dataset_refs=["step:get_sec_company_facts_quarterly"],
        operation="growth_rates",
        params={"metric": "revenue"},
        datasets={
            "step:get_sec_company_facts_quarterly": {
                "quarterly": [
                    {"period": "2025Q1", "revenue": 100.0, "net_income": 20.0},
                    {"period": "2025Q2", "revenue": 130.0, "net_income": 26.0},
                ]
            }
        },
    )

    assert result["metrics"]["revenue_growth_pct"] == 30.0
    assert result["tables"][0]["columns"] == ["period", "revenue", "growth_pct"]
    assert result["input_refs"] == ["step:get_sec_company_facts_quarterly"]
    assert result["code_hash"]
    assert result["duration_ms"] >= 0


def test_python_compute_valuation_sanity_uses_existing_datasets_only():
    result = run_python_compute(
        dataset_refs=["step:get_stock_price", "step:get_company_info", "step:get_sec_company_facts_quarterly"],
        operation="valuation_sanity",
        params={"shares_outstanding": 100.0},
        datasets={
            "step:get_stock_price": {"price": 50.0},
            "step:get_company_info": {"marketCap": 5000.0},
            "step:get_sec_company_facts_quarterly": {
                "quarterly": [
                    {"period": "2025Q1", "revenue": 100.0, "net_income": 10.0},
                    {"period": "2025Q2", "revenue": 125.0, "net_income": 15.0},
                ]
            },
        },
    )

    assert result["metrics"]["market_cap"] == 5000.0
    assert result["metrics"]["annualized_revenue"] == 500.0
    assert result["metrics"]["price_to_sales"] == 10.0
    assert result["metrics"]["price_to_earnings"] == pytest.approx(83.3333, rel=0.0001)
    assert result["metrics"]["revenue_growth_pct"] == 25.0
    assert result["tables"][0]["name"] == "valuation_sanity"


def test_python_compute_rejects_arbitrary_code_payloads():
    with pytest.raises(PythonComputeRejected):
        validate_compute_request(
            dataset_refs=["step:get_stock_price"],
            operation="valuation_sanity",
            params={"code": "import socket; socket.create_connection(('example.com', 80))"},
        )


def test_python_compute_rejects_unknown_operation():
    result = run_python_compute(
        dataset_refs=["step:get_stock_price"],
        operation="download_latest_data",
        params={},
        datasets={"step:get_stock_price": {"price": 50.0}},
    )

    assert result["error"] == "python_compute_rejected"
    assert "unsupported operation" in result["warnings"][0]
