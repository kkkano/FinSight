# -*- coding: utf-8 -*-
"""已规范化金融证据的展示适配；结构字段不能作为 JSON 或 repr 进入正文。"""
from __future__ import annotations

import ast
import json
import math
import re
from typing import Any

from backend.graph.synthesis.research_synthesis import clean_research_text
from backend.graph.synthesis.requirement_validation import disclosure_sections
from backend.tools.financial_facts import parse_profile_market_cap
from backend.utils.quote import parse_quote_payload


def number(value: Any, digits: int = 2, *, percent: bool = False) -> str:
    if value is None or isinstance(value, bool):
        return "未提供"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(numeric):
        return "未提供"
    if percent:
        numeric *= 100
    rendered = f"{numeric:,.{digits}f}".rstrip("0").rstrip(".") if digits else f"{numeric:,.0f}"
    return rendered + ("%" if percent else "")


def money(value: Any, unit: str | None) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "未提供"
    label = unit or "[币种未提供]"
    if "/" in label:
        return f"{number(numeric, 4)} {label}"
    if abs(numeric) >= 100_000_000:
        return f"{number(numeric / 100_000_000)} 亿 {label}"
    if abs(numeric) >= 10_000:
        return f"{number(numeric / 10_000)} 万 {label}"
    return f"{number(numeric)} {label}"


def payload_for(evidence) -> dict[str, Any]:
    payload = dict(evidence.structured_data)
    if not payload:
        text = evidence.text.strip()
        if text.startswith(("{", "[")):
            try:
                payload = json.loads(text)
            except (TypeError, ValueError):
                try:
                    payload = ast.literal_eval(text)
                except (ValueError, SyntaxError):
                    payload = {}
        if not payload and any(key in evidence.metadata for key in ("factor_beta", "risk_score", "metric_key", "value")):
            payload = dict(evidence.metadata)
    if isinstance(payload, list):
        payload = {"items": payload}
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("data"), dict):
        payload = {**payload, **payload["data"]}
    return payload


def _rows(value: Any) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _get(row: dict, *names: str) -> Any:
    lowered = {str(key).casefold(): value for key, value in row.items()}
    return next((lowered[name.casefold()] for name in names if lowered.get(name.casefold()) is not None), None)


def _time(payload: dict, evidence) -> str:
    return str(payload.get("as_of") or evidence.as_of or evidence.period_end or "源数据时间未提供")


def _period(value: Any) -> str:
    return {"0q": "当前财政季度", "+1q": "下一财政季度", "0y": "当前财年", "+1y": "下一财年"}.get(str(value), str(value or "期间未提供"))


def _earnings(payload: dict, evidence, *, compact: bool = False, summary: bool = False) -> str:
    lines = []
    currency = payload.get("currency") or evidence.currency
    unit = f"{currency}/股" if currency else "[币种未提供]/股"
    for row in _rows(payload.get("earnings_estimate")):
        if compact and row.get("period") not in {"0q", "+1q"}:
            continue
        average = _get(row, "avg", "current", "estimate")
        if average is None:
            continue
        line = f"{_period(row.get('period'))} 共识 EPS {number(average, 4)} {unit}"
        low, high = _get(row, "low"), _get(row, "high")
        if not compact and low is not None and high is not None:
            line += f"，区间 {number(low, 4)} 至 {number(high, 4)} {unit}"
        analysts = _get(row, "numberOfAnalysts")
        if not compact and analysts is not None:
            line += f"，覆盖分析师 {number(analysts, 0)} 位"
        growth = _get(row, "growth")
        if not compact and growth is not None:
            line += f"，供应商预期增长 {number(growth, percent=True)}"
        lines.append(line)
    for row in _rows(payload.get("eps_revisions")):
        if summary and lines:
            break
        if compact and row.get("period") not in {"0q", "+1q"}:
            continue
        for days in (7,) if compact else (7, 30):
            up, down = _get(row, f"upLast{days}days"), _get(row, f"downLast{days}days")
            if up is not None or down is not None:
                lines.append(f"{_period(row.get('period'))} 近 {days} 天 EPS 预期：上修 {number(up, 0)} 次，下修 {number(down, 0)} 次")
    for row in _rows(payload.get("eps_trend")):
        if compact and (lines or row.get("period") not in {"0q", "+1q"}):
            continue
        current, previous = _get(row, "current"), _get(row, "30daysAgo")
        if current is not None and previous is not None:
            lines.append(f"{_period(row.get('period'))} 共识 EPS：30 天前 {number(previous, 4)}，当前 {number(current, 4)} {unit}")
    if not lines:
        return ""
    return "\n".join(lines) + f"\n快照时间：{_time(payload, evidence)}。预期并非已实现业绩。"


