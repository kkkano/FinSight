"""正式工具的逐项展示合同；未知工具必须补注册，不能落成通用成功文案。"""
from __future__ import annotations

from urllib.parse import urlsplit
import math
import re

from .diagnostics import clean_text, error_info


def number(value, digits=2):
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return f"{value:,.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:,.0f}"


def rows(value):
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("rows", "kline_data", "bars", "articles", "news", "hits", "data", "results", "holdings", "transactions", "filings", "items", "transcripts", "events"):
            if isinstance(value.get(key), list):
                return rows(value[key])
            if isinstance(value.get(key), dict):
                found = rows(value[key])
                if found:
                    return found
    return []


def body(value):
    if not isinstance(value, dict):
        return {}
    if isinstance(value.get("data"), dict):
        return {**value, **value["data"]}
    return value


def target(args):
    parent = args.get("_dataset_inputs") or {}
    return clean_text(str(args.get("ticker") or args.get("symbol") or parent.get("ticker")
        or args.get("query") or args.get("indicator") or "当前研究资料"), 100)


def domains(value):
    result = []
    def visit(item, depth=0):
        if depth > 5 or len(result) >= 3:
            return
        if isinstance(item, dict):
            for key in ("url", "link", "source_url"):
                url = item.get(key)
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    host = urlsplit(url).hostname or ""
                    host = host.removeprefix("www.")
                    if host and host not in result:
                        result.append(host)
            for child in item.values():
                if isinstance(child, (list, dict)):
                    visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item[:12]:
                visit(child, depth + 1)
    visit(value)
    return "、".join(result)


def history(args, output):
    period = {"1d": "近1日", "5d": "近5日", "ytd": "年初至今", "1mo": "近1月", "3mo": "近3月", "6mo": "近6月", "1y": "近1年", "max": "全部可用历史"}.get(args.get("period"), args.get("period", "近1年"))
    frequency = {"1m": "1分钟", "5m": "5分钟", "15m": "15分钟", "30m": "30分钟", "1d": "日线", "1wk": "周线", "1mo": "月线"}.get(args.get("interval", "1d"), args.get("interval"))
    points = rows(output)
    caption = " · ".join(filter(None, [target(args), frequency, period]))
    if output is None:
        return caption, ""
    if not points:
        return caption, "未取得可用K线"
    start, end = points[0], points[-1]
    date = lambda row: str(row.get("date") or row.get("time") or row.get("datetime") or "")[:10]
    if date(start) and date(end):
        caption = f"{target(args)} · {frequency} · {date(start)}→{date(end)}"
    first, last = number(start.get("close")), number(end.get("close"))
    return caption, f"{len(points)} 根K线" + (f" · 收盘 {first}→{last}" if first is not None and last is not None else "")


def quote(args, output):
    if output is None:
        return target(args), ""
    value = body(output)
    if isinstance(output, str):
        price = re.search(r"(?:Current Price:|当前价格[:：]?)\s*\$?([\d,.]+)", output)
        change = re.search(r"\(([+-]?[\d.]+)%\)", output)
        currency = re.search(r"Currency:\s*([A-Z]{3})", output)
        stamp = re.search(r"As of:\s*([^|]+)", output)
        parts = [price.group(1) + " " + (currency.group(1) if currency else "") if price else "",
                 change.group(1) + "%" if change else "", stamp.group(1).strip() if stamp else ""]
    else:
        price = number(value.get("price", value.get("close")))
        change = number(value.get("change_percent"))
        parts = [f"{price} {value.get('currency', '')}" if price else "", f"{change}%" if change else "",
                 str(value.get("as_of") or value.get("source_timestamp") or "")]
    return target(args), " · ".join(part.strip() for part in parts if part) or "报价字段暂缺"


def extended_history(args, output):
    subject, result = history(args, output)
    session = {"all": "盘前/盘中/盘后", "pre_market": "盘前", "regular": "常规交易", "after_hours": "盘后"}.get(args.get("session", "all"), "")
    return subject + " · " + session, result


def otc_activity(args, output):
    if output is None:
        return f"{target(args)} · 近{args.get('weeks', 8)}周场外成交", ""
    points = rows(output)
    if not points:
        return target(args), "未取得已公布的场外统计"
    latest = max(points, key=lambda row: str(row.get("week_start") or row.get("date") or ""))
    ats, other = number(latest.get("ats_share_volume")), number(latest.get("non_ats_share_volume"))
    parts = [f"{len(points)}周统计", "延迟公布"]
    if ats:
        parts.append("替代交易系统 " + ats + "股")
    if other:
        parts.append("其它场外 " + other + "股")
    return target(args) + " · " + str(latest.get("week_start") or latest.get("date") or ""), " · ".join(parts)


