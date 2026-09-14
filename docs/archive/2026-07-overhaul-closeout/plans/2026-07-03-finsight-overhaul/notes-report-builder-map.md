# report_builder 拆分迁移地图（WP3 Task 5）

> 原文件：`backend/graph/report_builder.py`（2693 行，全模块级函数）→ 1825 行（payload 组装壳，spec 明示保留）。
> 外部消费面仅 `build_report_payload`（chat_router/execution_service 3 处延迟 import），无 shim 需求。

## 域 → 文件

- **report/citations.py**：_FILING_SECTION_PATTERNS、_TRACKING_QUERY_KEYS、_detect_filing_section_ref、
  _build_filing_section_citations、_canonicalize_url_for_citation_match、_is_suspicious_citation_item、
  _CitationBuild(@dataclass)、_build_citations、_normalize_internal_citation_text、
  _build_internal_citation_key、_build_internal_citation_url
- **report/grounding.py**（原 :1877-2043）：_GROUNDING_CLAIM_PATTERNS、_normalize_for_grounding、
  _extract_grounding_claims、_build_grounding_corpus、_is_claim_grounded、_compute_grounding_stats
- **report/quality_hints.py**（原 :1736 起）：_QUALITY_PROFILES、_infer_market_from_context、_build_report_quality_hints
- **report/agent_formatters.py**：_PRICE_CLAIM_LABELS、_extract_price_behavior_snapshot、
  _format_price_behavior_snapshot、_format_price_agent_claims、_format_price_agent_report_summary、
  **AGENT_REPORT_SUMMARY_FORMATTERS 注册表 + format_agent_report_summary 分发器**
- **report/util.py**：_safe_str、_parse_iso_datetime、_freshness_hours、_safe_confidence、
  _flatten_json_like_line、_sanitize_report_text_block、_classify_report_type（壳与四域共用的叶子工具）

## 注册表接线

`_agent_summaries_from_steps` 内原 `if agent_name == "price_agent"` 专属分支 → 查表：
`format_agent_report_summary(agent_name, output)`（未登记返回 None 走原默认摘要路径，行为保真）。
**spec 草图的 `AgentClaimFormatter -> list[str]` 签名与现实不符**——现网专属格式化只有 price_agent
且返回整段 summary 字符串，注册表按真实签名建（见 Deviations）。

## 已知归档

- ast 提块时 `@dataclass` 装饰器行不在 class.lineno 内——已修（decorator_list 最小行号取块）。
- report_builder 壳 1825 行（spec 允许保留壳；进一步拆分无锚点）。
