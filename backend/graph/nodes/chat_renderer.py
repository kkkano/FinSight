# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from typing import Any

from backend.graph.json_utils import json_dumps_safe
from backend.graph.state import GraphState


FORBIDDEN_CHAT_MARKERS = (
    "本轮问题包含",
    "分析对象",
    "get_stock_price",
    "get_company_news",
    "Suggested ladder",
    "暂无技术指标",
    "问题：",
    "后续关注：",
)


def _parse_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if not (text.startswith("{") or text.startswith("[")):
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def _tasks(state: GraphState) -> list[dict[str, Any]]:
    raw = state.get("tasks")
    return [item for item in (raw if isinstance(raw, list) else []) if isinstance(item, dict)]


def _operation_names(state: GraphState) -> set[str]:
    names: set[str] = set()
    op = state.get("operation")
    if isinstance(op, dict) and isinstance(op.get("name"), str):
        names.add(op["name"])
    for task in _tasks(state):
        task_op = task.get("operation")
        if isinstance(task_op, dict) and isinstance(task_op.get("name"), str):
            names.add(task_op["name"])
    return names


def _tickers(state: GraphState) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
    for raw in subject.get("tickers") or []:
        ticker = str(raw or "").strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            values.append(ticker)
    for task in _tasks(state):
        for raw in task.get("tickers") or []:
            ticker = str(raw or "").strip().upper()
            if ticker and ticker not in seen:
                seen.add(ticker)
                values.append(ticker)
    return values


def _step_outputs(state: GraphState) -> list[tuple[dict[str, Any], Any]]:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    plan_ir = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
    steps = plan_ir.get("steps") if isinstance(plan_ir.get("steps"), list) else []
    step_index = {str(step.get("id")): step for step in steps if isinstance(step, dict) and step.get("id")}

    outputs: list[tuple[dict[str, Any], Any]] = []
    for step_id, result in step_results.items():
        if not isinstance(result, dict):
            continue
        output = result.get("output")
        if isinstance(output, dict) and output.get("skipped"):
            continue
        outputs.append((step_index.get(str(step_id), {}), _parse_jsonish(output)))
    return outputs


def _first_matching_output(state: GraphState, names: set[str]) -> Any:
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") in names:
            return output
    return None


def _extract_price(output: Any) -> dict[str, Any]:
    parsed = _parse_jsonish(output)
    if isinstance(parsed, list) and parsed:
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        return {}

    data = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
    price = (
        data.get("price")
        or data.get("current_price")
        or data.get("currentPrice")
        or data.get("regularMarketPrice")
        or data.get("close")
    )
    change = data.get("change") or data.get("regularMarketChange")
    change_pct = (
        data.get("change_percent")
        or data.get("changePercent")
        or data.get("regularMarketChangePercent")
    )
    currency = data.get("currency") or data.get("financialCurrency") or "USD"
    as_of = data.get("as_of") or data.get("timestamp") or data.get("regularMarketTime")
    return {
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "currency": currency,
        "as_of": as_of,
    }


def _format_number(value: Any, digits: int = 2) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    text = str(value or "").strip()
    return text


def _format_price_line(ticker: str, price: dict[str, Any]) -> str:
    if not price.get("price"):
        return f"{ticker} 的实时价格这次没有拿到可用报价。可以稍后重试，或切到行情页确认最新成交价。"

    parts = [f"{ticker} 最新价格约为 {_format_number(price['price'])} {price.get('currency') or 'USD'}"]
    change = price.get("change")
    change_pct = price.get("change_pct")
    if change is not None or change_pct is not None:
        move = []
        if change is not None:
            move.append(_format_number(change))
        if change_pct is not None:
            pct = _format_number(change_pct)
            if pct and not pct.endswith("%"):
                pct += "%"
            move.append(pct)
        if move:
            parts.append("，变动 " + " / ".join(move))
    if price.get("as_of"):
        parts.append(f"。数据时间：{price['as_of']}")
    else:
        parts.append("。")
    return "".join(parts)


def _news_items(output: Any, limit: int = 5) -> list[dict[str, str]]:
    parsed = _parse_jsonish(output)
    rows: list[Any]
    if isinstance(parsed, list):
        rows = parsed
    elif isinstance(parsed, dict):
        nested = parsed.get("articles") or parsed.get("items") or parsed.get("news") or parsed.get("results")
        rows = nested if isinstance(nested, list) else [parsed]
    else:
        rows = []

    items: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("headline") or row.get("summary") or "").strip()
        if not title:
            continue
        url = str(row.get("url") or row.get("link") or row.get("article_url") or "").strip()
        source = str(row.get("source") or row.get("publisher") or "").strip()
        published = str(row.get("published_at") or row.get("published_date") or row.get("date") or "").strip()
        items.append({"title": title, "url": url, "source": source, "published": published[:10]})
        if len(items) >= limit:
            break
    return items