def _financial(payload: dict, evidence, *, compact: bool = False, summary: bool = False) -> str:
    periods = payload.get("period_ends") or payload.get("periods") or []
    metadata = payload.get("fact_metadata") if isinstance(payload.get("fact_metadata"), dict) else {}
    specs = (("revenue", "营收"), ("gross_profit", "毛利"), ("operating_income", "经营利润"), ("net_income", "净利润"), ("eps", "EPS"), ("operating_cash_flow", "经营现金流"), ("capital_expenditures", "资本开支"), ("free_cash_flow", "自由现金流"), ("total_assets", "总资产"), ("total_liabilities", "总负债"))
    lines = []
    for key, label in specs:
        if compact and key not in {"revenue", "net_income", "operating_cash_flow"}:
            continue
        values = payload.get(key)
        if not isinstance(values, list) or not values:
            continue
        fact_rows = metadata.get(key)
        meta = fact_rows[0] if isinstance(fact_rows, list) and fact_rows and isinstance(fact_rows[0], dict) else {}
        period = str(meta.get("period_end") or (periods[0] if isinstance(periods, list) and periods else evidence.period_end or "期间未提供"))
        if values[0] is None:
            lines.append(f"[数据缺失] {period} {label}没有可验证的对应期间数据。")
            continue
        unit = meta.get("unit") or evidence.unit or payload.get("currency") or evidence.currency
        if meta.get("frequency") not in {None, "quarterly", "instant"} and key not in {"total_assets", "total_liabilities"}:
            lines.append(f"[数据缺失] {label}只有 {meta['frequency']} 数据，不能当作单季值。")
            continue
        line = f"{period} {label} {money(values[0], unit)}"
        if meta.get("period_start") and not summary:
            line += f"（{meta['period_start']} 至 {period}）"
        elif meta.get("frequency") == "instant":
            line += "（期末余额）"
        if meta.get("filed") and not summary:
            line += f"；披露日 {meta['filed']}"
        lines.append(line)
    return "\n".join(lines)


def _profile(payload: dict, evidence, *, compact: bool = False) -> str:
    raw = str(payload.get("text") or evidence.text)
    fields = dict(payload)
    for label, value in re.findall(r"(?m)^\s*-?\s*([^:\n]+):[ \t]*([^\n]+)$", raw):
        fields.setdefault(label.strip(), value.strip())
    aliases = (("name", "公司", False), ("Name", "公司", False), ("sector", "行业大类", False), ("Sector", "行业大类", False), ("industry", "细分行业", False), ("Industry", "细分行业", False), ("trailingPE", "Trailing P/E", False), ("Trailing P/E", "Trailing P/E", False), ("forwardPE", "Forward P/E", False), ("Forward P/E", "Forward P/E", False), ("Price/Book", "P/B", False), ("Price/Sales", "P/S", False), ("EV/EBITDA", "EV/EBITDA", False), ("profitMargins", "净利率", True), ("revenueGrowth", "营收增长率", True), ("earningsGrowth", "盈利增长率", True))
    lines = []
    amount = parse_profile_market_cap(fields if payload and not payload.get("text") else raw)
    if amount.value is not None:
        lines.append(f"市值：{money(amount.value, amount.currency)}")
    for key, label, ratio in aliases:
        if compact and key not in {"name", "Name", "forwardPE", "Forward P/E", "trailingPE", "Trailing P/E", "profitMargins", "revenueGrowth"}:
            continue
        value = fields.get(key)
        if value is not None:
            formatted = number(value, percent=ratio) if ratio or isinstance(value, (int, float)) else str(value)
            line = f"{label}：{formatted}"
            if line not in lines:
                lines.append(line)
    description = fields.get("longBusinessSummary") or fields.get("description") or fields.get("Description") or fields.get("business_summary")
    if not compact and isinstance(description, str) and description.strip():
        lines.append("业务：" + description.strip())
    return "\n".join(lines)


