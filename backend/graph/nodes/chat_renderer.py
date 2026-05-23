# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import quote_plus

from backend.graph.memory_scope import current_report_context
from backend.graph.state import GraphState
from backend.graph.understanding_v2 import VALUATION_COMPARE_LIGHT_PROFILE
from backend.utils.quote import parse_quote_payload

try:  # Optional live-news fallback for link-required chat answers.
    from backend.config.ticker_mapping import COMPANY_MAP
    from backend.tools.authoritative_feeds import get_authoritative_media_news
    from backend.tools.news import get_company_news
except Exception:  # pragma: no cover - renderer must still work without live tool imports.
    COMPANY_MAP = {}
    get_authoritative_media_news = None
    get_company_news = None


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


def _is_citable_url(url: str) -> bool:
    text = str(url or "").strip()
    if not text.startswith(("http://", "https://")):
        return False
    lowered = text.lower()
    non_article_markers = (
        "google.com/search",
        "finance.yahoo.com/search",
        "finance.yahoo.com/quote/",
        "benzinga.com/search",
        "reuters.com/site-search",
        "cnbc.com/search",
        "marketwatch.com/search",
    )
    return not any(marker in lowered for marker in non_article_markers)


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
            or parsed.get("transcripts")
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
        if not _is_citable_url(url):
            url = ""
        source = str(row.get("source") or row.get("publisher") or "").strip()
        published = str(row.get("published_at") or row.get("published_date") or row.get("date") or "").strip()
        snippet = str(
            row.get("snippet")
            or row.get("description")
            or row.get("content")
            or row.get("summary")
            or ""
        ).strip()
        items.append(
            {
                "title": title,
                "url": url,
                "source": source,
                "published": published[:10],
                "snippet": snippet[:500],
                "type": str(row.get("type") or "").strip(),
            }
        )
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
        if not _is_citable_url(url):
            url = ""
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


def _reply_contract_requires_links(state: GraphState) -> bool:
    contract = state.get("reply_contract") if isinstance(state.get("reply_contract"), dict) else {}
    constraints = contract.get("source_constraints") if isinstance(contract.get("source_constraints"), dict) else {}
    return bool(constraints.get("requires_links"))


def _news_article_fallback_allowed(state: GraphState) -> bool:
    """Only supplement missing article links after a grounded research path."""
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    decision = artifacts.get("conversation_decision") if isinstance(artifacts.get("conversation_decision"), dict) else {}
    decision_route = str(decision.get("execution_route") or "").strip().lower()
    if decision_route:
        return decision_route == "research"

    understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    understanding_route = str(understanding.get("route") or "").strip().lower()
    if understanding_route:
        return understanding_route == "research"

    output_mode = str(state.get("output_mode") or "").strip().lower()
    if output_mode == "investment_report":
        return True

    return bool(_tasks(state))


def _news_article_fallback_budget_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("CHAT_RENDER_NEWS_FALLBACK_BUDGET_SECONDS", "5")))
    except Exception:
        return 5.0


def _news_article_fallback_max_tickers() -> int:
    try:
        return max(0, min(int(os.getenv("CHAT_RENDER_NEWS_FALLBACK_MAX_TICKERS", "1")), 4))
    except Exception:
        return 1


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


def _append_news_source_page_links(lines: list[str], state: GraphState, *, count: int) -> None:
    tickers = [
        ticker
        for ticker in _tickers(state)
        if re.match(r"^[A-Z][A-Z0-9.\-=]{0,9}$", ticker) and ticker not in {"I", "ME", "YOU"}
    ]
    if not tickers or count <= 0:
        return
    if lines and lines[-1] != "":
        lines.append("")
    lines.append("I did not get per-article URLs for every headline, so I am linking source pages for verification rather than treating them as article citations:")
    for ticker in tickers[:count]:
        lines.append(f"- [{ticker} Yahoo Finance news](https://finance.yahoo.com/quote/{quote_plus(ticker)}/news)")


def _news_map_has_citable_url(news_map: dict[str, list[dict[str, str]]]) -> bool:
    return any(
        _is_citable_url(str(item.get("url") or ""))
        for items in news_map.values()
        for item in items
    )


def _company_name_for_ticker(ticker: str) -> str:
    symbol = str(ticker or "").strip().upper()
    mapped = COMPANY_MAP.get(symbol) if isinstance(COMPANY_MAP, dict) else None
    return str(mapped or "").strip()


def _news_item_matches_subject(item: dict[str, str], ticker: str) -> bool:
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return True
    company_name = _company_name_for_ticker(symbol)
    haystack = " ".join(str(item.get(key) or "") for key in ("title", "source")).lower()
    if symbol.lower() in haystack:
        return True
    return bool(company_name and company_name.lower() in haystack)


