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
    assert "get_official_macro_releases" not in tools
    assert "get_local_market_filings" in tools
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
    assert "get_sec_company_facts_quarterly" in tools
    assert "get_official_macro_releases" in tools
    assert "get_authoritative_media_news" in tools
    assert "get_earnings_call_transcripts" in tools


def test_manifest_includes_sec_holdings_metadata():
    entries = {entry.name: entry for entry in TOOL_MANIFEST}
    expected = {
        "get_institutional_holdings",
        "get_institution_holdings_by_ticker",
        "get_insider_transactions",
        "get_holdings_overlap",
    }
    assert expected.issubset(entries)

    for name in expected:
        entry = entries[name]
        assert entry.group == "regulatory"
        assert entry.markets == ("US",)
        assert entry.risk_level == "low"
        assert "SEC_USER_AGENT" in entry.requires_env

    assert "45 days" in entries["get_institutional_holdings"].help_text
    assert "two business days" in entries["get_insider_transactions"].help_text


def test_select_tools_us_includes_sec_holdings_tools_for_deep_company_qa():
    tools = select_tools(
        subject_type="company",
        operation_name="qa",
        output_mode="investment_report",
        analysis_depth="deep_research",
        market="US",
    )
    assert "get_institutional_holdings" in tools
    assert "get_institution_holdings_by_ticker" in tools
    assert "get_insider_transactions" in tools
    assert "get_holdings_overlap" in tools


def test_select_tools_macro_includes_macro_evidence_sources():
    tools = select_tools(
        subject_type="macro",
        operation_name="qa",
        output_mode="brief",
        analysis_depth="report",
        market="US",
    )
    assert "get_official_macro_releases" in tools
    assert "get_authoritative_media_news" in tools
    assert "search" in tools
