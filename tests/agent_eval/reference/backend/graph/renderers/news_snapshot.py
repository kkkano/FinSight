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
from backend.graph.renderers.news_items import _is_real_ticker
from backend.graph.renderers.shared import _is_citable_url
from backend.agents.sentiment_brief import (
    build_light_snapshot,
    render_market_brief,
    render_stock_brief,
)



_SNAPSHOT_TEXT_MARKER = "整体舆情:"


_SNAPSHOT_AVG_RE = re.compile(r"平均分\s*([+-]?\d+(?:\.\d+)?|N/A)")


_SNAPSHOT_RATIO_RE = re.compile(r"正/负/中占比\s*(\d+)%/(\d+)%/(\d+)%")


_SNAPSHOT_TREND_RE = re.compile(r"趋势:\s*([A-Za-z_]+)")


_SNAPSHOT_NEWS_COUNT_RE = re.compile(r"新闻\s*(\d+)\s*条")


_SNAPSHOT_EVENT_COUNT_RE = re.compile(r"事件\s*(\d+)\s*个")


_SNAPSHOT_CATALYST_RE = re.compile(r"催化事件:\s*(\d+)\s*个")


_SNAPSHOT_LABEL_RE = re.compile(r"整体舆情:\s*([A-Za-z_]+)")


_SNAPSHOT_HEAT_RE = re.compile(r"热度:\s*([A-Za-z_]+)")


_SNAPSHOT_PRICE_RE = re.compile(r"价格传导:\s*([A-Za-z_]+)")


def _is_snapshot_news_item(item: dict[str, Any]) -> bool:
    """判断一个新闻条目实为 NewsAgent 完整快照（不能当新闻渲染）。

    判据：source == "news_sentiment_snapshot"，或标题/正文以"整体舆情:"模式出现。
    """
    if not isinstance(item, dict):
        return False
    if str(item.get("source") or "").strip() == "news_sentiment_snapshot":
        return True
    text = f"{item.get('title') or ''} {item.get('snippet') or ''}"
    return _SNAPSHOT_TEXT_MARKER in text


def _parse_snapshot_text(text: str) -> dict[str, Any] | None:
    """从 NewsAgent 快照文本提取结构化 snapshot dict（meta 丢失时的兜底）。

    返回与 build_light_snapshot/render_stock_brief 兼容的 dict：
    sentiment_bias / sentiment_trend / heat / catalyst_events / price_transmission。
    无法识别"整体舆情:"特征时返回 None。
    """
    raw = str(text or "").strip()
    if _SNAPSHOT_TEXT_MARKER not in raw:
        return None

    bias: dict[str, Any] = {}
    label_match = _SNAPSHOT_LABEL_RE.search(raw)
    if label_match:
        bias["label"] = label_match.group(1)

    avg_match = _SNAPSHOT_AVG_RE.search(raw)
    if avg_match and avg_match.group(1) != "N/A":
        try:
            bias["average_score"] = float(avg_match.group(1))
        except ValueError:
            bias["average_score"] = None

    ratio_match = _SNAPSHOT_RATIO_RE.search(raw)
    if ratio_match:
        pos, neg, neu = (int(ratio_match.group(i)) / 100.0 for i in (1, 2, 3))
        bias["positive_ratio"] = pos
        bias["negative_ratio"] = neg
        bias["neutral_ratio"] = neu

    news_count_match = _SNAPSHOT_NEWS_COUNT_RE.search(raw)
    event_count_match = _SNAPSHOT_EVENT_COUNT_RE.search(raw)
    news_count = int(news_count_match.group(1)) if news_count_match else 0
    event_count = int(event_count_match.group(1)) if event_count_match else 0
    # sample_size 没有显式数字，用新闻条数兜底（让标题行脱离"样本不足"分支，
    # 同时保守地反映"有聚合信号"这一事实）。
    bias["sample_size"] = news_count

    trend: dict[str, Any] = {}
    trend_match = _SNAPSHOT_TREND_RE.search(raw)
    if trend_match:
        trend["direction"] = trend_match.group(1)

    heat: dict[str, Any] = {"news_count": news_count, "event_count": event_count}
    heat_match = _SNAPSHOT_HEAT_RE.search(raw)
    if heat_match:
        heat["level"] = heat_match.group(1)

    catalyst_count_match = _SNAPSHOT_CATALYST_RE.search(raw)
    catalyst_count = int(catalyst_count_match.group(1)) if catalyst_count_match else 0

    price: dict[str, Any] = {"status": "todo"}
    price_match = _SNAPSHOT_PRICE_RE.search(raw)
    if price_match:
        price["status"] = price_match.group(1)

    return {
        "sentiment_bias": bias,
        "sentiment_trend": trend,
        "heat": heat,
        # 文本形式无逐条催化标题，只有总数；events 留空但保留 count，
        # 标题行显示"K 条催化"，催化区块退回"已识别 K 个催化"占位说明。
        "catalyst_events": {"count": catalyst_count, "events": []},
        "price_transmission": price,
    }