def _dedupe_news_items(items: list[dict[str, str]], *, limit: int) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in items:
        if not _is_citable_url(str(item.get("url") or "")):
            continue
        key = str(item.get("url") or item.get("title") or "").strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def _direct_news_article_fallback_map(state: GraphState, *, count: int) -> dict[str, list[dict[str, str]]]:
    """Fetch citable article URLs when the planned news path produced no links.

    This is intentionally narrow: it only runs for explicit link-required news
    turns and only accepts article-like URLs, never search or quote listing pages.
    """
    budget_seconds = _news_article_fallback_budget_seconds()
    max_tickers = _news_article_fallback_max_tickers()
    if budget_seconds <= 0 or max_tickers <= 0:
        return {}

    started_at = time.monotonic()
    target_count = max(1, min(count, 3))
    result: dict[str, list[dict[str, str]]] = {}
    tickers = [
        ticker
        for ticker in _tickers(state)
        if re.match(r"^[A-Z][A-Z0-9.\-=]{0,9}$", ticker) and ticker not in {"I", "ME", "YOU"}
    ]

    def _has_budget() -> bool:
        return (time.monotonic() - started_at) < budget_seconds

    for ticker in tickers[:max_tickers]:
        if not _has_budget():
            break
        items: list[dict[str, str]] = []
        if callable(get_company_news):
            try:
                items.extend(
                    _news_items(
                        get_company_news(ticker, limit=max(target_count, 3), fast=True),
                        limit=target_count * 2,
                    )
                )
            except Exception:
                pass

        if (
            _has_budget()
            and len(_dedupe_news_items(items, limit=target_count)) < target_count
            and callable(get_authoritative_media_news)
        ):
            company_name = _company_name_for_ticker(ticker)
            query = " ".join(part for part in (ticker, company_name, "news") if part)
            try:
                payload = get_authoritative_media_news(query, max_results=max(target_count * 2, 5))
            except Exception:
                payload = {}
            rows = payload.get("articles") if isinstance(payload, dict) else payload
            authoritative_items = _news_items(rows if isinstance(rows, list) else [], limit=target_count * 2)
            items.extend(item for item in authoritative_items if _news_item_matches_subject(item, ticker))

        usable = _dedupe_news_items(
            [item for item in items if not _is_low_value_evidence_item(item, state)],
            limit=target_count,
        )
        if usable:
            result[ticker] = usable

    if not result and not tickers and _has_budget() and callable(get_authoritative_media_news):
        try:
            payload = get_authoritative_media_news(str(state.get("query") or "market news"), max_results=max(target_count * 2, 5))
        except Exception:
            payload = {}
        rows = payload.get("articles") if isinstance(payload, dict) else payload
        usable = _dedupe_news_items(_news_items(rows if isinstance(rows, list) else [], limit=target_count * 2), limit=target_count)
        if usable:
            result["相关信息"] = usable

    return result


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


