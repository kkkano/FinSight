"""舆情简报渲染器（P0-9）。

确定性骨架 + LLM 观点段：
- 骨架（情绪/热度/催化/价格传导/风险/新闻列表）由代码渲染，零 LLM 依赖
- 观点段由调用方传入（LLM 生成），缺失时骨架照常输出

数据真实性防线：
- 价格传导 status=todo -> 区块不渲染
- 情绪样本 < 3 -> 显示"情绪样本不足"
- 有新闻但无催化 -> 显示"未识别到催化事件"
- 未评估可靠度 -> 不显示假分数
"""
from typing import Any, Dict, List, Optional

_BIAS_LABELS = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}
_HEAT_LABELS = {"elevated": "高热", "active": "活跃", "normal": "一般", "thin": "清淡"}
_PRICE_STATUS_LABELS = {"resonance": "共振", "divergence": "背离", "neutral": "不明确"}

_MIN_SENTIMENT_SAMPLE = 3


def _render_title_line(snapshot: Dict[str, Any]) -> str:
    bias = snapshot.get("sentiment_bias") or {}
    heat = snapshot.get("heat") or {}
    catalysts = snapshot.get("catalyst_events") or {}

    sample_size = int(bias.get("sample_size") or 0)
    if sample_size < _MIN_SENTIMENT_SAMPLE:
        sentiment_part = "**整体情绪：情绪样本不足**"
    else:
        label = _BIAS_LABELS.get(str(bias.get("label")), "中性")
        avg = bias.get("average_score")
        avg_text = f" ({avg:+.2f})" if isinstance(avg, (int, float)) else ""
        sentiment_part = f"**整体情绪：{label}{avg_text}**"

    parts = [sentiment_part]
    heat_label = _HEAT_LABELS.get(str(heat.get("level")), "")
    if heat_label:
        parts.append(f"热度：{heat_label}")
    catalyst_count = int(catalysts.get("count") or 0)
    if catalyst_count > 0:
        parts.append(f"{catalyst_count} 条催化")
    return " · ".join(parts)


def _render_catalysts(snapshot: Dict[str, Any], has_news: bool) -> Optional[str]:
    catalysts = snapshot.get("catalyst_events") or {}
    events = catalysts.get("events") or []
    if not events:
        # 有新闻但无催化 = 真实信息；无新闻 = 跳过区块
        return "⚡ **催化事件**\n\n未识别到催化事件" if has_news else None

    lines = ["⚡ **催化事件**", ""]
    for event in events[:5]:
        if not isinstance(event, dict):
            continue
        title = str(event.get("title") or "").strip()
        if not title:
            continue
        date = str(event.get("date") or "").strip()
        impact = event.get("impact_score")
        impact_text = f" (影响:{'高' if impact and impact >= 0.8 else '中'})" if isinstance(impact, (int, float)) else ""
        date_text = f" — {date[:10]}" if date else ""
        lines.append(f"- {title}{impact_text}{date_text}")
    return "\n".join(lines) if len(lines) > 2 else None


def _render_price_transmission(snapshot: Dict[str, Any]) -> Optional[str]:
    price = snapshot.get("price_transmission") or {}
    status = str(price.get("status") or "")
    # 数据真实性防线：todo = 我们没做到，不渲染；绝不输出 TODO 文案
    if status in ("todo", "", "unknown"):
        return None
    status_label = _PRICE_STATUS_LABELS.get(status, status)
    analysis = str(price.get("analysis") or "").strip()
    if "TODO" in analysis:
        return None
    change = price.get("price_change_pct")
    change_text = f"（近期价格 {change:+.1f}%）" if isinstance(change, (int, float)) else ""
    return f"📈 **情绪与价格：{status_label}**{change_text}\n\n{analysis}"


def _render_risks(snapshot: Dict[str, Any], extra_risks: Optional[List[str]] = None) -> Optional[str]:
    risks: List[str] = list(extra_risks or [])
    bias = snapshot.get("sentiment_bias") or {}
    sample_size = int(bias.get("sample_size") or 0)
    if 0 < sample_size < _MIN_SENTIMENT_SAMPLE:
        risks.append("情绪样本量小，整体判断的可靠性有限")
    if not risks:
        return None
    lines = ["⚠️ **风险提示**", ""]
    lines.extend(f"- {risk}" for risk in risks[:4])
    return "\n".join(lines)


_LOW_CONFIDENCE_THRESHOLD = 0.5  # spec 防线5：低于此置信度的新闻标注 ⚠️