def article_display(noun):
    def display(args, output):
        subject = clean_text(str(args.get("query") or args.get("url") or target(args)), 120)
        if output is None:
            return subject, ""
        items = rows(output)
        if isinstance(output, str) and output.strip():
            count = f"取得正文 · {len(output)} 字"
        elif isinstance(output, dict) and isinstance(output.get("content") or output.get("text"), str):
            count = f"取得正文 · {len(output.get('content') or output.get('text'))} 字"
        else:
            count = f"{len(items)} 条{noun}" if items else f"未取得匹配的{noun}"
        source = domains(output)
        return subject, count + (" · " + source if source else "")
    return display


def metric_display(noun, fields):
    def display(args, output):
        if output is None:
            return target(args), ""
        if isinstance(output, str):
            parts = []
            for key, label in fields:
                match = re.search(r"(?:^|\n)\s*-?\s*" + re.escape(key.replace("_", " ")) + r"\s*:\s*([^\n]+)", output, re.I)
                if match:
                    parts.append(label + " " + match.group(1).strip())
            if not parts:
                parts = [line.strip(" -") for line in output.splitlines() if line.strip()][:2]
            return target(args), clean_text(" · ".join(parts[:3]), 220)
        value = body(output)
        parts = []
        for key, label in fields:
            item = value.get(key)
            formatted = number(item) if isinstance(item, (int, float)) else clean_text(item, 80) if isinstance(item, str) else None
            if formatted:
                parts.append(label + " " + formatted)
            if len(parts) == 3:
                break
        if parts:
            return target(args), " · ".join(parts)
        items = rows(output)
        return target(args), f"{len(items)} 条{noun}" if items else f"{noun}字段暂缺"
    return display


def financials(args, output):
    if output is None:
        return target(args), ""
    value = body(output)
    periods = value.get("period_ends") or value.get("periods") or []
    parts = [f"{len(periods)} 个财期" if periods else "财报已读取"]
    if periods:
        parts.append(str(periods[-1]))
    for key, label in (("revenue", "营收"), ("net_income", "净利润"), ("eps", "每股盈利")):
        values = value.get(key)
        item = values[-1] if isinstance(values, list) and values else values
        formatted = number(item)
        if formatted:
            parts.append(label + " " + formatted)
    return target(args), " · ".join(parts[:4])


def calculation(args, output):
    operation = args.get("operation") or (output or {}).get("method", {}).get("kind") if isinstance(output, dict) else args.get("operation")
    minimum = (args.get("parameters") or {}).get("min_periods", 5)
    purpose = args.get("description") or args.get("task") or {
        "series_statistics": "计算区间收益与高低", "historical_drawdown_episodes": f"识别连续下跌≥{minimum}期的区间", "indexed_comparison": "计算区间相对涨跌", "valuation_scenarios": "计算估值情景",
    }.get(operation) or "执行本轮分析代码"
    if output is None:
        return clean_text(str(purpose), 120), ""
    value = body(output)
    if isinstance(value.get("result"), dict):
        value = value["result"]
    if isinstance(value.get("summary"), str):
        result = clean_text(value["summary"], 180)
    elif value.get("sample_count") is not None:
        result = f"找到 {value['sample_count']} 段区间"
    else:
        numeric = [(key, val) for key, val in value.items() if type(val) in {int, float} and number(val) is not None]
        result = " · ".join(f"{key} {number(val)}" for key, val in numeric[:3])
        if not result:
            result = f"生成 {len(rows(value))} 行计算结果" if rows(value) else clean_text(str(value.get("summary") or "计算未返回可展示的数值"), 180)
    return clean_text(str(purpose), 120), result


def chart(args, output):
    artifact = (output or {}).get("_artifact", {}) if isinstance(output, dict) else {}
    kind = {"line": "折线图", "bar": "柱状图", "scatter": "散点图", "candlestick": "K线图", "line_with_event_windows": "区间走势与小图"}.get(args.get("chart_type"), "图表")
    return clean_text(str(args.get("title") or "研究图表"), 120), "" if output is None else f"{kind} · {len(args.get('series') or [])} 条序列 · {len(rows(artifact.get('data')))} 个点"


def delegation(args, output):
    from backend.agents.profiles import AGENT_PROFILES
    profile = AGENT_PROFILES.get(args.get("role"))
    return profile.name_zh if profile else "专业研究员", clean_text(str(args.get("task") or ""), 150)


def readback(args, output):
    offset = args.get("offset", 0)
    value = body(output)
    end = value.get("next_offset") or value.get("total_chars") or offset
    return target(args) + " · 原始资料", "" if output is None else f"读取第 {offset}–{end} 字" + (" · 后续仍有内容" if value.get("has_more") else "")


def inspect_table(args, output):
    value = body(output)
    columns = value.get("columns") or []
    return target(args) + (" · " + str(args["table"]) if args.get("table") else " · 数据表"), "" if output is None else f"{len(rows(output))} 行 / 共 {value.get('row_count', len(rows(output)))} 行 · {len(columns)} 个字段"


