"""纯事实问答的已取证交付；只在必要资料齐全时使用，不替代投资判断。"""
from __future__ import annotations

import math
import re


def _number(value):
    return type(value) in {int, float} and math.isfinite(value)


def factual_answer(runtime) -> str:
    check, data, query = runtime.completeness, runtime.data, runtime.query
    if runtime.report_title or len(check.tickers) != 1 or check.missing(data, runtime.executor.attempts):
        return ""
    if re.search(r"为什么|为何|原因|估值|比较|对比|影响|研报|深度报告|why|valuation|compare|impact|investment report", query, re.I):
        return ""
    ticker = check.tickers[0]
    records = [(ref, row) for ref, row in reversed(list(data.records.items())) if row.get("status") == "success"
               and str(row.get("inputs", {}).get("ticker", "")).upper() == ticker]
    facets = set(check.facets)
    streak_query = re.search(r"连续(?:至少|不少于)?\s*(\d+)\s*(周|天).*下跌", query)
    if facets == {"chart"} and streak_query and not re.search(r"Python|代码|源码", query, re.I):
        for ref, record in reversed(list(data.records.items())):
            output = record.get("output")
            if record.get("status") != "success" or not isinstance(output, dict):
                continue
            method = output.get("method") or {}
            if method.get("kind") != "consecutive_decline_streaks":
                continue
            if (method.get("min_periods") != int(streak_query[1]) or method.get("minimum_loss") != 0
                    or method.get("frequency") != ("weekly" if streak_query[2] == "周" else "daily")):
                continue
            primary = data.records.get(record.get("inputs", {}).get("dataset_ref"), {})
            if str(primary.get("inputs", {}).get("ticker", "")).upper() != ticker:
                continue
            refs, rows, episodes = data.source_refs(ref), output.get("rows", []), output.get("episodes", [])
            if not refs or not rows or not data.artifacts:
                continue
            sid = refs[0]
            unit = "周" if method.get("frequency") == "weekly" else "个交易日"
            date = lambda value: str(value).split("T")[0]
            lines = [f"## {ticker} 连续下跌区间", "",
                f"已用 {date(rows[0]['date'])} 至 {date(rows[-1]['date'])} 的 {len(rows)} 个真实观测计算并生成走势图。"
                f"连续至少 {method['min_periods']} {unit}收跌的区间共有 {output['sample_count']} 段，"
                f"其中 {output['completed_sample_count']} 段已结束。[{sid}]", "",
                "| 首跌期标签 | 末跌期标签 | 连续期数 | 区间涨跌幅 | 状态 |", "|---|---|---:|---:|---|"]
            lines.extend(f"| {date(row['start'])} | {date(row['end'])} | {row['periods']} | {row['return_pct']*100:.2f}% | "
                         f"{'仍在延续' if row['ongoing'] else '已结束'} |" for row in episodes)
            lines += ["", f"数据来源：实际行情及连续下跌计算 [{sid}]", "",
                "区间按相邻收盘价连续下降识别，取最大且不重叠的连续区间；涨跌幅从首跌期的前一观测收盘价算起。日期沿用供应商标签，不一定是实际收盘日。", ""]
            if method.get("latest_period_closed") is True:
                close = str(method.get("latest_period_close")).replace("T", " ").replace("+00:00", " UTC")
                lines.append(f"末周已收盘，交易日历对应收盘时间为 {close}；仍在延续仅表示下跌区间尚未被后续上涨或持平终止，不表示末根周线尚未收盘。[{sid}]")
            elif method.get("latest_period_closed") is False:
                lines.append(f"取数时末周尚未收盘，已排除 {date(method['excluded_incomplete_period'])} 对应的观测，不把它加入已收盘区间统计。[{sid}]")
            else:
                lines.append("来源未提供足够的周期收盘信息；末期按原始观测保留，延伸到样本末尾的区间不当作已结束样本。")
            lines += ["", "历史区间是对已有数据的描述，不构成后续涨跌概率。"]
            return "\n".join(lines)
    if facets and facets <= {"news", "fresh_search"}:
        for ref, record in records:
            if record["tool"] != "get_company_news":
                continue
            output = record["output"]
            rows = output if isinstance(output, list) else output.get("news", []) if isinstance(output, dict) else []
            rows = [row for row in rows if isinstance(row, dict) and row.get("url") and row.get("published_at")
                    and (row.get("event_quality") or {}).get("freshness", "fresh") == "fresh"]
            rows.sort(key=lambda row: str(row["published_at"]), reverse=True)
            parts = [f"## {ticker} 最近的新闻与催化线索"]
            for row in rows[:6]:
                sid = next((sid for sid in data.source_refs(ref) if data.sources[sid].get("url") == row["url"]), None)
                if not sid:
                    continue
                title = str(row.get("title") or row.get("headline") or "报道").replace("\n", " ")
                snippet = str(row.get("snippet") or row.get("summary") or "").replace("\n", " ")[:1200]
                parts.append(f"**{str(row['published_at'])[:10]} · {row.get('source') or '新闻来源'}**\n\n"
                             f"[{title}]({row['url']})\n\n" + (f"> {snippet} [{sid}]" if snippet else f"[{sid}]"))
            if len(parts) > 1:
                parts.append("以上保留了原文标题与报道摘要，供核对事件和市场观点；返回条目不是该时间段内的完整新闻清单。")
                return "\n\n".join(parts)
        return ""
    if not facets or not facets <= {"filings", "cash_flow"} or not re.search(r"多少|数据|数值|数字|revenue|cash flow", query, re.I):
        return ""
    if not re.search(r"最新|最近|latest|most recent", query, re.I) or re.search(r"同比|环比|增长|差额|变化|趋势|yoy|qoq|growth", query, re.I):
        return ""
    if re.search(r"(?:近|过去|最新).{0,3}(?:[二两三四五六七八九十]|\d+)\s*(?:季|个?季度|年|期)", query):
        return ""
    for ref, record in records:
        output = record["output"]
        if record["tool"] != "get_sec_company_facts_quarterly" or not isinstance(output, dict):
            continue
        periods = output.get("period_ends") or []
        first = lambda key: output[key][0] if isinstance(output.get(key), list) and output[key] else None
        fields = [("营收", "revenue"), ("净利润", "net_income"), ("经营现金流", "operating_cash_flow")]
        if not periods or not all(_number(first(key)) for _, key in fields):
            continue
        alternative = not _number(first("free_cash_flow"))
        flow_key = "free_cash_flow_after_productive_asset_purchases" if alternative else "free_cash_flow"
        if not _number(first(flow_key)):
            continue
        if _number(first("capital_expenditures")):
            fields.append(("资本开支", "capital_expenditures"))
        if alternative:
            fields.extend([("生产性资产购置", "productive_asset_purchases"), ("经营现金流减生产性资产购置", flow_key)])
        else:
            fields.append(("自由现金流（经营现金流减资本开支）", flow_key))
        refs = data.source_refs(ref)
        if not refs:
            continue
        sid = refs[0]
        currency = output.get("currency") or "来源原始单位"
        lines = [f"## {ticker} 最新已披露季度：截至 {periods[0]}", "",
                 f"| 项目 | 金额（{currency}） |", "|---|---:|"]
        lines.extend(f"| {label} | {first(key):,.0f} |" for label, key in fields if _number(first(key)))
        lines += ["", f"来源：SEC 公司财报 [{sid}]", "",
                  "以上按单季口径列示。自由现金流差额是根据已取得科目计算的研究口径，不代表公司披露的非 GAAP 指标。"]
        metadata = output.get("fact_metadata") or {}
        differenced = [label for label, key in fields if isinstance(metadata.get(key), list) and metadata[key]
                       and isinstance(metadata[key][0], dict) and metadata[key][0].get("derivation") == "ytd_difference"]
        if differenced:
            lines.append("、".join(differenced) + "的单季值由同财年累计值相减得到，保留了两份申报输入；并非直接披露的独立单季数值。")
        if alternative:
            lines.append("这里单列了扣除生产性资产购置后的差额；该购置科目不能当作仅有形固定资产资本开支，两种口径不能混用。")
        return "\n".join(lines)
    return ""