def _render_news_list(news_items: List[Dict[str, Any]]) -> Optional[str]:
    if not news_items:
        return None
    lines = [f"📰 **依据新闻** ({len(news_items)} 条)", ""]
    for idx, item in enumerate(news_items[:8], 1):
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or item.get("title") or "").strip()
        if not headline:
            continue
        url = str(item.get("url") or "").strip()
        source = str(item.get("source") or "").strip()
        date = str(item.get("datetime") or item.get("published_at") or "").strip()[:10]
        title_part = f"[{headline}]({url})" if url else headline
        meta_parts = [p for p in (source, date) if p]
        meta_text = f" — {' · '.join(meta_parts)}" if meta_parts else ""
        # spec 防线5：低置信（搜索硬解析等）新闻标注 ⚠️，提醒读者甄别
        confidence = item.get("confidence")
        low_conf_mark = " ⚠️" if isinstance(confidence, (int, float)) and confidence < _LOW_CONFIDENCE_THRESHOLD else ""
        lines.append(f"{idx}. {title_part}{meta_text}{low_conf_mark}")
    return "\n".join(lines) if len(lines) > 2 else None


def render_stock_brief(
    snapshot: Dict[str, Any],
    news_items: List[Dict[str, Any]],
    opinion: Optional[str],
    extra_risks: Optional[List[str]] = None,
) -> str:
    """渲染个股舆情简报（markdown）。

    Args:
        snapshot: NewsSentimentSnapshot 的 dict 形式（dataclasses.asdict）
        news_items: 依据新闻列表
        opinion: LLM 生成的核心观点段；None 时跳过该区块（降级阶梯）
        extra_risks: 额外风险（如来源可靠度警告）
    """
    ticker = str(snapshot.get("ticker") or "").upper()
    has_news = bool(news_items)

    sections: List[Optional[str]] = [
        f"## {ticker} 舆情简报",
        _render_title_line(snapshot),
    ]

    clean_opinion = str(opinion or "").strip()
    if clean_opinion:
        sections.append(f"📍 **核心观点**\n\n{clean_opinion}")

    sections.append(_render_catalysts(snapshot, has_news))
    sections.append(_render_price_transmission(snapshot))
    sections.append(_render_risks(snapshot, extra_risks))

    news_section = _render_news_list(news_items)
    if news_section:
        sections.append("---")
        sections.append(news_section)

    return "\n\n".join(s for s in sections if s)


_THEME_SENTIMENT_LABELS = {"positive": "偏多", "negative": "偏空", "neutral": "中性"}


def render_market_brief(
    themes: List[Dict[str, Any]],
    news_items: List[Dict[str, Any]],
    opinion: Optional[str],
) -> str:
    """渲染泛市场舆情简报（无 ticker）。

    Args:
        themes: LLM 主题聚类结果 [{"name", "sentiment", "news_indices"}]
        news_items: 新闻列表
        opinion: LLM 核心观点；None 时跳过
    """
    sections: List[Optional[str]] = ["## 市场舆情简报"]

    valid_themes = [t for t in (themes or []) if isinstance(t, dict) and t.get("name")]
    title_parts = [f"{len(news_items)} 条新闻"]
    if valid_themes:
        title_parts.append(f"{len(valid_themes)} 个主题")
    sections.append(" · ".join(title_parts))

    clean_opinion = str(opinion or "").strip()
    if clean_opinion:
        sections.append(f"📍 **核心观点**\n\n{clean_opinion}")

    if valid_themes:
        lines = ["🗂 **主题分布**", ""]
        for theme in valid_themes[:4]:
            name = str(theme.get("name") or "").strip()
            sentiment = _THEME_SENTIMENT_LABELS.get(str(theme.get("sentiment")), "中性")
            indices = theme.get("news_indices") or []
            count_text = f"（{len(indices)} 条）" if indices else ""
            lines.append(f"- **{name}**：{sentiment}{count_text}")
        sections.append("\n".join(lines))
    elif news_items:
        sections.append("> ⚠️ 主题聚类暂不可用，以下为原始新闻列表")

    news_section = _render_news_list(news_items)
    if news_section:
        sections.append("---")
        sections.append(news_section)

    return "\n\n".join(s for s in sections if s)


# ──────────────────────────────────────────────────────────────
# 轻量舆情快照（Chat 快速模式用，零额外 API 调用）
#
# 与 NewsAgent 的完整快照（news_agent.py）相比：
# - sentiment_bias: 仅从新闻条目自带 sentiment 字段统计；无则 sample_size=0
# - heat: 新闻数量
# - catalyst_events: 用催化关键词扫描标题（确定性）
# - price_transmission: status="todo"（渲染器自动跳过该区块）
#
# 关键约束：不 import NewsAgent 类，避免 sentiment_brief 依赖重型 agent 模块。
# ──────────────────────────────────────────────────────────────