def _technical_action_line(ticker: str, text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    support_match = re.search(r"支撑\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)", cleaned)
    resistance_match = re.search(r"阻力\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)", cleaned)
    support = support_match.group(1) if support_match else ""
    resistance = resistance_match.group(1) if resistance_match else ""
    if any(marker in cleaned for marker in ("偏强", "上升趋势", "多头排列")):
        bias = "偏强"
    elif any(marker in cleaned for marker in ("偏弱", "下降趋势", "空头排列")):
        bias = "偏弱"
    elif "空头" in cleaned:
        bias = "信号有分歧"
    else:
        bias = "中性"

    if support and resistance:
        return (
            f"可执行结论：{ticker} 技术状态{bias}；接近阻力 {resistance} 不追高，"
            f"放量突破后再上调目标；回踩支撑 {support} 不破再考虑低吸，跌破则降低仓位或止损。"
        )
    if support:
        return f"可执行结论：{ticker} 技术状态{bias}；先盯支撑 {support}，跌破则降低仓位，站稳后再看量能确认。"
    if resistance:
        return f"可执行结论：{ticker} 技术状态{bias}；先盯阻力 {resistance}，未放量突破前避免追高。"
    return f"可执行结论：{ticker} 技术状态{bias}；等价格、MACD 和成交量同向确认后再加仓，信号冲突时控制仓位。"


def _append_sources(lines: list[str], sources: list[dict[str, str]]) -> None:
    usable = [item for item in sources if _is_citable_url(str(item.get("url") or ""))]
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
    if not _is_citable_url(url):
        url = ""
    meta = " / ".join(part for part in (item.get("source"), item.get("published")) if part)
    suffix = f"（{meta}）" if meta else ""
    if url:
        return f"[{title}]({url}){suffix}"
    return f"{title}{suffix}"


def _append_missing_article_url_note(lines: list[str], items: list[dict[str, str]]) -> None:
    if not items:
        return
    missing = [item for item in items if not _is_citable_url(str(item.get("url") or ""))]
    if not missing:
        return
    if lines and lines[-1] != "":
        lines.append("")
    lines.append("Some returned headlines did not include usable article URLs, so I am not treating search pages as citations.")


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
        if str(step.get("name") or "") not in {
            "get_company_news",
            "news_agent",
            "search",
            "get_official_macro_releases",
            "get_authoritative_media_news",
            "get_earnings_call_transcripts",
        }:
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
        relevant = _filter_news_by_company_identity(state, deduped)
        if relevant:
            deduped = relevant
        deduped.sort(
            key=lambda item: 0
            if str(item.get("type") or "").strip().lower() == "transcript"
            or "transcript" in str(item.get("title") or "").strip().lower()
            else 1
        )
        news_by_ticker[ticker] = deduped[:8]
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
        label = row.get("title") or row.get("ticker") or "这个链接"
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


def _url_fetch_all_failed(state: GraphState) -> bool:
    rows = _url_fetch_rows(state)
    if not rows:
        return False
    return not any((row.get("snippet") or "").strip() and not (row.get("error") or "").strip() for row in rows)


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


def _successful_synthesis_render_vars(state: GraphState) -> dict[str, str]:
    trace = state.get("trace") if isinstance(state.get("trace"), dict) else {}
    runtime = trace.get("synthesize_runtime") if isinstance(trace.get("synthesize_runtime"), dict) else {}
    legacy_runtime = trace.get("synthesize") if isinstance(trace.get("synthesize"), dict) else {}
    synthesized = (
        str(runtime.get("mode") or "").strip().lower() == "llm"
        and runtime.get("fallback") is False
    ) or (
        str(legacy_runtime.get("mode") or "").strip().lower() == "llm"
        and legacy_runtime.get("fallback") is False
    )
    if not synthesized:
        return {}
    return _render_vars(state)


def _synthesis_points(state: GraphState, keys: tuple[str, ...], *, limit: int = 4) -> list[str]:
    render_vars = _successful_synthesis_render_vars(state)
    points: list[str] = []
    seen: set[str] = set()
    for key in keys:
        value = _useful_render_var(render_vars, key)
        if not value:
            continue
        for line in value.splitlines():
            text = line.strip(" -•\t")
            if not text or text in seen:
                continue
            seen.add(text)
            points.append(text)
            if len(points) >= limit:
                return points
    return points


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


def _sanitize_agent_summary(summary: str) -> str:
    cleaned = str(summary or "").strip()
    cleaned = re.sub(r"^(?:[A-Za-z]+Agent|[A-Za-z]+_agent)\s*[:：]\s*", "", cleaned)

    def _compact_money(match: re.Match[str]) -> str:
        raw = match.group(1).replace(",", "")
        try:
            return _format_compact_number(float(raw), money=True)
        except Exception:
            return match.group(0)

    cleaned = re.sub(r"\$(\d{1,3}(?:,\d{3}){2,}|\d{9,})", _compact_money, cleaned)
    return cleaned[:900]


def _agent_summary(state: GraphState, names: set[str]) -> str:
    output = _first_matching_output(state, names)
    parsed = _parse_jsonish(output)
    if isinstance(parsed, dict):
        summary = str(parsed.get("summary") or parsed.get("analysis") or "").strip()
        if summary:
            return _sanitize_agent_summary(summary)
    if isinstance(parsed, str) and parsed.strip():
        return _sanitize_agent_summary(parsed)
    return ""


def _agent_risks(state: GraphState, names: set[str]) -> list[str]:
    risks: list[str] = []
    for step, output in _step_outputs(state):
        if str(step.get("name") or "") not in names:
            continue
        parsed = _parse_jsonish(output)
        if isinstance(parsed, dict):
            raw = parsed.get("risks")
            if isinstance(raw, list):
                for item in raw:
                    text = str(item or "").strip()
                    if text and text not in risks:
                        risks.append(text[:260])
            summary = str(parsed.get("summary") or "").strip()
            if summary and any(token in summary for token in ("风险", "回撤", "跌破", "risk", "drawdown")):
                clipped = summary[:420]
                if clipped not in risks:
                    risks.append(clipped)
        elif isinstance(parsed, str) and parsed.strip():
            text = parsed.strip()
            if any(token in text for token in ("风险", "回撤", "跌破", "risk", "drawdown")):
                clipped = text[:420]
                if clipped not in risks:
                    risks.append(clipped)
    return risks[:4]


def _format_compact_number(value: Any, *, money: bool = False) -> str:
    try:
        number = float(value)
    except Exception:
        return str(value or "").strip()
    abs_number = abs(number)
    prefix = "$" if money else ""
    if abs_number >= 1_000_000_000:
        return f"{prefix}{number / 1_000_000_000:.2f}B"
    if abs_number >= 1_000_000:
        return f"{prefix}{number / 1_000_000:.2f}M"
    if abs_number >= 1_000:
        return f"{prefix}{number / 1_000:.2f}K"
    return f"{prefix}{number:.2f}"


def _latest_quarter_facts(state: GraphState) -> list[str]:
    payload = _first_matching_output(state, {"get_sec_company_facts_quarterly"})
    parsed = _parse_jsonish(payload)
    if not isinstance(parsed, dict) or parsed.get("error"):
        return []

    periods = parsed.get("periods") if isinstance(parsed.get("periods"), list) else []
    period_label = str(periods[0] if periods else "最新季度").strip() or "最新季度"
    metric_specs = (
        ("revenue", "营收", True),
        ("gross_profit", "毛利", True),
        ("operating_income", "经营利润", True),
        ("net_income", "净利润", True),
        ("eps", "EPS", False),
        ("operating_cash_flow", "经营现金流", True),
        ("free_cash_flow", "自由现金流", True),
    )

    lines: list[str] = []
    for key, label, money in metric_specs:
        values = parsed.get(key)
        if not isinstance(values, list) or not values:
            continue
        formatted = _format_compact_number(values[0], money=money)
        if formatted:
            lines.append(f"{period_label} {label} {formatted}")
        if len(lines) >= 4:
            break
    return lines


def _case_insensitive_get(row: dict[str, Any], key: str) -> Any:
    if key in row:
        return row.get(key)
    wanted = key.lower()
    for raw_key, value in row.items():
        if str(raw_key).lower() == wanted:
            return value
    return None


def _earnings_expectation_lines(state: GraphState) -> list[str]:
    lines: list[str] = []
    estimates = _parse_jsonish(_first_matching_output(state, {"get_earnings_estimates"}))
    if isinstance(estimates, dict) and not estimates.get("error"):
        rows = estimates.get("earnings_estimate")
        if isinstance(rows, list) and rows:
            first = rows[0] if isinstance(rows[0], dict) else {}
            avg = first.get("avg") or first.get("current") or first.get("estimate")
            period = str(first.get("period") or "下一季").strip() or "下一季"
            if avg is not None:
                lines.append(f"{period} 共识 EPS 约 {_format_compact_number(avg)}")
        signal = str(estimates.get("revision_signal") or "").strip()
        if signal:
            lines.append(f"盈利预期修正信号：{signal}")

    revisions = _parse_jsonish(_first_matching_output(state, {"get_eps_revisions"}))
    if isinstance(revisions, dict) and not revisions.get("error"):
        rows = revisions.get("eps_revisions")
        if isinstance(rows, list) and rows:
            first = rows[0] if isinstance(rows[0], dict) else {}
            up = _case_insensitive_get(first, "upLast7days")
            down = _case_insensitive_get(first, "downLast7days")
            if up is not None or down is not None:
                lines.append(f"近 7 天 EPS 上修 {up or 0} 次、下修 {down or 0} 次")
        signal = str(revisions.get("revision_signal") or "").strip()
        if signal and all(signal not in line for line in lines):
            lines.append(f"EPS 修正信号：{signal}")

    return lines[:4]


def _company_identity_tokens(state: GraphState) -> set[str]:
    tokens = {ticker.lower() for ticker in _tickers(state) if ticker}
    generic = {"corp", "corporation", "inc", "ltd", "limited", "company", "class", "ordinary", "shares"}

    company_info = _parse_jsonish(_first_matching_output(state, {"get_company_info"}))
    candidates: list[str] = []
    if isinstance(company_info, dict):
        candidates.extend(
            str(company_info.get(key) or "")
            for key in ("name", "company_name", "longName", "shortName")
        )
    elif isinstance(company_info, str):
        match = re.search(r"(?:^|\n)\s*-\s*Name:\s*([^\n]+)", company_info, re.IGNORECASE)
        if match:
            candidates.append(match.group(1))

    for candidate in candidates:
        for word in re.findall(r"[A-Za-z][A-Za-z0-9&.-]{2,}", candidate):
            normalized = word.strip(" .,-").lower()
            if len(normalized) >= 3 and normalized not in generic:
                tokens.add(normalized)
    return tokens


def _filter_news_by_company_identity(state: GraphState, items: list[dict[str, str]]) -> list[dict[str, str]]:
    tokens = _company_identity_tokens(state)
    if not tokens:
        return items
    filtered: list[dict[str, str]] = []
    for item in items:
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("title", "url", "source", "published", "snippet")
        ).lower()
        if any(token and token in haystack for token in tokens):
            filtered.append(item)
    return filtered


