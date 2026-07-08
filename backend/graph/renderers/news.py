# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/chat_renderer.py（WP3 Task1，零行为变更）。
from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import quote_plus

from backend.graph.state import GraphState
from backend.graph.renderers.macro import (
    _external_entity_impact_fallback_lines,
    _focus_line,
    _focus_task_present,
    _has_macro_context,
    _macro_mechanism_lines,
)
from backend.graph.renderers.news_fallback import _append_news_source_page_links
from backend.graph.renderers.news_items import _is_low_value_evidence_item, _news_items
from backend.graph.renderers.news_snapshot import _is_snapshot_news_item, _render_news_brief_block
from backend.graph.renderers.price import _format_price_line
from backend.graph.renderers.shared import (
    _append_render_var_block,
    _append_sources,
    _company_identity_tokens,
    _finalize_chat_markdown,
    _has_contract_facet,
    _is_citable_url,
    _parse_jsonish,
    _risk_or_qa_fallback_lines,
    _step_outputs,
    _tasks,
    _ticker_for_step,
)
from backend.graph.renderers.synthesis_vars import _useful_render_var
from backend.graph.renderers.url_fetch import _append_url_fetch_notes



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

def _news_map_has_citable_url(news_map: dict[str, list[dict[str, str]]]) -> bool:
    return any(
        _is_citable_url(str(item.get("url") or ""))
        for items in news_map.values()
        for item in items
    )

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
        # P0-9-2: NewsAgent 完整快照条目不是新闻，绝不能参与 company-identity
        # 相关性过滤——否则快照标题含 ticker 会"存活"、真实新闻反被滤掉，
        # 下游只剩快照可渲染。快照单独拎出，过滤只作用于真实新闻，最后放回。
        snapshot_items = [item for item in deduped if _is_snapshot_news_item(item)]
        news_candidates = [item for item in deduped if not _is_snapshot_news_item(item)]
        relevant = _filter_news_by_company_identity(state, news_candidates)
        if relevant:
            news_candidates = relevant
        merged = news_candidates + snapshot_items
        merged.sort(
            key=lambda item: 0
            if str(item.get("type") or "").strip().lower() == "transcript"
            or "transcript" in str(item.get("title") or "").strip().lower()
            else 1
        )
        news_by_ticker[ticker] = merged[:8]
    return news_by_ticker

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


def render_news_impact(state: GraphState, ctx: dict[str, Any]) -> str | None:
    """原分支#12：fetch / analyze_impact / 有新闻。"""
    operations = ctx["operations"]
    news = ctx["news"]
    if not ("fetch" in operations or "analyze_impact" in operations or news):
        return None
    ticker_label = ctx["ticker_label"]
    render_vars = ctx["render_vars"]
    prices = ctx["prices"]
    news_map = ctx["news_map"]
    price = ctx["price"]
    evidence_items = ctx["evidence_items"]
    requested_link_count = ctx["requested_link_count"]
    news_summary = ctx["news_summary"]
    next_watch = ctx["next_watch"]
    risks = ctx["risks"]
    lines: list[str] = []
    analysis_block = (
        _useful_render_var(render_vars, "impact_analysis")
        or _useful_render_var(render_vars, "conclusion")
        or _useful_render_var(render_vars, "investment_summary")
    )
    if news_map:
        listed_news_items: list[dict[str, str]] = []
        # P0-9: 用确定性舆情简报替换"我找到几条比较相关的消息"自由发挥格式。
        # opinion 复用 synthesize 已生成的 analysis_block（不额外调 LLM）；
        # 简报消费后不再单独 append analysis_block，避免重复。
        opinion_consumed_by_brief = False
        for ticker, items in list(news_map.items())[:4]:
            brief_items = items[:8]
            # P0-9-2: 快照条目（news_sentiment_snapshot）不计入"已列新闻"，
            # 否则其空 URL 会误触发"部分标题缺可用链接"提示噪音。
            listed_news_items.extend(
                item for item in brief_items if not _is_snapshot_news_item(item)
            )
            brief_md = _render_news_brief_block(
                ticker, brief_items, opinion=analysis_block
            )
            if brief_md.strip():
                lines.append(brief_md)
                if analysis_block:
                    opinion_consumed_by_brief = True
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
        if analysis_block and not opinion_consumed_by_brief:
            lines.append(analysis_block)
        elif _has_contract_facet(state, "external_entity_impact"):
            lines.extend(
                _external_entity_impact_fallback_lines(
                    state,
                    prices=prices,
                    news_map=news_map,
                )
            )
        elif _has_macro_context(state):
            lines.extend(_macro_mechanism_lines(state))
        elif not opinion_consumed_by_brief:
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
            elif _has_contract_facet(state, "external_entity_impact"):
                lines.extend(
                    _external_entity_impact_fallback_lines(
                        state,
                        prices=prices,
                        news_map=news_map,
                    )
                )
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
