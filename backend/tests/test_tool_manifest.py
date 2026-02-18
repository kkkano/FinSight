# -*- coding: utf-8 -*-
from backend.tools.manifest import TOOL_MANIFEST, select_tools


def test_tool_manifest_has_unique_names():
    names = [entry.name for entry in TOOL_MANIFEST]
    assert len(names) == len(set(names))


def test_select_tools_company_technical_includes_snapshot():
    tools = select_tools(
        subject_type="company",
        operation_name="technical",
        output_mode="brief",
        analysis_depth="quick",
        market="US",
    )
    assert "get_stock_price" in tools
    assert "get_technical_snapshot" in tools
    assert "get_option_chain_metrics" in tools


def test_select_tools_market_filter_for_cn_excludes_us_only_tools():
    tools = select_tools(
        subject_type="company",
        operation_name="qa",
        output_mode="brief",
        analysis_depth="report",
        market="CN",
    )
    assert "get_earnings_estimates" not in tools
    assert "get_eps_revisions" not in tools
    assert "get_sec_filings" not in tools
    assert "get_sec_material_events" not in tools
    assert "get_sec_risk_factors" not in tools
    assert "get_stock_price" in tools


def test_select_tools_us_includes_sec_tools_for_company_qa():
    tools = select_tools(
        subject_type="company",
        operation_name="qa",
        output_mode="brief",
        analysis_depth="report",
        market="US",
    )
    assert "get_sec_filings" in tools
    assert "get_sec_material_events" in tools
    assert "get_sec_risk_factors" in tools