def _technical_text(output: Any) -> str:
    parsed = _parse_jsonish(output)
    if isinstance(parsed, str):
        return parsed.strip()[:700]
    if not isinstance(parsed, dict):
        return ""
    if parsed.get("summary"):
        return str(parsed["summary"]).strip()[:700]
    parts: list[str] = []
    for key, label in (
        ("rsi14", "RSI(14)"),
        ("macd", "MACD"),
        ("macd_signal", "MACD signal"),
        ("ma20", "MA20"),
        ("ma50", "MA50"),
        ("ma200", "MA200"),
        ("support", "支撑"),
        ("resistance", "阻力"),
        ("trend", "趋势"),
    ):
        value = parsed.get(key)
        if value is not None:
            parts.append(f"{label}: {_format_number(value)}")
    return "；".join(parts[:8])


def _append_sources(lines: list[str], sources: list[dict[str, str]]) -> None:
    usable = [item for item in sources if item.get("url")]
    if not usable:
        return
    lines.extend(["", "来源："])
    for item in usable[:5]:
        meta = " / ".join(part for part in (item.get("source"), item.get("published")) if part)
        suffix = f"（{meta}）" if meta else ""
        lines.append(f"- [{item['title']}]({item['url']}){suffix}")


def _sanitize_chat_markdown(text: str) -> str:
    cleaned = str(text or "").strip()
    for marker in FORBIDDEN_CHAT_MARKERS:
        cleaned = cleaned.replace(marker, "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"


def render_chat_markdown(state: GraphState) -> str:
    query = str(state.get("query") or "").strip()
    ticker_label = ", ".join(_tickers(state)) or "这个标的"
    operations = _operation_names(state)
    memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    last_report = memory_context.get("last_report") if isinstance(memory_context.get("last_report"), dict) else None

    if last_report and re.search(r"(刚才|上面|那份|这份|报告|研报|风险|结论|展开|继续|最大)", query):
        title = str(last_report.get("title") or "刚才那份报告").strip()
        summary = str(last_report.get("summary") or "").strip()
        risks = last_report.get("risks") if isinstance(last_report.get("risks"), list) else []
        lines = [f"可以，按《{title}》继续聊。"]
        if "风险" in query and risks:
            lines.append("")
            lines.append("这份报告里最需要先看的风险是：")
            for item in risks[:4]:
                text = str(item or "").strip()
                if text:
                    lines.append(f"- {text}")
        elif summary:
            lines.append("")
            lines.append(summary[:700])
        else:
            lines.append("")
            lines.append("我已经拿到这份报告的会话引用，但摘要不完整；你可以直接问要展开的章节或风险点。")
        return _sanitize_chat_markdown("\n".join(lines))

    price_output = _first_matching_output(state, {"get_stock_price", "price_agent"})
    news_output = _first_matching_output(state, {"get_company_news", "news_agent", "search"})
    technical_output = _first_matching_output(state, {"get_technical_snapshot", "technical_agent"})

    price = _extract_price(price_output)
    news = _news_items(news_output)
    technical = _technical_text(technical_output)

    lines: list[str] = []

    if "price" in operations and "fetch" not in operations and "technical" not in operations and "analyze_impact" not in operations:
        lines.append(_format_price_line(ticker_label, price))
        lines.append("")
        lines.append("如果你要做交易判断，我会把它和盘中走势、成交量、重要新闻一起看；单个报价本身只说明当前成交位置。")
        return _sanitize_chat_markdown("\n".join(lines))

    if "fetch" in operations or "analyze_impact" in operations or news:
        if news:
            lines.append(f"{ticker_label} 这次最值得先看的新闻是：")
            for item in news[:3]:
                lines.append(f"- {item['title']}")
            lines.append("")
            lines.append("对股价的影响要看两点：第一，事件是否会改变收入、利润率、交付或监管预期；第二，价格是否已经提前反映。短线更看情绪和成交量，中期还是要回到业绩指引和估值。")
        else:
            lines.append(f"我没有拿到 {ticker_label} 的可用新闻列表，所以这次不能硬编影响结论。可以重试或换一个更明确的时间范围。")
        if price.get("price"):
            lines.append("")
            lines.append(_format_price_line(ticker_label, price))
        _append_sources(lines, news)
        return _sanitize_chat_markdown("\n".join(lines))

    if "technical" in operations:
        if technical:
            lines.append(f"{ticker_label} 的技术面我会先看这几个信号：{technical}")
            lines.append("")
            lines.append("更重要的是把指标和价格位置合起来看：RSI 只说明动能冷热，MACD 更偏趋势确认，支撑/阻力需要用近期高低点和成交密集区验证。")
        else:
            lines.append(f"这次没有拿到 {ticker_label} 的可用技术指标数据，所以我不能给出 RSI、MACD 或支撑阻力的具体数值。可以稍后重试，或先用 K 线页确认最新行情。")
        return _sanitize_chat_markdown("\n".join(lines))

    if price.get("price"):
        lines.append(_format_price_line(ticker_label, price))
    elif news:
        lines.append(f"我找到了 {ticker_label} 的几条相关信息，核心先看事件是否改变业绩预期：")
        for item in news[:3]:
            lines.append(f"- {item['title']}")
        _append_sources(lines, news)
    else:
        artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
        existing = artifacts.get("draft_markdown")
        if isinstance(existing, str) and existing.strip():
            lines.append(existing.strip())
        else:
            lines.append(f"我理解你的问题是：{query or '继续分析'}。这次可用数据不足，我会先保留上下文；你可以继续补充标的、时间范围或想看的维度。")

    return _sanitize_chat_markdown("\n".join(lines))