def _render_earnings_performance_markdown(
    state: GraphState,
    *,
    news_map: dict[str, list[dict[str, str]]],
    evidence_items: list[dict[str, str]],
) -> str:
    tickers = _tickers(state)
    ticker_label = ", ".join(tickers) or "这个标的"
    financial_lines = _latest_quarter_facts(state)
    expectation_lines = _earnings_expectation_lines(state)
    fundamental = _agent_summary(state, {"fundamental_agent"})
    news = _filter_news_by_company_identity(state, [item for items in news_map.values() for item in items])
    synthesis_points = _synthesis_points(state, ("conclusion", "impact_analysis"), limit=3)

    if synthesis_points:
        lines: list[str] = ["**结论**"]
        lines.extend(f"- {item}" for item in synthesis_points)
        lines.extend(["", "**最新季度/财务表现**"])
    else:
        lines = [
            f"**结论**：{ticker_label} 的财报表现需要同时看财务事实、盈利预期/EPS 修正和管理层指引。",
            "",
            "**最新季度/财务表现**",
        ]
    if financial_lines:
        for item in financial_lines:
            lines.append(f"- {item}")
    elif fundamental:
        lines.append(f"- {fundamental}")
    else:
        lines.append("- [数据缺失] 本轮没有拿到季度财务事实表，不能硬编营收、利润或 EPS。")

    if fundamental and financial_lines:
        lines.append(f"- {fundamental}")

    lines.extend(["", "**盈利预期/EPS 修正**"])
    if expectation_lines:
        for item in expectation_lines:
            lines.append(f"- {item}")
    else:
        lines.append("- [数据缺失] 本轮没有拿到盈利预期或 EPS 修正数据，无法判断市场预期是否继续上修。")

    lines.extend(["", "**消息/指引**"])
    if news:
        for item in news[:3]:
            lines.append(f"- {_format_news_item(item)}")
    else:
        lines.append("- [数据缺失] 本轮没有可引用的财报新闻、电话会或指引来源，事件解释需要保守。")

    lines.extend(["", "**风险/待验证**"])
    risk_lines = _agent_risks(state, {"fundamental_agent", "news_agent"})
    if risk_lines:
        for item in risk_lines[:4]:
            lines.append(f"- {item}")
    else:
        lines.append("- 重点验证下一季指引、毛利率/净利率变化和 EPS 修正方向；如果预期上修停止，财报利好可能被估值压力抵消。")

    _append_sources(lines, news or evidence_items)
    return _finalize_chat_markdown(lines, state)