def _technical(payload: dict, evidence) -> str:
    lines = []
    specs = (("close", "收盘价", 2), ("ma20", "MA20", 2), ("ma50", "MA50", 2), ("ma200", "MA200", 2), ("rsi14", "RSI(14)", 2), ("macd", "MACD", 4), ("macd_signal", "MACD 信号线", 4), ("support", "支撑", 2), ("resistance", "阻力", 2), ("volume", "成交量", 0), ("volume_avg20", "20 日均量", 0))
    for key, label, digits in specs:
        if payload.get(key) is not None:
            lines.append(f"{label} {number(payload[key], digits)}")
    if isinstance(payload.get("rsi14"), (int, float)):
        lines.append("RSI 处于超买区，短期回撤风险需要关注。" if payload["rsi14"] >= 70 else "RSI 处于超卖区，仍需价格确认。" if payload["rsi14"] <= 30 else "RSI 尚未进入常用超买或超卖区间。")
    if isinstance(payload.get("macd"), (int, float)) and isinstance(payload.get("macd_signal"), (int, float)):
        lines.append("MACD 高于信号线。" if payload["macd"] > payload["macd_signal"] else "MACD 未高于信号线。")
    trend = {"uptrend": "上升趋势", "downtrend": "下降趋势", "neutral": "中性", "sideways": "横盘", "bullish": "偏强", "bearish": "偏弱"}.get(str(payload.get("trend") or ""))
    if trend:
        lines.append(f"指标趋势：{trend}。")
    return "；".join(lines)


def _risk(payload: dict, evidence, *, compact: bool = False, brief: bool = False) -> str:
    lines = []
    if payload.get("risk_score") is not None:
        lines.append(f"规则风险评分 {number(payload['risk_score'])}/100；该评分不代表未来损失概率。")
    factors = payload.get("factor_beta")
    if isinstance(factors, dict):
        labels = {"market": "市场", "growth": "成长", "small_cap": "小盘", "rates": "利率", "gold": "黄金", "usd": "美元"}
        lines.append("因子 beta：" + "；".join(f"{labels.get(key, key)} {number(value, 4)}" for key, value in factors.items() if isinstance(value, (int, float)) and (not compact or key in ({"market"} if brief else {"market", "growth"}))))
    for key, label in (("annualized_volatility", "历史年化波动率"), ("max_drawdown", "观察期最大回撤")):
        if brief and key == "annualized_volatility":
            continue
        if payload.get(key) is not None:
            lines.append(f"{label} {number(payload[key], percent=True)}")
    if not compact and payload.get("lookback_days") is not None:
        lines.append(f"观察窗口 {number(payload['lookback_days'], 0)} 个交易日")
    if not compact and payload.get("observation_count") is not None:
        lines.append(f"有效样本 {number(payload['observation_count'], 0)} 个")
    if not compact and payload.get("market_r2") is not None:
        lines.append(f"市场模型 R² {number(payload['market_r2'], 4)}")
    scenarios = payload.get("scenarios") or payload.get("stress_tests")
    for row in _rows(scenarios):
        scenario = row.get("name") or row.get("scenario") or "压力情景"
        loss = _get(row, "portfolio_return", "expected_return", "estimated_return", "estimated_loss")
        if loss is not None:
            lines.append(f"情景 {scenario}：模型估计 {number(loss, percent=True)}，不是收益预测。")
    raw = str(payload.get("text") or evidence.text)
    for match in re.finditer(r"Drawdown:\s*([-+\d.]+)%\s*\(from\s+(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})\)\s*Duration to trough:\s*(\d+)\s*days\.\s*Recovery time:\s*(\d+|N/A)\s*days", raw, re.IGNORECASE):
        drawdown, start, end, trough_days, recovery_days = match.groups()
        recovery = f"恢复耗时 {recovery_days} 天" if recovery_days != "N/A" else "恢复时间尚未确认"
        lines.append(f"历史回撤 {number(drawdown)}%（{start} 至 {end}），到谷底 {trough_days} 天，{recovery}。")
    if lines:
        lines.append(f"快照时间：{_time(payload, evidence)}；历史模型不代表未来表现。")
    return "\n".join(lines)


