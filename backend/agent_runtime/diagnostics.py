"""面向用户的有界调用详情与受控错误原因；不输出凭据或模型原始推理。"""
from __future__ import annotations

import json
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_PRIVATE = re.compile(r"api.?key|secret|password|authorization|cookie|access.?token|refresh.?token|signature|private.?key|reasoning_content|system_prompt|(?:^|[-_])(?:token|reasoning|reasoning_details)(?:$|[-_])", re.I)
_CREDENTIAL = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|sb_secret_[A-Za-z0-9_-]+|Bearer\s+\S+|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", re.I)

TOOL_TITLES = {
    "discover_tools": "查找研究工具", "enable_tools": "准备研究工具", "read_evidence": "查看已取得的资料",
    "discover_skills": "查找研究技能", "use_skill": "应用研究技能", "read_document": "阅读资料原文",
    "get_current_datetime": "核对当前时间", "get_stock_price": "获取行情", "get_technical_snapshot": "计算技术指标",
    "get_company_news": "读取公司新闻", "get_earnings_estimates": "读取盈利预期", "get_eps_revisions": "读取盈利预期修正",
    "get_sec_company_facts_quarterly": "读取季度财报", "get_company_info": "读取公司资料",
    "get_stock_historical_data": "读取历史行情", "get_market_benchmark_history": "读取市场基准走势",
    "get_event_calendar": "查询事件日历", "get_earnings_call_transcripts": "阅读财报电话会",
    "get_local_market_filings": "读取公司公告", "get_financial_statements": "读取财务报表",
    "get_fred_data": "查询宏观数据", "get_economic_events": "查询经济事件", "get_official_macro_releases": "查询官方宏观发布",
    "get_market_sentiment": "查询市场情绪", "get_news_sentiment": "分析新闻情绪", "get_option_chain_metrics": "读取期权指标",
    "get_relative_strength": "计算相对强弱", "get_factor_exposure": "分析风险因子", "get_performance_comparison": "比较表现",
    "analyze_historical_drawdowns": "分析历史回撤", "search": "搜索公开资料", "fetch_url_content": "阅读网页",
    "search_knowledge": "检索知识库", "search_memory": "检索会话记忆", "read_selection": "阅读选中资料",
    "analyze_dataset": "计算数据指标", "run_analysis_code": "运行隔离计算", "render_chart": "绘制数据图表",
    "delegate_research": "委派专业研究", "await_agent_results": "等待专业研究结果", "send_agent_message": "与研究伙伴交流",
    "mark_report": "整理研究报告", "propose_action": "提出操作请求", "get_watchlist": "读取自选清单",
    "get_us_extended_hours": "读取盘前盘后行情", "get_finra_otc_activity": "读取场外成交数据",
    "inspect_dataset": "查看数据表格",
    "get_authoritative_media_news": "读取权威报道", "get_holdings_overlap": "比较重合持仓",
    "get_insider_transactions": "查看内部人交易", "get_institution_holdings_by_ticker": "查看机构持仓",
    "get_institutional_holdings": "读取机构持仓", "get_price_window_metrics": "计算区间指标",
    "get_sec_capital_allocation": "读取资本配置", "get_sec_filings": "读取监管文件",
    "get_sec_material_events": "读取重大事件", "get_sec_risk_factors": "读取风险披露",
    "score_news_source_reliability": "核验新闻来源",
}

_ERRORS = {
    "context_window_exhausted": ("资料太多，模型暂时处理不下。", "可以先聚焦一个问题，已查到的数据会保留。"),
    "model_context_budget_invalid": ("模型配置还不完整。", "检查模型的上下文和输出额度设置。"),
    "model_http_429": ("模型服务暂时限流了。", "稍后再试，已查到的数据会保留。"),
    "provider_local_quota_exhausted": ("模型的短时调用额度用完了。", "等额度恢复后再试，不用重新查已有的数据。"),
    "model_timeout": ("模型响应超时了。", "可以稍后重试，或先聚焦一个问题。"),
    "model_connection_error": ("模型连接中断了。", "稍后再试。"),
    "model_incomplete_stream": ("回答还没完成，连接就中断了。", "已有内容会保留，可以重试。"),
    "model_stream_error": ("模型生成回答时出错了。", "稍后再试。"),
    "agent_turn_budget_exhausted": ("这次研究已达到调用上限。", "已查到的数据会保留，可以继续问没解决的部分。"),
    "run_token_budget_exhausted": ("这次研究的模型额度用完了。", "可以继续问没解决的部分。"),
    "run_deadline_exceeded": ("这次研究用时较长，已经超时。", "已查到的数据会保留，可以缩小问题后再试。"),
    "analysis_capacity_insufficient": ("计算服务暂时没有足够内存。", "可以先减少数据量，或使用现有的指标和图表。"),
    "analysis_worker_unconfigured": ("计算服务还没配置好。", "仍可查看行情指标和图表。"),
    "analysis_worker_failed": ("这次计算没完成。", "可以稍后重试。"),
    "analysis_memory_limit": ("这次计算需要的内存较多。", "可以减少数据量，或分批计算。"),
    "analysis_timeout": ("这次计算超时了。", "可以减少数据量，或分批计算。"),
    "dataset_has_no_rows": ("这份资料没有可直接计算的表格。", "可以换一张数据表再算。"),
    "dataset_table_required": ("资料里有多张表，需要先选一张。", "按返回的表名选择需要的数据。"),
    "tool_not_allowed": ("这项工具当前不可用。", "可以换一种查询方式。"),
    "tool_provider_error": ("数据源没有返回结果。", "可以换个来源再查。"),
    "report_persistence_failed": ("报告已生成，但保存失败了。", "先保留当前页面，稍后再试。"),
    "research_capacity_exhausted": ("已有研究正在进行。", "等当前研究完成后再发送新问题。"),
    "model_empty_response": ("模型未返回可展示的回答。", "请重试本次问题。"),
    "tool_timeout": ("数据源未在本次限时内返回结果。", "可以换用其他来源，或稍后重试此项查询。"),
    "market_data_unavailable": ("行情来源暂时不可用。", "稍后重试，或选择其他来源。"),
    "chart_columns_missing": ("所选图表字段不在这份数据中。", "先查看数据表的实际列名，再选择对应日期和数值列。"),
    "comparison_common_dates_missing": ("这些标的没有足够的共同日期数据。", "使用相同区间重新取得行情。"),
    "comparison_basis_mismatch": ("数据的币种或复权口径不一致。", "使用同一口径重新获取数据。"),
    "ytd_baseline_unavailable": ("缺少年初前最后交易日的基准价格。", "补充去年末的日线数据后再计算年初至今表现。"),
    "ytd_requires_daily_baseline": ("年初至今比较需要日线基准。", "请使用日线数据获取年末基准收盘价。"),
    "analysis_operation_unsupported": ("当前基础计算尚不支持这项操作。", "选择已有计算方式或可用的隔离计算服务。"),
    "dataset_column_not_found": ("资料中没有所选字段。", "先查看实际数据列再计算。"),
}