def _extract_full_snapshot(
    ticker: str, items: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """从新闻条目里提取 NewsAgent 完整快照，并返回剥离快照后的新闻列表。

    优先用 meta 里的结构化 snapshot dict；若只有文本则正则解析。
    返回 (snapshot_or_None, news_without_snapshot)。
    """
    snapshot: dict[str, Any] | None = None
    remaining: list[dict[str, Any]] = []
    for item in items:
        if not _is_snapshot_news_item(item):
            remaining.append(item)
            continue
        # 命中快照条目：优先结构化 dict，否则正则解析文本；无论如何都从新闻列表剔除。
        if snapshot is None:
            structured = item.get("_snapshot")
            if isinstance(structured, dict) and structured:
                snapshot = dict(structured)
            else:
                parsed = _parse_snapshot_text(
                    str(item.get("title") or item.get("snippet") or "")
                )
                if parsed is not None:
                    snapshot = parsed
        # 快照条目不进 remaining（绝不当新闻渲染）。
    if snapshot is not None:
        snapshot.setdefault("ticker", str(ticker or "").strip().upper())
    return snapshot, remaining


def _render_news_brief_block(
    ticker: str,
    items: list[dict[str, str]],
    *,
    opinion: str | None,
) -> str:
    """把一组新闻渲染成确定性舆情简报（P0-9 接入真实 Chat 路径）。

    - 真实 ticker -> render_stock_brief(build_light_snapshot(...))（个股简报）
    - 泛市场兜底标签 -> render_market_brief(themes=[], ...)（市场简报）

    opinion 复用 synthesize 已生成的 render_var（impact_analysis/conclusion），
    不额外触发 LLM 调用；缺失时简报骨架照常输出（降级阶梯）。
    """
    clean_opinion = str(opinion or "").strip() or None
    # P0-9-2: 先剥离 NewsAgent 完整快照条目（绝不能当新闻渲染），
    # 并把它作为优先快照（情绪/催化的真实聚合数据）供下游渲染。
    full_snapshot, news_only_items = _extract_full_snapshot(ticker, items)
    # 净化 URL：剥离不可引用链接（如 google search 页），与 chat_renderer 防线对齐，
    # 避免简报 news_list 把搜索页当成引用外泄。
    safe_items: list[dict[str, str]] = []
    for item in news_only_items:
        if not isinstance(item, dict):
            continue
        new_item = dict(item)
        if not _is_citable_url(str(new_item.get("url") or "").strip()):
            new_item["url"] = ""
        # 内部字段不外泄到渲染层。
        new_item.pop("_snapshot", None)
        safe_items.append(new_item)
    if _is_real_ticker(ticker):
        # 快照优先级：NewsAgent 完整快照 > 轻量快照（build_light_snapshot 兜底）。
        if full_snapshot is not None:
            snapshot = dict(full_snapshot)
            snapshot.setdefault("ticker", str(ticker or "").strip().upper())
        else:
            snapshot = build_light_snapshot(ticker, safe_items)
        return render_stock_brief(snapshot, safe_items, opinion=clean_opinion)
    return render_market_brief(themes=[], news_items=safe_items, opinion=clean_opinion)
