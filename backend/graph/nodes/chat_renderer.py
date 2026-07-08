# -*- coding: utf-8 -*-
"""兼容 shim（WP3 Task1）：chat_renderer 已拆分至 backend/graph/renderers/ 注册表包。

旧 import 路径（backend.graph.nodes.chat_renderer.X）全部由本文件 re-export 兜住，
至少保留一个发布周期（WP3 收尾任务统一删 shim 并全局改 import）。

注意：monkeypatch 需打到符号的新家（如 backend.graph.renderers.news_fallback.get_company_news），
patch 本 shim 的名字不会传导——详见 notes-chat-renderer-map.md 兼容性事项。
"""
from backend.graph.renderers.registry import (  # noqa: F401
    OPERATION_LABELS,
    RENDERERS,
    build_render_ctx,
    enrich_render_ctx,
    render_chat_markdown,
    render_task_sections,
    _task_section_state,
    _with_existing_prefixes,
)
from backend.graph.renderers.shared import (  # noqa: F401
    FORBIDDEN_CHAT_MARKERS,
    _append_blocked_notes,
    _append_render_var_block,
    _append_sources,
    _blocked_tasks,
    _case_insensitive_get,
    _company_identity_tokens,
    _finalize_chat_markdown,
    _first_matching_output,
    _format_number,
    _has_contract_facet,
    _intent_contract,
    _is_citable_url,
    _operation_names,
    _parse_jsonish,
    _risk_or_qa_fallback_lines,
    _sanitize_chat_markdown,
    _step_outputs,
    _subject_types,
    _task_index,
    _tasks,
    _ticker_for_step,
    _tickers,
    _understanding_v2,
    _v2_profiles,
)
from backend.graph.renderers.synthesis_vars import (  # noqa: F401
    _agent_risks,
    _agent_summary,
    _format_compact_number,
    _python_compute_metric_lines,
    _render_vars,
    _sanitize_agent_summary,
    _successful_synthesis_render_vars,
    _synthesis_points,
    _useful_render_var,
)
from backend.graph.renderers.price import (  # noqa: F401
    _extract_price,
    _format_price_line,
    _price_change_pct,
    _prices_by_ticker,
    render_price_only,
)
from backend.graph.renderers.news_items import (  # noqa: F401
    COMPANY_MAP,
    _TICKER_CODE_RE,
    _company_name_for_ticker,
    _dedupe_news_items,
    _is_low_value_evidence_item,
    _is_low_value_search_item,
    _is_real_ticker,
    _news_item_matches_subject,
    _news_items,
)
from backend.graph.renderers.news_fallback import (  # noqa: F401
    _append_news_source_page_links,
    _direct_news_article_fallback_map,
    _news_article_fallback_allowed,
    _news_article_fallback_budget_seconds,
    _news_article_fallback_max_tickers,
    _news_search_fallback_items,
    get_authoritative_media_news,
    get_company_news,
)
from backend.graph.renderers.news_snapshot import (  # noqa: F401
    _extract_full_snapshot,
    _is_snapshot_news_item,
    _parse_snapshot_text,
    _render_news_brief_block,
)
from backend.graph.renderers.news import (  # noqa: F401
    _append_missing_article_url_note,
    _evidence_items,
    _filter_news_by_company_identity,
    _format_news_item,
    _news_by_ticker,
    _news_map_has_citable_url,
    _reply_contract_requires_links,
    _requested_news_link_count,
    _search_item_from_output,
    render_news_impact,
)
from backend.graph.renderers.holdings import (  # noqa: F401
    _format_compact_usd_thousands,
    _format_holdings_number,
    _render_holdings_markdown,
    _request_requires_holdings,
    render_holdings,
)
from backend.graph.renderers.earnings import (  # noqa: F401
    _earnings_expectation_lines,
    _latest_quarter_facts,
    _local_filing_fact_lines,
    _render_earnings_impact_markdown,
    _render_earnings_performance_markdown,
    render_earnings_impact,
    render_earnings_performance,
)
from backend.graph.renderers.valuation import (  # noqa: F401
    _render_valuation_sanity_markdown,
    render_valuation_sanity,
)
from backend.graph.renderers.opinion import (  # noqa: F401
    _investment_opinion_bias,
    _render_investment_opinion_markdown,
    render_investment_opinion,
)
from backend.graph.renderers.portfolio import (  # noqa: F401
    _portfolio_positions,
    _render_portfolio_markdown,
    render_portfolio,
)
from backend.graph.renderers.compare import (  # noqa: F401
    _render_compare_or_basket_markdown,
    _render_research_compare_markdown,
    _v2_requires_research_compare,
    render_compare,
    render_research_compare,
)
from backend.graph.renderers.macro import (  # noqa: F401
    _external_entity_impact_fallback_lines,
    _focus_line,
    _focus_task_present,
    _has_macro_context,
    _macro_impact_fallback_lines,
    _macro_mechanism_lines,
)
from backend.graph.renderers.url_fetch import (  # noqa: F401
    _append_url_fetch_notes,
    _has_url_context,
    _url_fetch_all_failed,
    _url_fetch_rows,
    render_url_context,
)
from backend.graph.renderers.misc import (  # noqa: F401
    _technical_action_line,
    _technical_by_ticker,
    _technical_text,
    render_default,
    render_last_report_followup,
    render_technical,
)