def safe_code(value: object) -> str:
    code = str(value or "")
    return code if re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code) else "runtime_internal_error"


def error_info(value: object, *, output: dict | None = None) -> dict:
    code = safe_code(value)
    reason, action = _ERRORS.get(code, ("这次处理出错了。", "已有数据会保留，可以重试。"))
    if code.startswith("model_http_") and code not in _ERRORS:
        reason, action = "模型服务这次没有响应成功。", "检查模型服务状态和账户配置后重试。"
    if code == "analysis_capacity_insufficient" and output:
        available, required = output.get("available_memory_mb"), output.get("required_memory_mb")
        if type(available) is int and type(required) is int:
            reason = f"计算暂时无法开始：需要 {required} MiB 可用内存，当前有 {available} MiB。"
    return {"error_code": code, "reason": reason, "recovery_action": action}


def exception_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if code:
        return safe_code(code)
    if isinstance(exc, TimeoutError):
        return "run_deadline_exceeded"
    candidate = str(exc)
    return candidate if candidate in _ERRORS else "runtime_internal_error"


def clean_text(value: str, limit: int = 600) -> str:
    text = _CREDENTIAL.sub("[已隐藏凭据]", value)
    def clean_url(match):
        try:
            uri = urlsplit(match.group(0))
            query = [(key, "[hidden]" if _PRIVATE.search(key) or key.lower() in {"key", "token", "signature"} else val)
                     for key, val in parse_qsl(uri.query, keep_blank_values=True)]
            return urlunsplit((uri.scheme, uri.netloc.rsplit("@", 1)[-1], uri.path, urlencode(query), ""))
        except ValueError:
            return "[链接]"
    text = re.sub(r"https?://[^\s<>\"]+", clean_url, text)
    return text[:limit] + ("…" if len(text) > limit else "")


def safe_preview(value, *, max_chars: int = 5000):
    remaining = [max_chars]
    def project(item, depth=0):
        if remaining[0] <= 0:
            return "…"
        if isinstance(item, str):
            result = clean_text(item, min(600, remaining[0]))
            remaining[0] -= len(result)
            return result
        if item is None or isinstance(item, (bool, int)):
            return item
        if isinstance(item, float):
            return item if math.isfinite(item) else None
        if depth >= 4:
            return {"条目数": len(item)} if isinstance(item, (list, dict)) else str(type(item).__name__)
        if isinstance(item, dict):
            result = {}
            for key, child in list(item.items())[:20]:
                if _PRIVATE.search(str(key)):
                    continue
                if remaining[0] <= 0:
                    break
                result[clean_text(str(key), 80)] = project(child, depth + 1)
            if len(item) > 20:
                result["其他字段数"] = len(item) - 20
            return result
        if isinstance(item, (list, tuple)):
            rows = [project(child, depth + 1) for child in item[:5]]
            if len(item) > 5:
                rows.append({"其他条目数": len(item) - 5})
            return rows
        return project(str(item), depth)
    result = project(value)
    if len(json.dumps(result, ensure_ascii=False)) > max_chars:
        # 字符串再次JSON转义最多膨胀两倍；预留字段/省略号开销。
        return {"preview": clean_text(json.dumps(result, ensure_ascii=False), max(0, (max_chars - 64) // 2))}
    return result


def tool_summary(output) -> str:
    if isinstance(output, dict):
        if isinstance(output.get("summary"), str):
            return clean_text(output["summary"], 240)
        for key in ("rows", "bars", "articles", "news", "hits", "results", "tools", "skills"):
            if isinstance(output.get(key), list):
                return f"返回 {len(output[key])} 条结果，展开查看内容与来源。"
        return "结果已返回，展开查看关键数据。"
    if isinstance(output, list):
        return f"返回 {len(output)} 条结果，展开查看内容。"
    return clean_text(str(output), 240) or "工具已执行。"


def display_tool(name: str, args: dict, output=None) -> dict[str, str]:
    from .tool_display import display_tool as format_display
    return format_display(name, args, output)
