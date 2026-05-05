# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote_plus

from backend.graph.state import GraphState
from backend.utils.quote import parse_quote_payload


FORBIDDEN_CHAT_MARKERS = (
    "本轮问题包含",
    "分析对象",
    "get_stock_price",
    "get_company_news",
    "get_company_info",
    "Suggested ladder",
    "output（）",
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
    parsed_quote = parse_quote_payload(parsed)
    if parsed_quote:
        parsed_quote["currency"] = "USD"
        if isinstance(parsed, dict):
            data = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
            parsed_quote["currency"] = data.get("currency") or data.get("financialCurrency") or "USD"
            parsed_quote["as_of"] = data.get("as_of") or data.get("timestamp") or data.get("regularMarketTime")
        return parsed_quote
    if isinstance(parsed, str):
        parsed_quote = parse_quote_payload(parsed)
        if parsed_quote:
            parsed_quote["currency"] = "USD"
            return parsed_quote
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
        "change_percent": change_pct,
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
    change_pct = price.get("change_percent") if "change_percent" in price else price.get("change_pct")
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


def _price_change_pct(price: dict[str, Any]) -> float | None:
    raw = price.get("change_percent") if "change_percent" in price else price.get("change_pct")
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw or "").strip().replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _news_items(output: Any, limit: int = 5) -> list[dict[str, str]]:
    parsed = _parse_jsonish(output)
    rows: list[Any]
    if isinstance(parsed, list):
        rows = parsed
    elif isinstance(parsed, dict):
        nested = (
            parsed.get("articles")
            or parsed.get("items")
            or parsed.get("news")
            or parsed.get("results")
            or parsed.get("releases")
        )
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
        if not url and title:
            url = f"https://www.google.com/search?q={quote_plus(title)}"
        source = str(row.get("source") or row.get("publisher") or "").strip()
        published = str(row.get("published_at") or row.get("published_date") or row.get("date") or "").strip()
        items.append({"title": title, "url": url, "source": source, "published": published[:10]})
        if len(items) >= limit:
            break
    return items


def _is_low_value_search_item(item: dict[str, str], state: GraphState) -> bool:
    title = str(item.get("title") or "").strip()
    source = str(item.get("source") or "").strip().lower()
    query = str(state.get("query") or "")
    if not title:
        return True
    lowered_title = title.lower()
    if "wikipedia results" in lowered_title:
        tickers = _tickers(state)
        return bool(tickers) or not any(token in query for token in ("维基", "百科", "Wikipedia", "wikipedia"))
    if "search results" in lowered_title:
        return True
    if source == "搜索" and title in {"主题/行业 相关搜索结果", "相关信息 相关搜索结果"}:
        return True
    return False


def _is_low_value_evidence_item(item: dict[str, str], state: GraphState) -> bool:
    if _is_low_value_search_item(item, state):
        return True

    title = str(item.get("title") or "").strip()
    source = str(item.get("source") or "").strip()
    url = str(item.get("url") or "").strip()
    if not title:
        return True

    compact_title = re.sub(r"[\s:：,，.。;；\-_*`'\"“”‘’\[\]{}]+", "", title).lower()
    compact_source = re.sub(r"[\s:：,，.。;；\-_*`'\"“”‘’\[\]{}]+", "", source).lower()
    title_with_no_parens = re.sub(r"[()（）]+", "", compact_title)
    placeholder_titles = {
        "output",
        "searchoutput",
        "tooloutput",
        "result",
        "results",
        "response",
        "summary",
        "none",
        "null",
        "na",
        "n/a",
        "unknown",
        "输出",
        "结果",
    }
    placeholder_sources = {"output", "tool", "internal", "executor", "unknown"}
    combined = f"{title} {source}".lower()

    if title_with_no_parens in placeholder_titles:
        return True
    if compact_source in placeholder_sources and not url and len(title_with_no_parens) <= 24:
        return True
    if any(marker in combined for marker in ("get_company_info", "get_stock_price", "get_company_news")):
        return True
    if title in {"{}", "[]"} or re.fullmatch(r"output\s*[()（）]*", title, flags=re.IGNORECASE):
        return True
    return False