# 催化关键词（从 news_agent.py 的 _item_impact_score 同步，含中文 A 股词）
_CATALYST_KEYWORDS = (
    # English
    "beat",
    "beats",
    "miss",
    "earnings",
    "revenue",
    "guidance",
    "approval",
    "launch",
    "upgrade",
    "downgrade",
    "lawsuit",
    "investigation",
    "merger",
    "acquisition",
    "dividend",
    # 中文（A 股新闻催化识别）
    "财报",
    "业绩",
    "超预期",
    "不及预期",
    "净利润",
    "营收",
    "减持",
    "增持",
    "立案",
    "重组",
    "并购",
    "中标",
    "回购",
    "停牌",
    "分红",
    "解禁",
)

# 新闻条目自带情绪字段优先级（与 news_agent._extract_item_sentiment 一致）
_SENTIMENT_SCORE_KEYS = (
    "sentiment_score",
    "score",
    "ticker_sentiment_score",
    "overall_sentiment_score",
    "news_sentiment_score",
)
_SENTIMENT_LABEL_KEYS = (
    "sentiment_label",
    "ticker_sentiment_label",
    "overall_sentiment_label",
    "sentiment",
)


def _light_item_title(item: Dict[str, Any]) -> str:
    return str(item.get("headline") or item.get("title") or "").strip()


def _light_coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace("%", ""))
        except (ValueError, AttributeError):
            return None
    return None


def _light_sentiment_bucket(score: Optional[float], label: str) -> str:
    lowered = str(label or "").lower()
    if "neutral" in lowered:
        return "neutral"
    if "bull" in lowered or "positive" in lowered:
        return "positive"
    if "bear" in lowered or "negative" in lowered:
        return "negative"
    if score is None:
        return "neutral"
    if score >= 0.15:
        return "positive"
    if score <= -0.15:
        return "negative"
    return "neutral"


def _light_extract_sentiment(item: Dict[str, Any]) -> Optional[str]:
    """从单条新闻自带字段提取情绪 bucket；无情绪信号返回 None（不计入样本）。"""
    score: Optional[float] = None
    for key in _SENTIMENT_SCORE_KEYS:
        score = _light_coerce_float(item.get(key))
        if score is not None:
            break
    label = ""
    for key in _SENTIMENT_LABEL_KEYS:
        raw_label = item.get(key)
        if isinstance(raw_label, dict):
            raw_label = raw_label.get("label")
        if raw_label:
            label = str(raw_label)
            break
    if score is None and not label:
        return None
    return _light_sentiment_bucket(score, label)


def _light_sentiment_bias(news_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for item in news_items:
        if not isinstance(item, dict):
            continue
        bucket = _light_extract_sentiment(item)
        if bucket is None:
            continue
        counts[bucket] += 1

    total = sum(counts.values())
    if counts["positive"] > counts["negative"]:
        label = "bullish"
    elif counts["negative"] > counts["positive"]:
        label = "bearish"
    else:
        label = "neutral"

    return {
        "label": label,
        "average_score": None,  # 轻量模式无逐条分数平均（防止假精度）
        "positive_count": counts["positive"],
        "negative_count": counts["negative"],
        "neutral_count": counts["neutral"],
        "sample_size": total,
        "confidence": None,
    }


def _light_heat(news_count: int) -> Dict[str, Any]:
    if news_count >= 6:
        level = "elevated"
    elif news_count >= 3:
        level = "active"
    elif news_count > 0:
        level = "normal"
    else:
        level = "thin"
    return {"level": level, "news_count": news_count, "basis": "chat_news_volume"}


def _light_catalyst_events(news_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    events: List[Dict[str, Any]] = []
    for item in news_items:
        if not isinstance(item, dict):
            continue
        title = _light_item_title(item)
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
                or item.get("published")
                or item.get("date"),
                "source": item.get("source") or "news",
            }
        )
    return {"count": len(events), "events": events[:8]}


def build_light_snapshot(ticker: str, news_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从新闻列表构建轻量舆情快照（Chat 快速模式用，零额外 API 调用）。

    与 NewsAgent 的完整快照相比：
    - sentiment_bias: 仅从新闻条目自带的 sentiment 字段统计；无则 sample_size=0
      （渲染器显示"情绪样本不足"）
    - heat: 新闻数量
    - catalyst_events: 用催化关键词扫描标题（确定性，含中文 A 股词）
    - price_transmission: status="todo"（渲染器自动跳过该区块——数据真实性防线）

    Args:
        ticker: 标的代码（用于简报标题）
        news_items: 新闻列表（dict，字段约定见 sentiment_brief._render_news_list）

    Returns:
        与 render_stock_brief 期望的 snapshot 结构兼容的 dict
    """
    safe_items = [item for item in (news_items or []) if isinstance(item, dict)]
    return {
        "ticker": str(ticker or "").strip().upper(),
        "sentiment_bias": _light_sentiment_bias(safe_items),
        "heat": _light_heat(len(safe_items)),
        "catalyst_events": _light_catalyst_events(safe_items),
        "price_transmission": {
            "status": "todo",
            "source": None,
            "price_change_pct": None,
        },
        "source": "chat_light_snapshot",
    }
