"""Dashboard 新闻舆情快照（确定性聚合，零额外 API 调用）。

与 NewsAgent 的完整 NewsSentimentSnapshot 对齐，但只使用 Dashboard 新闻列表
本身可得的字段，避免为看板首屏引入额外外部调用：

- sentiment_bias / sentiment_trend: 标题+摘要关键词的确定性估计，basis 显式标注
- catalyst_events: 标题催化关键词扫描
- heat: 新闻数量分级
- price_transmission: 恒为 status="todo"（Dashboard 尚无价格校准证据，不推断）
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_POSITIVE_KEYWORDS = (
    "surge", "jump", "rise", "gain", "bull", "rally", "upgrade", "beat",
    "profit", "growth", "record", "high", "strong", "positive", "optimis",
    "outperform", "buy", "upside",
    "超预期", "增持", "上涨", "新高", "盈利", "回购", "中标", "获批", "利好", "上调",
)

_NEGATIVE_KEYWORDS = (
    "drop", "fall", "decline", "loss", "bear", "crash", "downgrade", "miss",
    "debt", "risk", "weak", "negative", "pessimis", "sell", "cut", "low",
    "slump", "warning", "fear",
    "下跌", "减持", "亏损", "下调", "不及预期", "立案", "调查", "停牌", "利空", "违约", "裁员",
)

_CATALYST_KEYWORDS = (
    "beat", "beats", "miss", "earnings", "revenue", "guidance", "approval",
    "launch", "upgrade", "downgrade", "lawsuit", "investigation", "merger",
    "acquisition", "dividend", "catalyst",
    "财报", "业绩", "超预期", "不及预期", "净利润", "营收", "减持", "增持", "立案",
    "重组", "并购", "中标", "回购", "停牌", "分红", "解禁",
)


def _item_text(item: Dict[str, Any]) -> str:
    return f"{item.get('title') or ''} {item.get('summary') or ''}".lower()


def _keyword_sentiment(item: Dict[str, Any]) -> str:
    text = _item_text(item)
    positive_hits = sum(1 for kw in _POSITIVE_KEYWORDS if kw in text)
    negative_hits = sum(1 for kw in _NEGATIVE_KEYWORDS if kw in text)
    if positive_hits > negative_hits:
        return "bullish"
    if negative_hits > positive_hits:
        return "bearish"
    return "neutral"


def _sentiment_score(bucket: str) -> int:
    if bucket == "bullish":
        return 1
    if bucket == "bearish":
        return -1
    return 0


def _timestamp_seconds(item: Dict[str, Any]) -> Optional[float]:
    raw = item.get("ts") or item.get("published_at") or item.get("datetime")
    if raw is None or raw == "":
        return None
    try:
        if isinstance(raw, (int, float)):
            return float(raw)
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return None


def _merge_items(market_items: List[Dict[str, Any]], impact_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in list(market_items or []) + list(impact_items or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        key = (title, str(item.get("source") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged[:40]


def _build_sentiment_bias(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    for item in items:
        counts[_keyword_sentiment(item)] += 1
    total = len(items)
    if counts["bullish"] > counts["bearish"]:
        label = "bullish"
    elif counts["bearish"] > counts["bullish"]:
        label = "bearish"
    else:
        label = "neutral"
    return {
        "label": label,
        "average_score": None,
        "positive_count": counts["bullish"],
        "negative_count": counts["bearish"],
        "neutral_count": counts["neutral"],
        "sample_size": total,
        "basis": "keyword_estimation",
    }


def _build_sentiment_trend(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    observations = []
    for item in items:
        ts = _timestamp_seconds(item)
        if ts is None:
            continue
        observations.append((ts, _sentiment_score(_keyword_sentiment(item))))
    observations.sort(key=lambda pair: pair[0])
    scores = [score for _, score in observations]
    if len(scores) < 2:
        return {
            "direction": "unknown",
            "delta": None,
            "recent_average": None,
            "previous_average": None,
            "sample_size": len(scores),
            "basis": "insufficient_timestamped_sentiment",
        }

    split = max(1, len(scores) // 2)
    previous = scores[:split]
    recent = scores[split:] or previous
    previous_avg = sum(previous) / len(previous)
    recent_avg = sum(recent) / len(recent)
    delta = recent_avg - previous_avg
    if delta >= 0.08:
        direction = "improving"
    elif delta <= -0.08:
        direction = "deteriorating"
    else:
        direction = "stable"
    return {
        "direction": direction,
        "delta": round(delta, 4),
        "recent_average": round(recent_avg, 4),
        "previous_average": round(previous_avg, 4),
        "sample_size": len(scores),
        "basis": "half_window_comparison",
    }


def _build_heat(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    count = len(items)
    if count >= 6:
        level = "elevated"
    elif count >= 3:
        level = "active"
    elif count > 0:
        level = "normal"
    else:
        level = "thin"
    return {"level": level, "news_count": count, "basis": "news_volume"}


def _build_catalyst_events(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []
    for item in items:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        lowered = title.lower()
        if not any(token in lowered for token in _CATALYST_KEYWORDS):
            continue
        events.append(
            {
                "kind": "news",
                "category": "keyword_catalyst",
                "title": title,
                "date": item.get("datetime")
                or item.get("published_at")
                or item.get("ts")
                or item.get("date"),
                "source": item.get("source") or "news",
                "impact_score": item.get("impact_score")
                if isinstance(item.get("impact_score"), (int, float))
                else None,
            }
        )
    return {"count": len(events), "events": events[:8]}


def build_dashboard_sentiment_snapshot(
    ticker: str,
    market_items: List[Dict[str, Any]],
    impact_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """从 Dashboard 新闻列表构建确定性舆情快照（零额外 API 调用）。"""
    items = _merge_items(market_items, impact_items)
    return {
        "ticker": str(ticker or "").strip().upper(),
        "sentiment_bias": _build_sentiment_bias(items),
        "sentiment_trend": _build_sentiment_trend(items),
        "heat": _build_heat(items),
        "catalyst_events": _build_catalyst_events(items),
        # 数据真实性防线：Dashboard 未做价格校准，不推断共振/背离。
        "price_transmission": {
            "status": "todo",
            "reason": "dashboard_has_no_price_alignment_evidence",
            "source": None,
            "price_change_pct": None,
        },
        "source": "dashboard_light_snapshot",
    }


def attach_dashboard_news_sentiment(news: Optional[Dict[str, Any]], ticker: str) -> Dict[str, Any]:
    """把舆情快照挂到新闻 payload 的副本上，不改动缓存对象。"""
    payload = dict(news or {})
    payload["sentiment_snapshot"] = build_dashboard_sentiment_snapshot(
        ticker,
        payload.get("market", []),
        payload.get("impact", []),
    )
    return payload