def _search_item_from_output(step: dict[str, Any], output: Any) -> dict[str, str] | None:
    if str(step.get("name") or "") != "search":
        return None
    inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
    search_query = str(inputs.get("query") or "").strip()
    parsed = _parse_jsonish(output)
    title = ""
    if isinstance(parsed, str):
        for line in parsed.splitlines():
            line = line.strip()
            if line:
                title = line[:160]
                break
    elif isinstance(parsed, dict):
        title = str(parsed.get("summary") or parsed.get("title") or parsed.get("snippet") or "").strip()[:160]
    if not title and search_query:
        title = f"{search_query} 相关搜索结果"
    if not title:
        return None
    url_query = search_query or title
    return {
        "title": title,
        "url": f"https://www.google.com/search?q={quote_plus(url_query)}",
        "source": "搜索",
        "published": "",
    }


def _evidence_items(state: GraphState, limit: int = 5) -> list[dict[str, str]]:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts.get("evidence_pool"), list) else []
    items: list[dict[str, str]] = []
    for row in evidence_pool:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("headline") or row.get("summary") or "").strip()
        if not title:
            continue
        url = str(row.get("url") or row.get("link") or row.get("article_url") or "").strip()
        source = str(row.get("source") or row.get("publisher") or "").strip()
        published = str(row.get("published_at") or row.get("published_date") or row.get("date") or "").strip()
        item = {"title": title, "url": url, "source": source, "published": published[:10]}
        if _is_low_value_evidence_item(item, state):
            continue
        items.append(item)
        if len(items) >= limit:
            break
    return items


def _requested_news_link_count(state: GraphState) -> int:
    count = 0
    for task in _tasks(state):
        operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        op_name = str(operation.get("name") or "").strip().lower()
        params = operation.get("params") if isinstance(operation.get("params"), dict) else {}
        if op_name not in {"fetch", "news_impact", "analyze_impact"}:
            continue
        topic = str(params.get("topic") or "").strip().lower()
        wants_links = bool(params.get("include_links"))
        raw_count = params.get("count")
        if topic == "news" or wants_links or raw_count:
            try:
                parsed_count = int(raw_count)
            except Exception:
                parsed_count = 3 if wants_links else 0
            count = max(count, parsed_count)
    return min(max(count, 0), 5)


def _news_search_fallback_items(state: GraphState, *, count: int) -> list[dict[str, str]]:
    tickers = _tickers(state) or ["相关标的"]
    items: list[dict[str, str]] = []
    for ticker in tickers:
        query = f"{ticker} 最新新闻"
        items.append(
            {
                "title": f"{ticker} 最新新闻搜索",
                "url": f"https://www.google.com/search?q={quote_plus(query)}",
                "source": "搜索",
                "published": "",
            }
        )
        if ticker != "相关标的":
            items.append(
                {
                    "title": f"{ticker} Yahoo Finance 新闻",
                    "url": f"https://finance.yahoo.com/quote/{quote_plus(ticker)}/news",
                    "source": "Yahoo Finance",
                    "published": "",
                }
            )
        if len(items) >= count:
            break
    return items[:count]


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


def _format_news_item(item: dict[str, str]) -> str:
    title = item.get("title") or "相关消息"
    url = item.get("url") or ""
    meta = " / ".join(part for part in (item.get("source"), item.get("published")) if part)
    suffix = f"（{meta}）" if meta else ""
    if url:
        return f"[{title}]({url}){suffix}"
    return f"{title}{suffix}"


def _task_index(state: GraphState) -> dict[str, dict[str, Any]]:
    return {str(task.get("id")): task for task in _tasks(state) if task.get("id")}


def _blocked_tasks(state: GraphState) -> list[dict[str, Any]]:
    raw = state.get("blocked_tasks")
    return [item for item in (raw if isinstance(raw, list) else []) if isinstance(item, dict)]


