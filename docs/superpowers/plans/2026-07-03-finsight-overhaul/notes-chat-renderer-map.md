# chat_renderer 拆分迁移地图（WP3 Task 1 Step 1）

> 原文件：`backend/graph/nodes/chat_renderer.py`（2708 行 / 97 函数 + 13 模块常量）。
> 结构事实：`render_chat_markdown` 主体是**互斥早退分支链**（每个分支自己 return），不是 spec 草图的 parts.append 拼接。
> 按偏差条款适配：注册表语义 = **first-non-None-wins**（renderer 返回完整 markdown 或 None 让位下一个），
> 顺序 = 原分支出现顺序，逐条对应。原 `lines=[]` 在每个会 append 的分支进入时恒为空（前面分支都早退），
> 故每个 renderer 内部自建 `lines` 与原语义逐字节一致。

## 两阶段 ctx（保持原计算顺序与副作用时点）

- `build_render_ctx(state)`（phase1，= 原函数头 2373-2381 行）：query / ticker_label / operations /
  memory_context / last_report / artifacts / decision / binding / render_vars
- renderer#1（last_report 跟聊）只消费 phase1
- `enrich_render_ctx(ctx, state)`（phase2，= 原 2403-2429 行，含 news_map 的联网 fallback 增补）：
  prices / news_map / requested_link_count / technical_map / price / news / technical / evidence_items /
  price_snapshot / technical_snapshot / news_summary / comparison_conclusion / comparison_metrics /
  conclusion / next_watch / risks / has_url_context
- 其余 renderer 消费完整 ctx

## RENDERERS 顺序表（原分支 → renderer → 归属文件）

| # | 原分支（行号） | renderer | 文件 |
|---|---|---|---|
| 1 | last_report 跟聊（2383） | render_last_report_followup | misc.py |
| 2 | portfolio 任务（2433） | render_portfolio | portfolio.py |
| 3 | URL 上下文（2446） | render_url_context | url_fetch.py |
| 4 | 契约 compare/v2（2484-2495） | render_research_compare | compare.py |
| 5 | earnings_impact（2497） | render_earnings_impact | earnings.py |
| 6 | earnings_performance（2505） | render_earnings_performance | earnings.py |
| 7 | valuation_sanity（2512） | render_valuation_sanity | valuation.py |
| 8 | holdings（2520） | render_holdings | holdings.py |
| 9 | 纯价格（2523） | render_price_only | price.py |
| 10 | compare 操作（2530） | render_compare | compare.py |
| 11 | investment_opinion（2539） | render_investment_opinion | opinion.py |
| 12 | fetch/analyze_impact/news（2548） | render_news_impact | news.py |
| 13 | technical（2650） | render_technical | misc.py |
| 14 | 末端兜底链（2672，恒返回） | render_default | misc.py |

入口 `render_chat_markdown`（registry.py）：先 `render_task_sections`（多问题分节，T10）短路，
再 phase1 → renderer#1 → enrich → 2..14 循环取第一个非 None。

## 函数 → 目标文件（97 项）

### registry.py
render_chat_markdown（重写为查表循环）、render_task_sections、_task_section_state、_with_existing_prefixes

### shared.py（跨桶公共，含常量 FORBIDDEN_CHAT_MARKERS、_TICKER_CODE_RE）
_parse_jsonish、_tasks、_operation_names、_tickers、_step_outputs、_first_matching_output、_format_number、
_is_citable_url、_task_index、_blocked_tasks、_append_blocked_notes、_ticker_for_step、_is_real_ticker、
_render_vars、_useful_render_var、_successful_synthesis_render_vars、_synthesis_points、_subject_types、
_sanitize_agent_summary、_agent_summary、_agent_risks、_python_compute_metric_lines、_format_compact_number、
_case_insensitive_get、_company_identity_tokens、_append_render_var_block、_sanitize_chat_markdown、
_finalize_chat_markdown、_intent_contract、_has_contract_facet、_understanding_v2、_v2_profiles、
_focus_task_present、_focus_line、_append_sources

### price.py
_extract_price、_format_price_line、_price_change_pct、_prices_by_ticker、render_price_only

### news.py（含 try-import 块 COMPANY_MAP/get_authoritative_media_news/get_company_news 与 _SNAPSHOT_* 常量）
_news_items、_is_low_value_search_item、_is_low_value_evidence_item、_search_item_from_output、_evidence_items、
_requested_news_link_count、_reply_contract_requires_links、_news_article_fallback_allowed、
_news_article_fallback_budget_seconds、_news_article_fallback_max_tickers、_news_search_fallback_items、
_append_news_source_page_links、_news_map_has_citable_url、_company_name_for_ticker、_news_item_matches_subject、
_dedupe_news_items、_direct_news_article_fallback_map、_is_snapshot_news_item、_parse_snapshot_text、
_extract_full_snapshot、_render_news_brief_block、_news_by_ticker、_format_news_item、
_append_missing_article_url_note、_filter_news_by_company_identity、render_news_impact

### holdings.py
_request_requires_holdings、_format_compact_usd_thousands、_format_holdings_number、_render_holdings_markdown、render_holdings

### earnings.py
_latest_quarter_facts、_local_filing_fact_lines、_earnings_expectation_lines、
_render_earnings_performance_markdown、_render_earnings_impact_markdown、render_earnings_impact、render_earnings_performance

### valuation.py
_render_valuation_sanity_markdown、render_valuation_sanity

### opinion.py
_investment_opinion_bias、_render_investment_opinion_markdown、_risk_or_qa_fallback_lines、render_investment_opinion

### portfolio.py
_portfolio_positions、_render_portfolio_markdown、render_portfolio

### compare.py
_render_compare_or_basket_markdown、_render_research_compare_markdown、_v2_requires_research_compare、
render_research_compare、render_compare

### macro.py
_has_macro_context、_macro_impact_fallback_lines、_macro_mechanism_lines、_external_entity_impact_fallback_lines

### url_fetch.py
_url_fetch_rows、_append_url_fetch_notes、_url_fetch_all_failed、_has_url_context、render_url_context

### misc.py
_technical_text、_technical_action_line、_technical_by_ticker、
render_last_report_followup、render_technical、render_default

## 兼容性事项

- `chat_renderer.py` 变 shim：显式 re-import 全部公有+私有符号（旧 import 路径不破）。
- **monkeypatch 目标迁移**（shim re-export 无法传导 patch）：`test_chat_response_contract.py` 两处
  `monkeypatch.setattr(chat_renderer, "get_company_news"/"get_authoritative_media_news", ...)`
  → 改 patch `backend.graph.renderers.news`。测试路径更新属机械重构预期，记入 Deviations。
- 生产引用面：仅 `render_stub.py` import `render_chat_markdown`（shim 兜住，不改）。