def _render_earnings_impact_markdown(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
    news_map: dict[str, list[dict[str, str]]],
    evidence_items: list[dict[str, str]],
) -> str:
    tickers = _tickers(state)
    ticker_label = ", ".join(tickers) or "这个标的"
    primary_ticker = tickers[0] if tickers else ticker_label
    price = prices.get(primary_ticker) or next(iter(prices.values()), {})
    financial_lines = _latest_quarter_facts(state)
    expectation_lines = _earnings_expectation_lines(state)
    fundamental = _agent_summary(state, {"fundamental_agent"})
    risk_lines = _agent_risks(state, {"risk_agent", "fundamental_agent", "news_agent"})
    news = _filter_news_by_company_identity(state, [item for items in news_map.values() for item in items])
    synthesis_points = _synthesis_points(state, ("conclusion", "impact_analysis"), limit=3)

    if synthesis_points:
        lines: list[str] = ["**结论**"]
        lines.extend(f"- {item}" for item in synthesis_points)
        lines.extend(["", "**股价反应**"])
    else:
        lines = [
            f"**结论**：{ticker_label} 的财报对股价影响，要同时看“财报/指引是否超预期”和“股价是否已经反映”。本轮按财报事实、EPS 修正、股价反应和风险触发来判断。",
            "",
            "**股价反应**",
        ]
    if price.get("price"):
        lines.append(f"- {_format_price_line(primary_ticker, price)}")
    else:
        lines.append("- [数据缺失] 本轮没有拿到可用当前报价，无法量化市场即时反应。")

    lines.extend(["", "**财报/预期差**"])
    if financial_lines:
        for item in financial_lines:
            lines.append(f"- {item}")
    elif fundamental:
        lines.append("- 本轮 SEC 季度事实表不可用，先用基本面 Agent 的财务摘要作为替代证据。")
    else:
        lines.append("- [数据缺失] 本轮没有拿到季度财务事实表，不能硬判断财报本身是利好还是利空。")
    if fundamental:
        lines.append(f"- {fundamental}")

    lines.extend(["", "**盈利预期/EPS 修正**"])
    if expectation_lines:
        for item in expectation_lines:
            lines.append(f"- {item}")
    else:
        lines.append("- [数据缺失] 本轮没有拿到盈利预期或 EPS 修正，无法确认市场预期是否上修。")

    lines.extend(["", "**消息/指引**"])
    if news:
        for item in news[:3]:
            lines.append(f"- {_format_news_item(item)}")
    else:
        lines.append("- [数据缺失] 本轮没有可引用的财报新闻、电话会或指引来源，事件解释需要保守。")

    lines.extend(["", "**风险/后续观察**"])
    if risk_lines:
        for item in risk_lines[:4]:
            lines.append(f"- {item}")
    else:
        lines.append("- 重点看下一季指引、毛利率、EPS 修正和股价是否放量确认；若预期上修停滞，短线利好可能被估值压力抵消。")

    _append_sources(lines, news or evidence_items)
    return _finalize_chat_markdown(lines, state)