def named_control(noun, input_key, output_key):
    def display(args, output):
        selected = args.get(input_key) if input_key else None
        value = body(output)
        selected = selected or value.get("name") or value.get("title")
        from .diagnostics import TOOL_TITLES
        label = "、".join(TOOL_TITLES.get(str(item), str(item)) for item in selected[:4]) if isinstance(selected, list) else str(selected or noun)
        items = value.get(output_key) if output_key else None
        status = {"ok": "已应用", "accepted": "已受理", "completed": "已完成", "confirmation_required": "等待确认", "pending": "仍在处理", "target_finished": "对方任务已结束"}.get(value.get("status"), "")
        result = f"{len(items)} 项{noun}" if isinstance(items, list) else clean_text(str(value.get("summary") or value.get("description") or status or noun + "已记录"), 180)
        return clean_text(label, 120), "" if output is None else result
    return display


DISPLAYS = {
    "get_stock_price": quote, "get_stock_historical_data": history, "get_us_extended_hours": extended_history,
    "get_company_news": article_display("新闻"), "get_authoritative_media_news": article_display("权威报道"),
    "search": article_display("搜索结果"), "fetch_url_content": article_display("网页"),
    "get_earnings_call_transcripts": article_display("电话会记录"), "get_event_calendar": article_display("事件"),
    "get_economic_events": article_display("经济事件"), "get_official_macro_releases": article_display("官方发布"),
    "get_local_market_filings": article_display("公司公告"), "get_sec_filings": article_display("监管文件"),
    "get_sec_material_events": article_display("重大事件"), "get_sec_risk_factors": article_display("风险披露"),
    "get_sec_company_facts_quarterly": financials,
    "get_company_info": metric_display("公司资料", (("name", ""), ("sector", "行业"), ("market_cap", "市值"))),
    "get_technical_snapshot": metric_display("技术指标", (("close", "收盘"), ("ma20", "20日均线"), ("rsi14", "相对强弱指数"))),
    "get_price_window_metrics": metric_display("区间指标", (("return_pct", "区间变化"), ("max_drawdown", "最大回撤"))),
    "get_earnings_estimates": metric_display("盈利预期", (("ticker", "标的"), ("as_of", "截至"))),
    "get_eps_revisions": metric_display("盈利修正", (("net_revisions", "净修正"), ("up_revisions", "上修"), ("down_revisions", "下修"))),
    "get_market_sentiment": metric_display("市场情绪", (("score", "情绪评分"), ("label", "状态"))),
    "get_option_chain_metrics": metric_display("期权指标", (("iv_atm", "平值隐含波动率"), ("put_call_ratio_oi", "认沽认购比"), ("expiry", "到期"))),
    "get_factor_exposure": metric_display("风险因子", (("beta", "市场敏感度"), ("r_squared", "拟合度"))),
    "get_performance_comparison": metric_display("对比数据", (("period", "区间"),)),
    "get_sec_capital_allocation": metric_display("资本配置", (("buybacks", "回购"), ("dividends", "分红"))),
    "get_finra_otc_activity": otc_activity,
    "get_fred_data": metric_display("宏观观测", (("latest_value", "最新值"), ("as_of", "截至"))),
    "get_insider_transactions": article_display("内部人交易"), "get_institution_holdings_by_ticker": article_display("机构持仓"),
    "get_institutional_holdings": article_display("机构持仓"), "get_holdings_overlap": metric_display("重合持仓", (("overlap_count", "重合标的"),)),
    "score_news_source_reliability": metric_display("来源核验", (("score", "可靠度"), ("tier", "来源层级"))),
    "analyze_historical_drawdowns": calculation, "analyze_dataset": calculation, "run_analysis_code": calculation,
    "render_chart": chart, "delegate_research": delegation, "read_evidence": readback, "read_document": readback,
    "inspect_dataset": inspect_table, "search_knowledge": article_display("知识资料"), "search_memory": article_display("会话资料"),
    "discover_tools": named_control("研究工具", None, "tools"), "enable_tools": named_control("工具", "names", "enabled"),
    "discover_skills": named_control("研究技能", None, "skills"), "use_skill": named_control("研究技能", None, None),
    "read_selection": named_control("选中资料", None, "items"), "get_watchlist": named_control("自选标的", None, "rows"),
    "await_agent_results": named_control("专业研究结果", None, "results"), "send_agent_message": named_control("研究交流", "message", None),
    "mark_report": named_control("研究报告", "title", None), "propose_action": named_control("自选操作", "ticker", None),
    "get_current_datetime": lambda args, output: ("当前时间", "" if output is None else clean_text(str(output), 100)),
}


def display_tool(name: str, args: dict, output=None) -> dict[str, str]:
    if name not in DISPLAYS:
        raise ValueError("tool_display_not_registered")
    subject, result = DISPLAYS[name](args, output)
    if isinstance(output, dict) and output.get("status") in {"error", "unavailable"}:
        result = clean_text(str(output.get("summary") or error_info(output.get("error_code") or output.get("error"))["reason"]), 180)
    return {"target": clean_text(subject, 150), "result": clean_text(result, 220)}
