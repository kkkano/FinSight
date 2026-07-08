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
from backend.graph.renderers.news_items import (
    _company_name_for_ticker,
    _dedupe_news_items,
    _is_low_value_evidence_item,
    _news_item_matches_subject,
    _news_items,
)
from backend.graph.renderers.shared import _tasks, _tickers
try:  # Optional live-news fallback for link-required chat answers.
    from backend.tools.authoritative_feeds import get_authoritative_media_news
    from backend.tools.news import get_company_news
except Exception:  # pragma: no cover - renderer must still work without live tool imports.
    get_authoritative_media_news = None
    get_company_news = None


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