def _investment_opinion_bias(price: dict[str, Any], technical: str, risk_lines: list[str]) -> str:
    score = 0
    change_pct = _price_change_pct(price)
    if change_pct is not None:
        if change_pct >= 1.0:
            score += 1
        elif change_pct <= -1.0:
            score -= 1
    tech_text = str(technical or "")
    if any(token in tech_text for token in ("偏强", "上升趋势", "多头排列", "多头")):
        score += 1
    if any(token in tech_text for token in ("偏弱", "下降趋势", "空头排列", "空头")):
        score -= 1
    risk_text = " ".join(str(item or "") for item in risk_lines).lower()
    controlled_risk = any(
        token in risk_text
        for token in ("可控", "中等", "未触发", "没有触及", "尚未", "moderate", "controlled", "contained")
    )
    elevated_risk = any(
        token in risk_text
        for token in (
            "高风险",
            "风险较高",
            "显著",
            "急剧",
            "已跌破",
            "跌破支撑",
            "破位",
            "趋势转弱",
            "下修",
            "监管",
            "elevated",
            "high risk",
            "bearish",
        )
    )
    if elevated_risk and not controlled_risk:
        score -= 1
    if score >= 2:
        return "中性偏多"
    if score <= -2:
        return "偏谨慎"
    return "中性观察"


def _render_investment_opinion_markdown(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
    news_map: dict[str, list[dict[str, str]]],
    technical_map: dict[str, str],
    evidence_items: list[dict[str, str]],
) -> str:
    tickers = _tickers(state)
    ticker_label = ", ".join(tickers) or "这个标的"
    primary_ticker = tickers[0] if tickers else ticker_label
    price = prices.get(primary_ticker) or next(iter(prices.values()), {})
    technical = technical_map.get(primary_ticker) or next(iter(technical_map.values()), "")
    news = [item for items in news_map.values() for item in items]
    fundamental = _agent_summary(state, {"fundamental_agent"})
    risk_summary = _agent_summary(state, {"risk_agent"})
    risk_lines = _agent_risks(state, {"risk_agent", "fundamental_agent", "technical_agent"})
    bias = _investment_opinion_bias(price, technical, risk_lines)

    lines: list[str] = [
        f"**结论**：{ticker_label} 这轮先按「{bias}」处理；这不是买卖指令，核心取决于技术位、盈利验证和风险触发是否同时改善。",
        "",
        "**价格/趋势**",
    ]
    if price.get("price"):
        lines.append(f"- {_format_price_line(primary_ticker, price)}")
    else:
        lines.append("- [数据缺失] 本轮未取得可用当前报价，方向判断缺少价格锚点。")

    lines.extend(["", "**技术面**"])
    if technical:
        lines.append(f"- {technical}")
        action_line = _technical_action_line(primary_ticker, technical)
        if action_line:
            lines.append(f"- {action_line}")
    else:
        lines.append("- [数据缺失] 本轮未取得趋势、动量、支撑阻力等技术证据，不能只凭新闻判断走势。")

    lines.extend(["", "**消息/催化**"])
    if news:
        for item in news[:3]:
            lines.append(f"- {_format_news_item(item)}")
    else:
        lines.append("- [数据缺失] 本轮未取得可引用的近期新闻或事件日历，催化判断需要保守。")

    lines.extend(["", "**基本面/估值**"])
    if fundamental:
        lines.append(f"- {fundamental}")
    else:
        lines.append("- [数据缺失] 本轮未取得基本面、盈利预期或估值证据，不能支持强买入/强卖出结论。")

    lines.extend(["", "**风险**"])
    if risk_lines:
        for item in risk_lines:
            lines.append(f"- {item}")
    elif risk_summary:
        lines.append(f"- {risk_summary}")
    else:
        lines.append("- [数据缺失] 本轮未取得回撤、波动或因子风险证据；仓位建议需要等待风险模块补齐。")

    _append_sources(lines, news or evidence_items)
    return _finalize_chat_markdown(lines, state)


