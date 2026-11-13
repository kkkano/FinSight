"""工具类型在注册时确定；名称是固定协议标识，不用于判断自然语言。"""
from __future__ import annotations


TOOL_KINDS = {
    "get_stock_price": "quote", "get_quote": "quote",
    "get_stock_historical_data": "series", "get_price_history": "series", "get_us_extended_hours": "series",
    "get_fred_data": "series", "get_market_benchmark_history": "series",
    "get_company_news": "news", "search_news": "news", "get_authoritative_media_news": "news",
    "fetch_url_content": "document", "fetch_url": "document", "search": "document", "web_search": "document",
    "get_earnings_call_transcripts": "document", "get_sec_filings": "document", "get_sec_risk_factors": "document",
    "search_knowledge": "document", "search_memory": "document", "read_document": "document",
    "read_selection": "document", "read_evidence": "document", "read_data": "document",
    "get_company_info": "table", "get_company_profile": "table", "get_sec_company_facts_quarterly": "table",
    "get_financials": "table", "get_financial_statements": "table", "get_sec_capital_allocation": "table",
    "get_earnings_estimates": "table", "get_eps_revisions": "table", "get_estimates": "table",
    "get_local_market_filings": "table", "get_sec_material_events": "table", "get_technical_snapshot": "table",
    "get_option_chain_metrics": "table", "get_finra_otc_activity": "table", "get_market_signals": "table",
    "get_market_sentiment": "table", "get_news_sentiment": "table", "get_event_calendar": "table",
    "get_economic_events": "table", "get_official_macro_releases": "table", "get_macro": "table",
    "get_institutional_holdings": "table", "get_institution_holdings_by_ticker": "table",
    "get_insider_transactions": "table", "get_holdings_overlap": "table", "get_watchlist": "control",
    "score_news_source_reliability": "table", "get_relative_strength": "table", "get_factor_exposure": "table",
    "get_performance_comparison": "computation", "get_price_window_metrics": "computation",
    "analyze_historical_drawdowns": "computation", "analyze_dataset": "computation",
    "run_analysis_code": "computation", "run_python_compute": "computation", "run_python": "computation",
    "render_chart": "chart", "render_table": "table", "inspect_dataset": "table",
    "get_current_datetime": "control", "discover_tools": "control", "enable_tools": "control",
    "discover_skills": "control", "use_skill": "control", "load_skill": "control", "update_plan": "control",
    "delegate_research": "control", "await_agent_results": "control", "send_agent_message": "control",
    "spawn_agents": "control", "propose_action": "control", "mark_report": "control", "submit_review": "control",
}

TOOL_LABEL_ALIASES = {
    "get_quote": "get_stock_price", "get_price_history": "get_stock_historical_data",
    "get_financials": "get_sec_company_facts_quarterly", "get_company_profile": "get_company_info",
    "get_estimates": "get_earnings_estimates", "get_macro": "get_fred_data",
    "get_market_signals": "get_market_sentiment", "search_news": "get_company_news",
    "web_search": "search", "fetch_url": "fetch_url_content", "run_python": "run_analysis_code",
    "run_python_compute": "run_analysis_code", "render_table": "inspect_dataset", "read_data": "read_evidence",
    "spawn_agents": "delegate_research", "load_skill": "use_skill",
}
TOOL_LABELS = {"update_plan": "更新研究计划", "submit_review": "提交核查结果"}
