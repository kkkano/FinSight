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
from backend.graph.renderers.shared import _is_citable_url, _parse_jsonish, _tickers

try:  # Optional live-news fallback for link-required chat answers.
    from backend.config.ticker_mapping import COMPANY_MAP
except Exception:  # pragma: no cover - renderer must still work without live tool imports.
    COMPANY_MAP = {}


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
        evidence = parsed.get("evidence")
        if isinstance(nested, list) and nested:
            rows = nested
        elif isinstance(evidence, list):
            rows = evidence
        else:
            rows = [parsed]
    else:
        rows = []

    items: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("headline") or row.get("text") or row.get("summary") or "").strip()
        if not title:
            continue
        url = str(row.get("url") or row.get("link") or row.get("article_url") or "").strip()
        if not _is_citable_url(url):
            url = ""
        source = str(row.get("source") or row.get("publisher") or "").strip()
        published = str(row.get("published_at") or row.get("published_date") or row.get("date") or row.get("timestamp") or "").strip()
        snippet = str(
            row.get("snippet")
            or row.get("description")
            or row.get("content")
            or row.get("text")
            or row.get("summary")
            or ""
        ).strip()
        new_item: dict[str, Any] = {
            "title": title,
            "url": url,
            "source": source,
            "published": published[:10],
            "snippet": snippet[:500],
            "type": str(row.get("type") or "").strip(),
        }
        # P0-9-2: 保留 NewsAgent 完整快照（meta.snapshot）。EvidenceItem 经
        # collector_adapter 的 asdict 序列化后 meta 仍在；下游 _render_news_brief_block
        # 据此把快照从新闻列表剥离，并优先于轻量快照渲染标题/催化。
        meta = row.get("meta")
        if isinstance(meta, dict):
            snapshot = meta.get("snapshot")
            if isinstance(snapshot, dict) and snapshot:
                new_item["_snapshot"] = snapshot
        items.append(new_item)
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


_TICKER_CODE_RE = re.compile(r"^[A-Z0-9]{1,6}([.\-][A-Z0-9]{1,4})?$")


def _is_real_ticker(key: str) -> bool:
    """判断 news_map 的 key 是真实股票代码（个股简报）还是泛市场兜底标签。

    真实 ticker：AAPL / MSFT / 600519.SS / 0700.HK 等 ASCII 代码。
    泛市场兜底：``_news_by_ticker`` 在无法判定标的时写入的 "相关信息" 等中文标签。
    """
    candidate = str(key or "").strip().upper()
    return bool(_TICKER_CODE_RE.match(candidate))