def _append_render_var_block(lines: list[str], text: str) -> None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(cleaned)


def _sanitize_chat_markdown(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"\s*\|\s*Suggested ladder\s*:\s*[^\n]+", "", cleaned, flags=re.IGNORECASE)
    for marker in FORBIDDEN_CHAT_MARKERS:
        cleaned = cleaned.replace(marker, "")
    cleaned = re.sub(r"(?m)^\s*\*{2,}\s*$\n?", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"


def _finalize_chat_markdown(lines: list[str], state: GraphState) -> str:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    alert_markdown = str(artifacts.get("alert_markdown") or "").strip()
    if alert_markdown and alert_markdown not in "\n".join(lines):
        lines[:0] = [alert_markdown, ""]
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


def _understanding_v2(state: GraphState) -> dict[str, Any]:
    payload = state.get("understanding_v2")
    if isinstance(payload, dict):
        return payload
    understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    payload = understanding.get("v2") if isinstance(understanding, dict) else {}
    return payload if isinstance(payload, dict) else {}


def _v2_profiles(state: GraphState) -> set[str]:
    profiles: set[str] = set()
    for requirement in (_understanding_v2(state).get("evidence_requirements") or []):
        if not isinstance(requirement, dict):
            continue
        profile = str(requirement.get("profile") or "").strip()
        if profile:
            profiles.add(profile)
    for task in _tasks(state):
        operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        params = operation.get("params") if isinstance(operation.get("params"), dict) else {}
        for key in ("evidence_profile", "comparison_data_profile", "budget_profile"):
            profile = str(params.get(key) or "").strip()
            if profile:
                profiles.add(profile)
        if str(params.get("evidence_focus") or "").strip().lower() == "valuation":
            profiles.add(VALUATION_COMPARE_LIGHT_PROFILE)
    return profiles


def _v2_requires_research_compare(state: GraphState) -> bool:
    v2 = _understanding_v2(state)
    if not v2.get("relations"):
        return False
    return VALUATION_COMPARE_LIGHT_PROFILE in _v2_profiles(state)


def _render_v2_research_compare_markdown(
    state: GraphState,
    *,
    prices: dict[str, dict[str, Any]],
    news_map: dict[str, list[dict[str, str]]],
    evidence_items: list[dict[str, str]],
) -> str:
    v2 = _understanding_v2(state)
    scope = v2.get("scope") if isinstance(v2.get("scope"), dict) else {}
    tickers = [
        str(ticker).strip().upper()
        for ticker in (scope.get("primary_tickers") if isinstance(scope.get("primary_tickers"), list) else _tickers(state))
        if str(ticker).strip()
    ]
    facets = {
        str(facet.get("name") or "").strip()
        for facet in (v2.get("facets") or [])
        if isinstance(facet, dict) and str(facet.get("name") or "").strip()
    }
    label = ", ".join(tickers) or "these tickers"
    lines: list[str] = [
        f"Research comparison for {label}.",
        "",
        "Per-ticker evidence",
    ]
    for ticker in tickers[:6]:
        lines.append(f"- {ticker}:")
        price = prices.get(ticker)
        if price and price.get("price"):
            lines.append(f"  - {_format_price_line(ticker, price)}")
        else:
            lines.append("  - [data missing] current price evidence was not available.")
        if "valuation" in facets:
            lines.append("  - Valuation evidence uses company context, earnings expectations, and fundamental review.")

    fundamental = _agent_summary(state, {"fundamental_agent"})
    if fundamental:
        lines.extend(["", "Fundamental / valuation read", f"- {fundamental}"])
    elif "valuation" in facets:
        lines.extend(["", "Fundamental / valuation read", "- [data missing] fundamental_agent output was not available."])

    omitted = scope.get("omitted_tickers") if isinstance(scope.get("omitted_tickers"), list) else []
    omitted = [str(ticker).strip().upper() for ticker in omitted if str(ticker).strip()]
    if omitted:
        lines.extend(["", f"Not covered in this lightweight chat pass: {', '.join(omitted)}."])

    sources = [item for items in news_map.values() for item in items] or evidence_items
    _append_sources(lines, sources)
    return _finalize_chat_markdown(lines, state)


def render_chat_markdown(state: GraphState) -> str:
    query = str(state.get("query") or "").strip()
    ticker_label = ", ".join(_tickers(state)) or "这个标的"
    operations = _operation_names(state)
    memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    last_report = current_report_context(memory_context)
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
    requested_link_count = _requested_news_link_count(state)
    if _reply_contract_requires_links(state):
        requested_link_count = max(requested_link_count, 3)
    if (
        _reply_contract_requires_links(state)
        and requested_link_count
        and _news_article_fallback_allowed(state)
        and not _news_map_has_citable_url(news_map)
    ):
        for ticker, items in _direct_news_article_fallback_map(state, count=requested_link_count).items():
            news_map[ticker] = _dedupe_news_items(items + news_map.get(ticker, []), limit=5)
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
        analysis_block = (
            _useful_render_var(render_vars, "impact_analysis")
            or _useful_render_var(render_vars, "conclusion")
            or _useful_render_var(render_vars, "investment_summary")
        )
        has_other_answerable_tasks = bool(
            prices
            or analysis_block
            or next_watch
            or _has_macro_context(state)
            or _focus_task_present(state)
        )
        if _url_fetch_all_failed(state) and not has_other_answerable_tasks:
            if not lines:
                lines.append("URL fetch failed; no readable content was available, so I will not infer from the URL text alone.")
            return _finalize_chat_markdown(lines, state)
        if analysis_block:
            if lines and lines[-1] != "":
                lines.append("")
            _append_render_var_block(lines, analysis_block)
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

    if "earnings_impact" in operations:
        return _render_earnings_impact_markdown(
            state,
            prices=prices,
            news_map=news_map,
            evidence_items=evidence_items,
        )

    if "earnings_performance" in operations:
        return _render_earnings_performance_markdown(
            state,
            news_map=news_map,
            evidence_items=evidence_items,
        )

    if "price" in operations and "fetch" not in operations and "technical" not in operations and "analyze_impact" not in operations:
        target_tickers = _tickers(state) or list(prices.keys()) or [ticker_label]
        for ticker in target_tickers[:5]:
            ticker_price = prices.get(ticker, price if len(target_tickers) == 1 else {})
            lines.append(_format_price_line(ticker, ticker_price))
        return _finalize_chat_markdown(lines, state)

    if _v2_requires_research_compare(state):
        return _render_v2_research_compare_markdown(
            state,
            prices=prices,
            news_map=news_map,
            evidence_items=evidence_items,
        )

    if "compare" in operations:
        return _render_compare_or_basket_markdown(
            state,
            prices=prices,
            news_map=news_map,
            comparison_conclusion=comparison_conclusion,
            comparison_metrics=comparison_metrics,
        )

    if "investment_opinion" in operations:
        return _render_investment_opinion_markdown(
            state,
            prices=prices,
            news_map=news_map,
            technical_map=technical_map,
            evidence_items=evidence_items,
        )

    if "fetch" in operations or "analyze_impact" in operations or news:
        analysis_block = (
            _useful_render_var(render_vars, "impact_analysis")
            or _useful_render_var(render_vars, "conclusion")
            or _useful_render_var(render_vars, "investment_summary")
        )
        if news_map:
            listed_news_items: list[dict[str, str]] = []
            for ticker, items in list(news_map.items())[:4]:
                lines.append(f"{ticker} 我找到几条比较相关的消息（最近新闻）：")
                for item in items[:3]:
                    lines.append(f"- {_format_news_item(item)}")
                    listed_news_items.append(item)
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
            _append_missing_article_url_note(lines, listed_news_items)
            if requested_link_count and not any(_is_citable_url(str(item.get("url") or "")) for item in listed_news_items):
                _append_news_source_page_links(lines, state, count=requested_link_count)
        else:
            fallback_items = evidence_items
            if fallback_items:
                lines.append(f"{ticker_label} 这次先看这些来源：")
                for item in fallback_items[:4]:
                    lines.append(f"- {_format_news_item(item)}")
                _append_missing_article_url_note(lines, fallback_items[:4])
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
                if requested_link_count:
                    lines.append(f"Live news sources did not return usable article URLs for {ticker_label}; I will not invent citation links.")
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
                lines.append(f"{ticker} 技术面结论：{text}")
                action_line = _technical_action_line(ticker, text)
                if action_line:
                    lines.append(action_line)
            if conclusion:
                _append_render_var_block(lines, conclusion)
        elif technical:
            lines.append(f"{ticker_label} 技术面结论：{technical}")
            action_line = _technical_action_line(ticker_label, technical)
            if action_line:
                lines.append(action_line)
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