def _append_blocked_notes(lines: list[str], state: GraphState) -> None:
    blocked = _blocked_tasks(state)
    if not blocked:
        return
    notes: list[str] = []
    for item in blocked[:3]:
        question = str(item.get("question") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if reason == "missing_portfolio_holdings":
            text = question or "要判断对你持仓的影响，还需要持仓列表、权重，或你允许我按一个假设组合估算。"
        elif question:
            text = question
        else:
            text = "这部分还缺少必要上下文，所以我先没有硬给结论。"
        if text and text not in notes:
            notes.append(text)
    if not notes:
        return
    if lines and lines[-1] != "":
        lines.append("")
    lines.append("另外还有一部分需要你补充后才能判断：")
    lines.extend(f"- {note}" for note in notes)


def _ticker_for_step(step: dict[str, Any], output: Any, state: GraphState) -> str:
    inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
    ticker = str(inputs.get("ticker") or "").strip().upper()
    if ticker:
        return ticker
    parsed = _parse_jsonish(output)
    if isinstance(parsed, dict):
        ticker = str(parsed.get("ticker") or parsed.get("symbol") or "").strip().upper()
        if ticker:
            return ticker
    task_index = _task_index(state)
    for task_id in step.get("task_ids") or []:
        task = task_index.get(str(task_id))
        tickers = task.get("tickers") if isinstance(task, dict) else None
        if isinstance(tickers, list) and tickers:
            ticker = str(tickers[0] or "").strip().upper()
            if ticker:
                return ticker
        subject_label = str((task or {}).get("subject_label") or "").strip()
        if subject_label:
            return subject_label
    tickers = _tickers(state)
    return tickers[0] if len(tickers) == 1 else ""


def _prices_by_ticker(state: GraphState) -> dict[str, dict[str, Any]]:
    prices: dict[str, dict[str, Any]] = {}
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") not in {"get_stock_price", "price_agent"}:
            continue
        ticker = _ticker_for_step(step, output, state)
        price = _extract_price(output)
        if ticker and price:
            prices[ticker] = price
    if not prices:
        first = _first_matching_output(state, {"get_stock_price", "price_agent"})
        price = _extract_price(first)
        tickers = _tickers(state)
        if price and tickers:
            prices[tickers[0]] = price
    return prices


def _news_by_ticker(state: GraphState) -> dict[str, list[dict[str, str]]]:
    news_by_ticker: dict[str, list[dict[str, str]]] = {}
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") not in {"get_company_news", "news_agent", "search", "get_official_macro_releases", "get_authoritative_media_news"}:
            continue
        ticker = _ticker_for_step(step, output, state) or "相关信息"
        items = _news_items(output)
        if not items:
            search_item = _search_item_from_output(step, output)
            if search_item:
                items = [search_item]
        items = [item for item in items if not _is_low_value_evidence_item(item, state)]
        if items:
            news_by_ticker.setdefault(ticker, []).extend(items)

    for ticker, items in list(news_by_ticker.items()):
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for item in items:
            key = item.get("url") or item.get("title") or ""
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            deduped.append(item)
        news_by_ticker[ticker] = deduped[:5]
    return news_by_ticker


def _url_fetch_rows(state: GraphState) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") != "fetch_url_content":
            continue
        parsed = _parse_jsonish(output)
        inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
        url = str(inputs.get("url") or "").strip()
        title = ""
        snippet = ""
        error = ""
        if isinstance(parsed, dict):
            url = str(parsed.get("final_url") or parsed.get("url") or url).strip()
            title = str(parsed.get("title") or "").strip()
            snippet = str(parsed.get("content") or parsed.get("text") or parsed.get("snippet") or "").strip()
            error = str(parsed.get("error") or "").strip()
        elif isinstance(parsed, str):
            snippet = parsed.strip()
        rows.append(
            {
                "ticker": _ticker_for_step(step, output, state),
                "url": url,
                "title": title,
                "snippet": snippet[:420],
                "error": error,
            }
        )
    return rows


def _append_url_fetch_notes(lines: list[str], state: GraphState) -> None:
    rows = _url_fetch_rows(state)
    if not rows:
        return
    if lines and lines[-1] != "":
        lines.append("")
    for row in rows[:3]:
        label = row.get("title") or "这个链接"
        url = row.get("url") or ""
        error = row.get("error") or ""
        snippet = row.get("snippet") or ""
        if error:
            detail = f"（{error}）" if error else ""
            if url:
                if label == "这个链接":
                    lines.append(f"我试着读取这个链接，但这次没有拿到可读正文{detail}：{url}。所以我先不把它当作支持证据，需要换成可访问正文后再判断。")
                else:
                    lines.append(f"我试着读取 {label}，但这次没有拿到可读正文{detail}：{url}。所以我先不把它当作支持证据，需要换成可访问正文后再判断。")
            else:
                lines.append(f"我试着读取{label}，但这次没有拿到可读正文{detail}，所以我先不把它当作支持证据。")
        elif snippet:
            linked = f"[{row.get('title') or url}]({url})" if url else (row.get("title") or label)
            lines.append(f"{label} 相关链接我已读到正文，先看这点：{linked}，{snippet}")


def _technical_by_ticker(state: GraphState) -> dict[str, str]:
    rows: dict[str, str] = {}
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") not in {"get_technical_snapshot", "technical_agent"}:
            continue
        ticker = _ticker_for_step(step, output, state)
        text = _technical_text(output)
        if ticker and text:
            rows[ticker] = text
    return rows


def _render_vars(state: GraphState) -> dict[str, str]:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    raw = artifacts.get("render_vars") if isinstance(artifacts.get("render_vars"), dict) else {}
    return {str(key): str(value).strip() for key, value in raw.items() if isinstance(value, str) and value.strip()}


def _useful_render_var(render_vars: dict[str, str], key: str) -> str:
    value = str(render_vars.get(key) or "").strip()
    if not value:
        return ""
    if any(
        marker in value
        for marker in (
            "暂无",
            "未获取到",
            "未执行",
            "当前缺少明确对象",
            "operation=`",
            "当前操作",
            "点击“生成研报”",
            "你想先看哪一条",
            "如需我解读",
        )
    ):
        return ""
    return value


def _subject_types(state: GraphState) -> set[str]:
    values: set[str] = set()
    subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
    subject_type = str(subject.get("subject_type") or "").strip().lower()
    if subject_type:
        values.add(subject_type)
    for task in _tasks(state):
        task_type = str(task.get("subject_type") or "").strip().lower()
        if task_type:
            values.add(task_type)
    return values


def _has_macro_context(state: GraphState) -> bool:
    return "macro" in _subject_types(state)


def _macro_impact_fallback_lines(state: GraphState) -> list[str]:
    tickers = _tickers(state)
    target = ", ".join(tickers[:4]) if tickers else "这个宏观问题"
    return [
        f"这轮没有合成出足够可靠的宏观影响判断，我先不硬给 {target} 下结论。",
        "可以继续补充你想看的市场、标的或时间窗口，我会按可验证证据接着分析。",
    ]


def _macro_mechanism_lines(state: GraphState) -> list[str]:
    tickers = _tickers(state)
    target = ", ".join(tickers[:4]) if tickers else "这类高估值资产"
    return [
        "利率影响估值，核心是折现率和机会成本：利率上行会降低远期现金流的现值，也会让无风险收益率更有吸引力。",
        f"所以 {target} 更敏感，后面要看利率预期是否继续压低估值倍数，以及业绩指引能不能抵消这部分压力。",
        "这类问题我不硬给单点结论，先看利率预期、业绩指引和价格反应能否互相验证。",
    ]


def _focus_task_present(state: GraphState) -> bool:
    if _portfolio_positions(state):
        return False
    for task in _tasks(state):
        if str(task.get("subject_type") or "").strip().lower() != "portfolio":
            continue
        op = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        if str(op.get("name") or "").strip().lower() == "qa":
            return True
    return False


def _focus_line(state: GraphState) -> str:
    tickers = _tickers(state)
    ticker_label = "/".join(tickers[:3]) if tickers else "相关标的"
    if _has_macro_context(state):
        return f"一句话：先关注利率和通胀预期是否继续压估值，再看 {ticker_label} 的业绩指引和价格反应能不能抵消压力。"
    return f"一句话：先关注 {ticker_label} 的价格反应是否被后续新闻、财报指引和成交量确认。"


def _has_url_context(state: GraphState) -> bool:
    if _url_fetch_rows(state):
        return True
    for task in _tasks(state):
        operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        params = operation.get("params") if isinstance(operation.get("params"), dict) else {}
        if str(params.get("url") or "").startswith(("http://", "https://")):
            return True
    return False


def _risk_or_qa_fallback_lines(state: GraphState, risks: str = "") -> list[str]:
    risk_points: list[str] = []
    for line in str(risks or "").splitlines():
        text = line.strip(" -•\t")
        if not text:
            continue
        if any(marker in text for marker in ("仅供参考", "不构成投资建议", "免责声明")):
            continue
        risk_points.append(text)
    if risk_points:
        return risk_points[:5]

    return ["这轮没有足够的可靠证据支撑风险判断，我先不硬编风险点。"]


def _append_render_var_block(lines: list[str], text: str) -> None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(cleaned)


def _sanitize_chat_markdown(text: str) -> str:
    cleaned = str(text or "").strip()
    for marker in FORBIDDEN_CHAT_MARKERS:
        cleaned = cleaned.replace(marker, "")
    cleaned = re.sub(r"(?m)^\s*\*{2,}\s*$\n?", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"


def _finalize_chat_markdown(lines: list[str], state: GraphState) -> str:
    _append_blocked_notes(lines, state)
    return _sanitize_chat_markdown("\n".join(lines))


def _portfolio_positions(state: GraphState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in _tasks(state):
        if str(task.get("subject_type") or "").strip().lower() != "portfolio":
            continue
        params = task.get("params") if isinstance(task.get("params"), dict) else {}
        positions = params.get("positions") if isinstance(params.get("positions"), list) else []
        for item in positions:
            if isinstance(item, dict) and str(item.get("ticker") or "").strip():
                rows.append(item)
    if rows:
        return rows

    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    raw = ui_context.get("positions") or ui_context.get("holdings") or ui_context.get("portfolio")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict) and str(item.get("ticker") or item.get("symbol") or "").strip()]
    if isinstance(raw, dict):
        normalized: list[dict[str, Any]] = []
        for key, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("ticker", key)
                normalized.append(item)
            else:
                normalized.append({"ticker": key, "weight": value})
        return normalized
    return []


def _render_portfolio_markdown(state: GraphState) -> str:
    positions = _portfolio_positions(state)
    tickers = _tickers(state)
    render_vars = _render_vars(state)
    analysis_block = (
        _useful_render_var(render_vars, "impact_analysis")
        or _useful_render_var(render_vars, "conclusion")
        or _useful_render_var(render_vars, "investment_summary")
    )
    risks = _useful_render_var(render_vars, "risks")
    label = ", ".join(tickers[:6]) if tickers else "当前持仓"
    lines = [f"我先按你给的持仓看：{label}。"]
    if positions:
        lines.append("")
        lines.append("持仓锚点：")
        for item in positions[:8]:
            ticker = str(item.get("ticker") or item.get("symbol") or "").strip().upper()
            weight = item.get("weight")
            if weight is None:
                lines.append(f"- {ticker}")
            else:
                lines.append(f"- {ticker}: 权重约 {weight}")
    if analysis_block:
        _append_render_var_block(lines, analysis_block)
    elif risks:
        _append_render_var_block(lines, risks)
    else:
        lines.extend(
            [
                "",
                "这轮还缺少可验证的持仓影响证据，我不会按固定框架硬编单条新闻冲击。",
                "你可以补充新闻、持仓权重或时间窗口，我会按证据继续判断。",
            ]
        )
    return _finalize_chat_markdown(lines, state)


def _render_compare_or_basket_markdown(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
    news_map: dict[str, list[dict[str, str]]],
    comparison_conclusion: str,
    comparison_metrics: str,
) -> str:
    tickers = _tickers(state)
    ticker_label = ", ".join(tickers) or "这些标的"
    lines: list[str] = []

    if prices or news_map:
        lines.append(f"我先按 {ticker_label} 这组代表标的看。")
        for ticker in tickers[:6]:
            parts: list[str] = []
            price = prices.get(ticker)
            if price and price.get("price"):
                parts.append(_format_price_line(ticker, price))
            items = news_map.get(ticker) or []
            if items:
                parts.append("相关消息：" + "；".join(_format_news_item(item) for item in items[:2]))
            if parts:
                lines.append("")
                lines.append(f"{ticker}:")
                lines.extend(f"- {part}" for part in parts)

    if comparison_conclusion:
        _append_render_var_block(lines, comparison_conclusion)
    if comparison_metrics:
        _append_render_var_block(lines, comparison_metrics)
    if not comparison_conclusion and len(tickers) >= 2:
        comparable = [
            (ticker, _price_change_pct(prices.get(ticker) or {}))
            for ticker in tickers
            if _price_change_pct(prices.get(ticker) or {}) is not None
        ]
        if len(comparable) >= 2:
            ranked = sorted(comparable, key=lambda item: item[1], reverse=True)
            winner, winner_pct = ranked[0]
            runner, runner_pct = ranked[1]
            lines.append("")
            lines.append(
                f"按这次拿到的涨跌幅，{winner} 暂时更强（{winner_pct:.2f}% vs {runner} {runner_pct:.2f}%）。"
            )
        if news_map:
            lines.append("风险上先看新闻标题能不能落实到收入、利润率或指引；只靠标题还不能证明基本面已经变化。")

    if not lines:
        lines.append(f"我先按 {ticker_label} 这组标的理解。当前没有拿到足够的可引用行情或新闻，所以不硬给排序；更稳的是等价格和新闻源恢复后再比较强弱。")

    sources = [item for items in news_map.values() for item in items]
    _append_sources(lines, sources)
    return _finalize_chat_markdown(lines, state)


def render_chat_markdown(state: GraphState) -> str:
    query = str(state.get("query") or "").strip()
    ticker_label = ", ".join(_tickers(state)) or "这个标的"
    operations = _operation_names(state)
    memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    last_report = memory_context.get("last_report") if isinstance(memory_context.get("last_report"), dict) else None
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    decision = artifacts.get("conversation_decision") if isinstance(artifacts.get("conversation_decision"), dict) else {}
    binding = decision.get("context_binding") if isinstance(decision.get("context_binding"), dict) else {}
    render_vars = _render_vars(state)

    if last_report and binding.get("source") == "last_report":
        title = str(last_report.get("title") or "刚才那份报告").strip()
        summary = str(last_report.get("summary") or "").strip()
        risks = last_report.get("risks") if isinstance(last_report.get("risks"), list) else []
        lines = [f"可以，按《{title}》继续聊。"]
        if risks:
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
        return _finalize_chat_markdown(lines, state)

    prices = _prices_by_ticker(state)
    news_map = _news_by_ticker(state)
    technical_map = _technical_by_ticker(state)
    price = next(iter(prices.values()), {})
    news = [item for items in news_map.values() for item in items]
    technical = next(iter(technical_map.values()), "")
    evidence_items = _evidence_items(state)
    price_snapshot = _useful_render_var(render_vars, "price_snapshot")
    technical_snapshot = _useful_render_var(render_vars, "technical_snapshot")
    news_summary = _useful_render_var(render_vars, "news_summary")
    comparison_conclusion = _useful_render_var(render_vars, "comparison_conclusion")
    comparison_metrics = _useful_render_var(render_vars, "comparison_metrics")
    conclusion = _useful_render_var(render_vars, "conclusion")
    next_watch = _useful_render_var(render_vars, "next_watch")
    risks = _useful_render_var(render_vars, "risks")
    has_url_context = _has_url_context(state)

    lines: list[str] = []

    portfolio_tasks = [
        task
        for task in _tasks(state)
        if str(task.get("subject_type") or "").strip().lower() == "portfolio"
    ]
    non_portfolio_tasks = [
        task
        for task in _tasks(state)
        if str(task.get("subject_type") or "").strip().lower() != "portfolio"
    ]
    if portfolio_tasks and (_portfolio_positions(state) or not non_portfolio_tasks):
        return _render_portfolio_markdown(state)

    if has_url_context:
        for ticker in (_tickers(state) or list(prices.keys()))[:5]:
            ticker_price = prices.get(ticker)
            if ticker_price:
                lines.append(_format_price_line(ticker, ticker_price))
        _append_url_fetch_notes(lines, state)
        if _has_macro_context(state):
            if lines and lines[-1] != "":
                lines.append("")
            lines.extend(_macro_mechanism_lines(state))
        if lines and "关注" not in "\n".join(lines):
            lines.append("")
            lines.append(_focus_line(state))
        if not lines:
            lines.append("这个链接和宏观问题需要更多可读证据；我先不按 URL 字面内容硬下结论。")
        _append_sources(lines, news or evidence_items)
        return _finalize_chat_markdown(lines, state)

    if "price" in operations and "fetch" not in operations and "technical" not in operations and "analyze_impact" not in operations:
        target_tickers = _tickers(state) or list(prices.keys()) or [ticker_label]
        for ticker in target_tickers[:5]:
            lines.append(_format_price_line(ticker, prices.get(ticker, price if len(target_tickers) == 1 else {})))
        return _finalize_chat_markdown(lines, state)

    if "compare" in operations:
        return _render_compare_or_basket_markdown(
            state,
            prices=prices,
            news_map=news_map,
            comparison_conclusion=comparison_conclusion,
            comparison_metrics=comparison_metrics,
        )

    if "fetch" in operations or "analyze_impact" in operations or news:
        analysis_block = (
            _useful_render_var(render_vars, "impact_analysis")
            or _useful_render_var(render_vars, "conclusion")
            or _useful_render_var(render_vars, "investment_summary")
        )
        if news_map:
            for ticker, items in list(news_map.items())[:4]:
                lines.append(f"{ticker} 我找到几条比较相关的消息：")
                for item in items[:3]:
                    lines.append(f"- {_format_news_item(item)}")
                if ticker in prices and prices[ticker].get("price"):
                    lines.append(f"- {_format_price_line(ticker, prices[ticker])}")
                lines.append("")
            for ticker, ticker_price in prices.items():
                if ticker not in news_map and ticker_price.get("price"):
                    lines.append(_format_price_line(ticker, ticker_price))
                    lines.append("")
            while lines and lines[-1] == "":
                lines.pop()
            _append_url_fetch_notes(lines, state)
            lines.append("")
            if analysis_block:
                lines.append(analysis_block)
            elif _has_macro_context(state):
                lines.extend(_macro_mechanism_lines(state))
            else:
                lines.append("我先只列出可引用消息；这轮没有足够证据支撑进一步影响判断。")
            if next_watch and "关注" not in "\n".join(lines):
                lines.append("")
                lines.append(next_watch)
            elif _focus_task_present(state) and "关注" not in "\n".join(lines):
                lines.append("")
                lines.append(_focus_line(state))
        else:
            fallback_items = evidence_items
            if fallback_items:
                lines.append(f"{ticker_label} 这次先看这些来源：")
                for item in fallback_items[:4]:
                    lines.append(f"- {_format_news_item(item)}")
                if analysis_block:
                    _append_render_var_block(lines, analysis_block)
                elif _has_macro_context(state):
                    lines.append("")
                    lines.extend(_macro_mechanism_lines(state))
            elif news_summary:
                lines.append(news_summary)
                if analysis_block:
                    _append_render_var_block(lines, analysis_block)
            elif risks:
                lines.extend(_risk_or_qa_fallback_lines(state, risks))
            else:
                requested_link_count = _requested_news_link_count(state)
                if requested_link_count:
                    fallback_links = _news_search_fallback_items(state, count=requested_link_count)
                    lines.append(f"实时新闻源这次没有返回 {ticker_label} 的可用条目，我先给你可点击的检索入口，避免硬编新闻：")
                    for item in fallback_links:
                        lines.append(f"- {_format_news_item(item)}")
                    evidence_items = fallback_links
                else:
                    lines.append(f"我没有拿到 {ticker_label} 的可用新闻列表，所以这次不能硬编影响结论。可以重试或换一个更明确的时间范围。")
        if not news_map and price.get("price"):
            lines.append("")
            lines.append(_format_price_line(ticker_label, price))
        if not news_map:
            _append_url_fetch_notes(lines, state)
        if _focus_task_present(state) and "关注" not in "\n".join(lines):
            lines.append("")
            lines.append(_focus_line(state))
        _append_sources(lines, news or evidence_items)
        return _finalize_chat_markdown(lines, state)

    if "technical" in operations:
        if price_snapshot:
            _append_render_var_block(lines, price_snapshot)
        if technical_map:
            for ticker, text in list(technical_map.items())[:4]:
                lines.append(f"{ticker} 的技术面我会先看这几个信号：{text}")
            if conclusion:
                _append_render_var_block(lines, conclusion)
        elif technical:
            lines.append(f"{ticker_label} 的技术面我会先看这几个信号：{technical}")
        elif technical_snapshot:
            _append_render_var_block(lines, technical_snapshot)
        else:
            lines.append(f"这次没有拿到 {ticker_label} 的可用技术指标数据，所以我不能给出 RSI、MACD 或支撑阻力的具体数值。可以稍后重试，或先用 K 线页确认最新行情。")
        return _finalize_chat_markdown(lines, state)

    if price.get("price"):
        lines.append(_format_price_line(ticker_label, price))
    elif news:
        lines.append(f"我找到了 {ticker_label} 的几条相关信息，核心先看事件是否改变业绩预期：")
        for item in news[:3]:
            lines.append(f"- {item['title']}")
        _append_sources(lines, news)
    elif evidence_items:
        lines.append(f"我先按 {ticker_label} 相关来源给你看要点：")
        for item in evidence_items[:4]:
            lines.append(f"- {_format_news_item(item)}")
        _append_sources(lines, evidence_items)
    elif risks:
        lines.extend(_risk_or_qa_fallback_lines(state, risks))
    elif comparison_conclusion:
        _append_render_var_block(lines, comparison_conclusion)
        if risks:
            _append_render_var_block(lines, risks)
    elif "daily_brief" in operations:
        lines.append(f"{ticker_label} 先给你一个很短的快评。")
        if conclusion:
            lines.append(conclusion)
        elif risks:
            lines.append(risks)
        else:
            lines.append("这次还没拿到足够的实时数据，我会继续看价格和新闻后再补一句判断。")
    elif conclusion:
        lines.append(conclusion)
    else:
        existing = artifacts.get("draft_markdown")
        if isinstance(existing, str) and existing.strip():
            lines.append(existing.strip())
        else:
            target = f"（{ticker_label}）" if _tickers(state) else ""
            lines.append(f"我理解你的问题是：{query or '继续分析'}{target}。这次可用数据不足，我会先保留上下文；你可以继续补充标的、时间范围或想看的维度。")

    return _finalize_chat_markdown(lines, state)