def _options(payload: dict, evidence) -> str:
    lines = []
    for key, label, ratio in (("iv_atm", "ATM 隐含波动率", True), ("put_call_ratio_oi", "持仓 Put/Call", False), ("put_call_ratio_volume", "成交 Put/Call", False), ("iv_skew_25d", "25Δ IV 偏斜", True)):
        if payload.get(key) is not None:
            lines.append(f"{label} {number(payload[key], 4 if not ratio else 2, percent=ratio)}")
    if payload.get("expiry"):
        lines.append(f"到期日：{payload['expiry']}")
    return "；".join(lines)


def _calendar(payload: dict, evidence, *, limit: int | None = None) -> str:
    lines, seen = [], set()
    for key, label in (("earnings_events", "财报"), ("dividend_events", "分红"), ("macro_events", "宏观"), ("events", "事件")):
        for row in _rows(payload.get(key)):
            date = str(row.get("date") or row.get("datetime") or "时间未提供")
            if date == "时间未提供":
                continue
            title = str(row.get("title") or row.get("event") or "事件说明未提供")
            if title.lower() == "earnings date":
                title = "预期财报发布日期"
            title = re.sub(r"\s*\|\s*", "，", title).strip("， ")
            canonical_title = "联储会议纪要" if re.search(r"FOMC.*Minutes", title, re.IGNORECASE) else title
            identity = (date, canonical_title)
            if identity in seen:
                continue
            seen.add(identity)
            source = str(row.get("source") or payload.get("source") or "")
            note = "（搜索日历线索，仍需官方确认）" if "search" in source else "（供应商日历，日期以公司或官方披露为准）"
            lines.append(f"{label}：{date} {canonical_title}{note}")
    if lines:
        if limit is not None:
            lines = lines[:limit]
        coverage = payload.get("coverage_window") or evidence.metadata.get("coverage_window")
        if isinstance(coverage, dict) and coverage.get("as_of") and coverage.get("scope") == "provider_calendar":
            days = coverage.get("days_ahead") or (coverage.get("value") if coverage.get("unit") == "days" else None)
            if days is not None:
                lines.append(f"本轮供应商日历查询窗口为未来 {number(days, 0)} 天，不代表已取得全部事件；快照时间 {coverage['as_of']}。")
        return "\n".join(lines)
    return "[数据缺失] 该日历来源未返回可核验的事件日期。"


def _macro(payload: dict, evidence) -> str:
    meta = evidence.metadata
    indicator = meta.get("indicator_key")
    labels = {"fed_rate": "联邦基金利率（历史观测）", "cpi": "CPI 通胀同比", "unemployment": "失业率", "gdp_growth": "GDP 增速", "treasury_10y": "10 年期美债收益率", "yield_spread": "10Y-2Y 利差"}
    if indicator not in labels:
        return ""
    value = meta.get("value")
    if value is None:
        candidates = _rows(meta.get("candidates"))
        matched = [item for item in candidates if str(item.get("source") or "").casefold() == str(evidence.source_name or "").casefold()]
        if len(matched) == 1:
            value = matched[0].get("value")
    if value is None:
        return ""
    unit = "个百分点" if indicator == "yield_spread" else str(meta.get("unit") or evidence.unit or "[单位未提供]")
    period = evidence.period_end or meta.get("period_end") or evidence.as_of or "观察期未提供"
    text = f"{period} {labels[indicator]} {number(value)}{unit}"
    if indicator == "fed_rate":
        text += "；该序列观测不等同于最近一次 FOMC 决议确认。"
    return text


def format_fact(evidence, *, profile: str = "full") -> str:
    compact = profile in {"chat", "brief", "comparison"}
    payload = payload_for(evidence)
    raw = str(payload.get("text") or evidence.text)
    quote = parse_quote_payload(payload) or (parse_quote_payload(raw) if "Current Price:" in raw else None)
    if evidence.kind == "price_snapshot" or quote and evidence.kind in {"technical_snapshot", "risk_profile"}:
        price = evidence.market_price if evidence.market_price is not None else quote.get("price") if quote else None
        if price is not None:
            currency = evidence.currency or payload.get("currency") or (quote or {}).get("currency") or "[币种未提供]"
            as_of = (quote or {}).get("as_of") or evidence.as_of or "未提供"
            label = "风险校准报价" if evidence.kind == "risk_profile" else "最新可用报价"
            session = (quote or {}).get("market_session") or payload.get("market_session") or evidence.metadata.get("market_session")
            session_label = {"regular_close":"常规交易时段的日线收盘价，非盘后价格", "regular":"常规交易时段", "post":"盘后交易", "postmarket":"盘后交易", "after_hours":"盘后交易", "pre":"盘前交易", "premarket":"盘前交易", "continuous_close":"24 小时市场的日线收盘价"}.get(str(session or '').lower())
            precision = (quote or {}).get("source_time_precision") or evidence.metadata.get("source_time_precision")
            timing = f"源日期：{as_of}（来源仅提供交易日，不代表精确成交时刻）" if precision == 'date' else f"源数据时间：{as_of}"
            return f"{evidence.subject or '标的'} {label} {number(price)} {currency}；{timing}；{session_label or '[数据缺失] 来源未提供常规/盘前/盘后属性'}。"
    formatter = {"earnings_estimates": lambda data, item: _earnings(data, item, compact=compact, summary=profile in {"comparison", "brief"}), "company_profile": lambda data, item: _profile(data, item, compact=compact), "technical_snapshot": _technical, "risk_profile": lambda data, item: _risk(data, item, compact=compact, brief=profile == "brief"), "options_derivatives": _options, "event_calendar": lambda data, item: _calendar(data, item, limit=1 if profile == "brief" else 3 if compact else None)}.get(evidence.kind)
    text = formatter(payload, evidence) if formatter else ""
    if not text and evidence.kind == "macro_context":
        text = _macro(payload, evidence)
    if not text and evidence.kind in {"filing_context", "fundamental_snapshot"}:
        text = _financial(payload, evidence, compact=compact, summary=profile in {"comparison", "brief"})
        metric = evidence.metric or evidence.metadata.get("metric_key") or payload.get("metric_key")
        if not text and metric and payload.get("value") is not None:
            labels = {"revenue": "营收", "net_income": "净利润", "operating_income": "经营利润", "operating_cash_flow": "经营现金流", "total_assets": "总资产", "total_liabilities": "总负债"}
            period = evidence.period_end or payload.get("latest_period") or "期间未提供"
            text = f"{period} {labels.get(metric, metric)} {money(payload['value'], evidence.unit or evidence.currency)}"
        if not text and metric and evidence.unit and re.search(r"[-+]?\$?[-+]?\d+(?:\.\d+)?[KMBT]", raw):
            text = f"{evidence.period_end or '期间未提供'} {raw}；单位 {evidence.unit}；来源口径 {evidence.frequency or '未提供'}。"
        sections = disclosure_sections(payload)
        if not text and sections:
            labels = {"business": "业务正文摘录", "competition": "竞争正文摘录", "management_discussion": "管理层讨论摘录"}
            limit = 600 if compact else 1400
            text = "\n".join([
                f"{evidence.as_of or '披露时间未提供'} {evidence.title or '公司公告'}；已读取披露正文。",
                *[f"{labels.get(name, '披露正文摘录')}：{' '.join(body.split())[:limit]}" for name, body in sections.items()],
            ])
        if not text and evidence.kind == "filing_context" and evidence.url:
            text = f"{evidence.as_of or '披露时间未提供'} {evidence.title or '公司公告'}；该来源为公告索引，财务结论需核对文件正文。"
    if not text and evidence.kind == "news_context" and isinstance(payload.get("snapshot"), dict):
        snapshot = payload["snapshot"]
        sentiment = snapshot.get("sentiment_bias") or {}
        heat = snapshot.get("heat") or {}
        bias = {"bullish": "积极", "bearish": "消极", "neutral": "中性"}.get(sentiment.get("label"), "未确定")
        if (sentiment.get("sample_size") or 0) < 3 or sentiment.get("average_score") is None:
            text = f"舆情样本不足，不能判断整体情绪；当前合格报道 {number(heat.get('news_count'), 0)} 条。"
        else:
            text = f"样本舆情{bias}，平均分 {number(sentiment.get('average_score'))}；情绪样本 {number(sentiment.get('sample_size'), 0)} 条，当前合格报道 {number(heat.get('news_count'), 0)} 条。舆情标签不代表投资方向。"
        transmission = snapshot.get("price_transmission") or {}
        if transmission.get("analysis"):
            text += "\n" + str(transmission["analysis"])
    if not text and evidence.kind in {"news_context", "macro_context", "document_context", "transcript_context"}:
        description = payload.get("snippet") or payload.get("summary") or payload.get("content") or ""
        if isinstance(description, str) and description.strip():
            title = str(payload.get("title") or evidence.title or "")
            date = str(payload.get("published_date") or evidence.as_of or "")
            text = " ".join(value for value in (date, title, "" if compact and evidence.kind == "news_context" else description.strip()) if value)
    if not text:
        rows = _rows(payload.get("releases") or payload.get("articles") or payload.get("filings") or payload.get("items"))
        if rows:
            text = "\n".join(" ".join(str(row.get(key) or "") for key in ("published_date", "filing_date", "title", "snippet", "summary", "primary_doc_description")).strip() for row in rows)
    if text:
        event_quality = evidence.metadata.get("event_quality")
        if evidence.kind == "news_context" and isinstance(event_quality, dict):
            text = {"reported_news": "媒体归因报道：", "opinion": "媒体观点：", "historical_news": "历史新闻线索：", "discovery": "未核实检索线索："}.get(event_quality.get("evidence_role"), "未核实新闻线索：") + text
        reliability = evidence.metadata.get("source_reliability")
        if evidence.kind == "news_context" and isinstance(reliability, dict) and reliability.get("reliability_tier") == "low":
            text = "低可靠度媒体线索，需独立核验：" + text
        return clean_research_text(text)
    cleaned = clean_research_text(raw)
    if cleaned.startswith(("{", "[", "{'", '"')) or re.search(r"\b(?:factor_beta|earnings_estimate|eps_revisions|fact_metadata|positions)\s*[:=]", cleaned):
        return "[数据缺失] 该来源的结构化内容尚不能映射为可读事实，不能直接据此形成结论。"
    if evidence.kind == "news_context":
        reliability = evidence.metadata.get("source_reliability")
        if isinstance(reliability, dict) and reliability.get("reliability_tier") == "low":
            cleaned = "低可靠度媒体线索，需独立核验：" + cleaned
    return re.sub(r"(?<![\w:])(-?\d+\.\d{5,})(?!\w)", lambda match: number(match.group(1), 4), cleaned)
