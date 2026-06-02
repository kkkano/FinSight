# 新闻舆情简报实现计划（P0-9）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把"拉新闻只给列表"的新闻 Agent 升级为"观点先行、证据殿后"的舆情简报 Agent。

**Architecture:** 确定性骨架（NewsSentimentSnapshot 渲染）+ LLM 观点段。废除 fetch/analyze
二分路由，所有新闻请求统一走舆情简报。新增独立渲染器 `sentiment_brief.py`，supervisor
路由收口为 `_handle_news_brief`。

**Tech Stack:** Python 3.12 + LangChain + pytest

**关联文档:** 设计规格 `docs/plans/2026-06-02_news_sentiment_brief_spec.md`（已批准定稿）

**执行注意:**
- 测试命令：`cd /e/FinSight && python -m pytest backend/tests/<file> -v`
- commit 前必须征得主人同意（全局规则）
- 任务有依赖顺序：Task 1/2 独立可先做，Task 3 → Task 4 → Task 5 → Task 6 必须按序

---

## Task 1: 修复来源重复显示

**问题:** `[标题](url) (来源)` 格式中，标题末尾常自带来源（"... - Yahoo Finance"），来源出现两次。

**Files:**
- Modify: `backend/tools/news.py:249-266`（`_format_headline_line`）
- Test: `backend/tests/test_news_source_dedup.py`（新建）

- [ ] **Step 1.1: 写失败测试**

创建 `backend/tests/test_news_source_dedup.py`：

```python
"""P0-9 Task1: 新闻条目来源不得重复显示"""
from backend.tools.news import _format_headline_line, _strip_trailing_source


def test_strip_trailing_source_with_dash():
    assert _strip_trailing_source("Apple Rises 5% - Yahoo Finance", "Yahoo Finance") == "Apple Rises 5%"


def test_strip_trailing_source_with_pipe():
    assert _strip_trailing_source("Apple Q2 Earnings Beat | Bloomberg", "Bloomberg") == "Apple Q2 Earnings Beat"


def test_strip_trailing_source_no_match_keeps_title():
    assert _strip_trailing_source("Apple Rises - strong demand", "Reuters") == "Apple Rises - strong demand"


def test_format_headline_line_no_duplicate_source():
    line = _format_headline_line(
        date_str="2026-06-01",
        title="Apple Q2 Earnings Beat Expectations - Reuters",
        source="Reuters",
        url="https://example.com/a",
    )
    # 来源 "Reuters" 在整行中只能出现一次
    assert line.count("Reuters") == 1


def test_format_headline_line_unified_format():
    line = _format_headline_line(
        date_str="2026-06-01",
        title="Apple Rises",
        source="Reuters",
        url="https://example.com/a",
    )
    # 新格式：[标题](url) — 来源 · 日期
    assert "[Apple Rises](https://example.com/a)" in line
    assert "— Reuters" in line
    assert "2026-06-01" in line
```

- [ ] **Step 1.2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_news_source_dedup.py -v
```
预期：FAIL（`_strip_trailing_source` 不存在）

- [ ] **Step 1.3: 实现 `_strip_trailing_source` 并改写 `_format_headline_line`**

在 `backend/tools/news.py` 的 `_format_headline_line`（249 行）之前添加：

```python
def _strip_trailing_source(title: str, source: str) -> str:
    """剥离标题末尾自带的来源后缀（P0-9: 防来源重复显示）。

    只剥离与 source 字段相同（忽略大小写）的尾部片段，
    例如 "Apple Rises - Yahoo Finance" + source="Yahoo Finance" -> "Apple Rises"。
    """
    clean_title = (title or "").strip()
    clean_source = (source or "").strip()
    if not clean_title or not clean_source:
        return clean_title
    pattern = re.compile(
        r"\s*[-|–|—|\|]\s*" + re.escape(clean_source) + r"\s*$",
        flags=re.IGNORECASE,
    )
    return pattern.sub("", clean_title).strip()
```

将 `_format_headline_line`（249-266 行）整体替换为：

```python
def _format_headline_line(
    date_str: str,
    title: str,
    source: str,
    url: str = "",
    snippet: str = "",
) -> str:
    tags = _headline_tags(f"{title} {snippet}".strip())
    tag_text = f"[{'/'.join(tags)}] " if tags else ""
    clean_source = (source or "").strip()
    # P0-9: 剥离标题尾部重复的来源，统一为 "[标题](url) — 来源 · 日期" 格式
    clean_title = _strip_trailing_source(title, clean_source) or "Untitled"
    display_title = f"[{clean_title}]({url})" if url else clean_title
    clean_snippet = (snippet or "").strip()
    if len(clean_snippet) > 160:
        clean_snippet = clean_snippet[:157] + "..."
    snippet_text = f" - {clean_snippet}" if clean_snippet else ""
    meta_parts = [p for p in (clean_source, date_str) if p]
    meta_text = f" — {' · '.join(meta_parts)}" if meta_parts else ""
    return f"{tag_text}{display_title}{meta_text}{snippet_text}".strip()
```

- [ ] **Step 1.4: 运行测试 + 回归**

```bash
python -m pytest backend/tests/test_news_source_dedup.py backend/tests/test_news_parsing.py backend/tests/test_news_tags.py backend/tests/test_dashboard_news_ranking.py -v
```
预期：新测试 PASS；若现有测试断言旧格式 `[date] [Title](url) (source)`，按新格式更新断言（格式变更是本任务的目的）。

- [ ] **Step 1.5: 提交（需主人同意）**

```bash
git add backend/tools/news.py backend/tests/
git commit -m "fix(news): strip duplicate source suffix, unified headline format (P0-9)"
```

---

## Task 2: 中文催化词 + 数据真实性防线

**问题:** 催化关键词全英文（A股新闻全漏检）；假可靠度 0.55 进证据链；价格传导 TODO 文案可能外泄。

**Files:**
- Modify: `backend/agents/news_agent.py:539-555`（催化词）
- Modify: `backend/agents/news_agent.py:186-198`（假可靠度）
- Test: `backend/tests/test_news_agent_truthfulness.py`（新建）

- [ ] **Step 2.1: 写失败测试**

创建 `backend/tests/test_news_agent_truthfulness.py`：

```python
"""P0-9 Task2: 新闻 agent 数据真实性防线"""
from unittest.mock import MagicMock
from backend.agents.news_agent import NewsAgent


def _make_agent(tools=None):
    cache = MagicMock()
    cache.get.return_value = None
    return NewsAgent(llm=None, cache=cache, tools_module=tools)


def test_chinese_catalyst_keywords_detected():
    """中文新闻的催化事件必须能被识别"""
    agent = _make_agent()
    item = {"headline": "贵州茅台发布财报：净利润超预期增长20%", "source_reliability": {"reliability_score": 0.9}}
    score = agent._item_impact_score(item)
    assert score >= 0.72, f"中文催化新闻 impact score={score}，应 >= 0.72"


def test_english_catalyst_still_detected():
    agent = _make_agent()
    item = {"headline": "Apple earnings beat expectations", "source_reliability": {"reliability_score": 0.9}}
    assert agent._item_impact_score(item) >= 0.72


def test_default_reliability_not_fake():
    """无评分工具时，可靠度必须标记为未评估，不得编造 0.55"""
    agent = _make_agent(tools=None)
    rel = agent._score_reliability_for_item({"source": "unknown", "url": ""})
    assert rel.get("reason") == "unscored"
    assert rel.get("reliability_score") is None
    assert rel.get("reliability_tier") == "unscored"


def test_unscored_reliability_not_in_confidence():
    """未评估的可靠度不得变成证据 confidence"""
    agent = _make_agent(tools=None)
    items = agent._annotate_reliability([{"headline": "Some news", "url": "https://x.com/a"}])
    assert len(items) == 1
    # 未评估时不注入 confidence（保持上游原值或缺失）
    assert "confidence" not in items[0] or items[0]["confidence"] != 0.55
```

- [ ] **Step 2.2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_news_agent_truthfulness.py -v
```
预期：FAIL

- [ ] **Step 2.3: 补中文催化词**

`backend/agents/news_agent.py:539-555`，将 `catalyst_keywords` 元组替换为：

```python
        catalyst_keywords = (
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
            # 中文（P0-9: A股新闻催化识别）
            "财报",
            "业绩",
            "超预期",
            "不及预期",
            "净利润",
            "营收",
            "减持",
            "增持",
            "立案",
            "调查",
            "重组",
            "并购",
            "中标",
            "回购",
            "停牌",
            "分红",
            "解禁",
        )
```

- [ ] **Step 2.4: 修复假可靠度**

`backend/agents/news_agent.py:186-198`，将 `_score_reliability_for_item` 替换为：

```python
    _UNSCORED_RELIABILITY = {"reliability_score": None, "reliability_tier": "unscored", "reason": "unscored"}

    def _score_reliability_for_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        scorer = getattr(self.tools, "score_news_source_reliability", None)
        if not scorer:
            # P0-9: 无评分工具时诚实标记未评估，不编造 0.55
            return dict(self._UNSCORED_RELIABILITY)
        try:
            payload = scorer(source=item.get("source", ""), url=item.get("url", ""))
            if isinstance(payload, dict):
                score = payload.get("reliability_score")
                if isinstance(score, (int, float)):
                    return payload
        except Exception:
            pass
        return dict(self._UNSCORED_RELIABILITY)
```

同步修改 `_annotate_reliability`（200-212 行）：score 为 None 时不注入 confidence：

```python
    def _annotate_reliability(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        annotated: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            rel = self._score_reliability_for_item(item)
            cloned = dict(item)
            cloned["source_reliability"] = rel
            score = rel.get("reliability_score")
            # P0-9: 只有真实评分才进 confidence；未评估(None)不注入
            if isinstance(score, (int, float)) and "confidence" not in cloned:
                cloned["confidence"] = max(0.1, min(0.95, float(score)))
            annotated.append(cloned)
        return annotated
```

同步检查 `_summarize_reliability`（214-239 行）和 `_item_impact_score`（528-558 行）：
两处对 `rel.get("reliability_score")` 已有 `isinstance(score, (int, float))` 防御，None 会被自然跳过，无需修改。

- [ ] **Step 2.5: 运行测试确认通过 + 回归**

```bash
python -m pytest backend/tests/test_news_agent_truthfulness.py backend/tests/ -k "news" -v
```
预期：PASS

- [ ] **Step 2.6: 提交（需主人同意）**

```bash
git add backend/agents/news_agent.py backend/tests/test_news_agent_truthfulness.py
git commit -m "fix(news-agent): Chinese catalyst keywords + honest unscored reliability (P0-9)"
```

---

## Task 3: 舆情简报渲染器 sentiment_brief.py

**Files:**
- Create: `backend/agents/sentiment_brief.py`
- Test: `backend/tests/test_sentiment_brief.py`（新建）

- [ ] **Step 3.1: 写失败测试**

创建 `backend/tests/test_sentiment_brief.py`：

```python
"""P0-9 Task3: 舆情简报确定性骨架渲染"""
from backend.agents.sentiment_brief import render_stock_brief


def _snapshot(**overrides):
    base = {
        "ticker": "AAPL",
        "as_of": "2026-06-02T10:00:00",
        "sentiment_bias": {
            "label": "bullish", "average_score": 0.32, "sample_size": 6,
            "positive_ratio": 0.6, "negative_ratio": 0.2, "neutral_ratio": 0.2,
        },
        "sentiment_trend": {"direction": "improving"},
        "heat": {"level": "active", "news_count": 5, "event_count": 2},
        "catalyst_events": {
            "count": 2,
            "events": [
                {"title": "Q2 earnings beat", "category": "high_impact_news", "date": "2026-06-01", "impact_score": 0.85},
                {"title": "Earnings call", "category": "earnings", "date": "2026-06-10"},
            ],
        },
        "price_transmission": {"status": "resonance", "analysis": "偏多舆情与近期价格上行共振。", "price_change_pct": 2.5},
        "inputs": {},
    }
    base.update(overrides)
    return base


def test_brief_contains_skeleton_sections():
    md = render_stock_brief(_snapshot(), news_items=[], opinion="测试观点段。")
    assert "AAPL 舆情简报" in md
    assert "偏多" in md          # bullish -> 中文
    assert "+0.32" in md
    assert "测试观点段。" in md   # LLM 观点段
    assert "催化事件" in md
    assert "情绪与价格" in md


def test_brief_without_opinion_still_renders_skeleton():
    """LLM 观点段缺失时骨架照常输出（降级阶梯）"""
    md = render_stock_brief(_snapshot(), news_items=[], opinion=None)
    assert "AAPL 舆情简报" in md
    assert "催化事件" in md


def test_brief_skips_todo_price_transmission():
    """价格传导 status=todo 时整个区块不渲染，TODO 文案绝不外泄"""
    snap = _snapshot(price_transmission={"status": "todo", "analysis": "TODO: 接入..."})
    md = render_stock_brief(snap, news_items=[], opinion="观点。")
    assert "TODO" not in md
    assert "情绪与价格" not in md


def test_brief_insufficient_sentiment_sample():
    """样本 < 3 时显示"情绪样本不足"，不显示具体分数"""
    snap = _snapshot(sentiment_bias={"label": "neutral", "average_score": 0.05, "sample_size": 1})
    md = render_stock_brief(snap, news_items=[], opinion="观点。")
    assert "情绪样本不足" in md
    assert "+0.05" not in md


def test_brief_no_catalyst_shows_honest_message():
    """有新闻但无催化时显示"未识别到催化事件"而非 0 个"""
    snap = _snapshot(catalyst_events={"count": 0, "events": []})
    md = render_stock_brief(snap, news_items=[{"headline": "x", "url": ""}], opinion="观点。")
    assert "未识别到催化事件" in md


def test_brief_news_list_rendered_with_unscored_marker():
    """未评估可靠度的新闻不显示假分数"""
    items = [
        {"headline": "Apple Q2 beat", "url": "https://x.com/a", "source": "Reuters",
         "datetime": "2026-06-01", "source_reliability": {"reliability_score": 0.9}},
        {"headline": "Some blog post", "url": "https://y.com/b", "source": "blog",
         "datetime": "2026-06-01", "source_reliability": {"reliability_score": None, "reason": "unscored"}},
    ]
    md = render_stock_brief(_snapshot(), news_items=items, opinion="观点。")
    assert "依据新闻" in md
    assert "Apple Q2 beat" in md
```

- [ ] **Step 3.2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_sentiment_brief.py -v
```
预期：FAIL（模块不存在）

- [ ] **Step 3.3: 实现 `backend/agents/sentiment_brief.py`**

```python
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
_TREND_LABELS = {"improving": "改善中", "deteriorating": "恶化中", "stable": "平稳", "unknown": ""}
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
```

- [ ] **Step 3.4: 运行测试确认通过**

```bash
python -m pytest backend/tests/test_sentiment_brief.py -v
```
预期：全部 PASS

- [ ] **Step 3.5: 提交（需主人同意）**

```bash
git add backend/agents/sentiment_brief.py backend/tests/test_sentiment_brief.py
git commit -m "feat(news): deterministic sentiment brief renderer (P0-9)"
```

---

## Task 4: NewsAgent 输出舆情简报

**Files:**
- Modify: `backend/agents/news_agent.py:1031-1084`（`_first_summary` / `_deterministic_summary`）
- Test: 扩展 `backend/tests/test_news_agent_truthfulness.py`

- [ ] **Step 4.1: 写失败测试（追加到 test_news_agent_truthfulness.py）**

```python
import asyncio
from dataclasses import asdict


def test_first_summary_renders_brief_without_llm():
    """无 LLM 时 _first_summary 输出舆情简报骨架（而非标题拼接）"""
    agent = _make_agent()
    agent._current_ticker = "AAPL"
    # 构造最小可用的 snapshot
    from backend.agents.news_agent import NewsSentimentSnapshot
    agent._last_sentiment_snapshot = NewsSentimentSnapshot(
        ticker="AAPL", as_of="2026-06-02T10:00:00",
        sentiment_bias={"label": "bullish", "average_score": 0.3, "sample_size": 5,
                        "positive_ratio": 0.6, "negative_ratio": 0.2, "neutral_ratio": 0.2},
        sentiment_trend={"direction": "improving"},
        heat={"level": "active", "news_count": 5, "event_count": 0},
        catalyst_events={"count": 1, "events": [{"title": "Earnings beat", "category": "high_impact_news", "date": "2026-06-01"}]},
        price_transmission={"status": "todo", "analysis": "TODO: x"},
    )
    data = [{"headline": "Apple Q2 beat", "url": "https://x.com/a", "source": "Reuters", "ticker": "AAPL"}]

    summary = asyncio.run(agent._first_summary(data))

    assert "舆情简报" in summary
    assert "TODO" not in summary  # 价格传导 todo 不外泄
```

- [ ] **Step 4.2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_news_agent_truthfulness.py::test_first_summary_renders_brief_without_llm -v
```
预期：FAIL

- [ ] **Step 4.3: 改写 `_first_summary` 与 `_deterministic_summary`**

`backend/agents/news_agent.py`，文件顶部 import 区追加：

```python
from backend.agents.sentiment_brief import render_stock_brief
```

将 `_first_summary`（1031-1061 行）替换为：

```python
    async def _first_summary(self, data: List[Any]) -> str:
        """P0-9: 输出舆情简报（确定性骨架 + LLM 观点段）"""
        if not data:
            return "未找到相关新闻。"

        snapshot = self._last_sentiment_snapshot
        snapshot_dict = asdict(snapshot) if isinstance(snapshot, NewsSentimentSnapshot) else {}

        # LLM 观点段（唯一的 LLM 依赖，失败时为 None -> 骨架照常输出）
        opinion = None
        if self.llm is not None:
            news_context_parts = []
            for item in data[:8]:
                if not isinstance(item, dict):
                    continue
                headline = item.get("headline", item.get("title", ""))
                source = item.get("source", "")
                date = item.get("datetime", item.get("published_at", ""))
                meta = f" ({source}" + (f", {date}" if date else "") + ")" if source else ""
                news_context_parts.append(f"- {headline}{meta}")
            news_context = "\n".join(news_context_parts)
            snapshot_summary = self._snapshot_text(snapshot) if isinstance(snapshot, NewsSentimentSnapshot) else ""

            opinion = await self._llm_analyze(
                f"舆情快照：{snapshot_summary}\n\n新闻列表：\n{news_context}",
                role="资深舆情分析师",
                focus=(
                    "基于舆情快照和新闻列表，输出 2-4 句核心观点：\n"
                    "1. 识别 1-2 条驱动舆情的主线事件\n"
                    "2. 说明事件对标的的影响路径\n"
                    "3. 给出短期方向判断（结合情绪与价格关系）\n"
                    "要求：连贯段落、不用列表、不复述新闻标题、中文输出。"
                ),
            )

        # 风险（来源可靠度警告）
        extra_risks: List[str] = []
        reliability_summary = self._last_reliability_summary if isinstance(self._last_reliability_summary, dict) else {}
        avg_rel = reliability_summary.get("avg_reliability")
        if isinstance(avg_rel, (int, float)) and float(avg_rel) < 0.65:
            extra_risks.append("新闻来源整体可靠度偏低，关键结论建议以官方披露为准")

        if snapshot_dict:
            return render_stock_brief(snapshot_dict, list(data), opinion, extra_risks=extra_risks)
        return self._deterministic_summary(data)
```

`_deterministic_summary`（1063-1084 行）保留不动（作为 snapshot 完全缺失时的兜底）。

确认文件顶部已有 `from dataclasses import asdict, dataclass, field`（已存在于第 1 行）。

- [ ] **Step 4.4: 运行测试 + 回归**

```bash
python -m pytest backend/tests/test_news_agent_truthfulness.py backend/tests/ -k "news" -v
```
预期：PASS。注意 `_llm_analyze` 的实际签名在 `backend/agents/base_agent.py` 中——若参数名不是
`role`/`focus`，按实际签名调整（搜索 `def _llm_analyze`）。

- [ ] **Step 4.5: 提交（需主人同意）**

```bash
git add backend/agents/news_agent.py backend/tests/test_news_agent_truthfulness.py
git commit -m "feat(news-agent): research output is now sentiment brief (P0-9)"
```

---

## Task 5: Supervisor 路由重构（废二分 + 删 bug + 统一入口）

**Files:**
- Modify: `backend/orchestration/supervisor_agent.py:298-306`（路由分发）
- Delete: `supervisor_agent.py:455-496`（`_classify_news_subintent`）
- Modify: `supervisor_agent.py:498-665`（`_handle_news` 重构为 `_handle_news_brief`）
- Test: `backend/tests/test_supervisor_news_routing.py`（新建）

- [ ] **Step 5.1: 写失败测试**

创建 `backend/tests/test_supervisor_news_routing.py`：

```python
"""P0-9 Task5: NEWS 意图统一走舆情简报，二分法已废除"""
import pytest
from backend.orchestration.supervisor_agent import SupervisorAgent


def test_classify_news_subintent_removed():
    """fetch/analyze 二分法必须已删除"""
    assert not hasattr(SupervisorAgent, "_classify_news_subintent")


def test_handle_news_brief_exists():
    """统一入口 _handle_news_brief 必须存在"""
    assert hasattr(SupervisorAgent, "_handle_news_brief")


def test_old_handlers_removed():
    """旧的 _handle_news 已被 _handle_news_brief 取代"""
    assert not hasattr(SupervisorAgent, "_handle_news")
```

- [ ] **Step 5.2: 运行测试确认失败**

```bash
python -m pytest backend/tests/test_supervisor_news_routing.py -v
```
预期：FAIL

- [ ] **Step 5.3: 重构 supervisor_agent.py**

按顺序执行以下修改：

(a) **路由分发**（298-306 行），替换为：

```python
        # NEWS 意图：统一走舆情简报（P0-9，二分法已废除）
        if intent == AgentIntent.NEWS:
            return await self._handle_news_brief(query, ticker, classification, context_summary)
```

(b) **删除** `_classify_news_subintent` 整个方法（455-496 行）。

(c) **重命名并重构** `_handle_news`（498-665 行）为 `_handle_news_brief`：

```python
    async def _handle_news_brief(self, query: str, ticker: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """统一新闻入口：舆情简报（P0-9）

        - Selection Context（用户点"问这条"）-> 引用新闻深度分析（复用 _handle_news_analysis）
        - 有 ticker -> NewsAgent.research() 输出舆情简报
        - 无 ticker -> 泛市场舆情简报（见 _handle_market_news_brief）
        """
        trace_emitter = get_trace_emitter()

        try:
            # ── Selection Context：引用新闻深度分析（保留现有实现）──
            if context_summary and "[System Context]" in context_summary:
                if "用户正在询问以下新闻" in context_summary or "引用新闻" in context_summary:
                    logger.info("[Supervisor] Selection Context -> news deep analysis")
                    return await self._handle_news_analysis(query, ticker, classification, context_summary)

            # ── 无 ticker：泛市场舆情简报 ──
            if not ticker:
                return await self._handle_market_news_brief(query, classification, context_summary)

            # ── 有 ticker：NewsAgent 舆情简报 ──
            news_agent = self.agents.get("news")
            if news_agent:
                try:
                    self._consume_round("agent:news")
                    trace_emitter.emit_agent_start("NewsAgent", query=query, ticker=ticker)
                    agent_start_time = time.perf_counter()

                    output = await news_agent.research(query, ticker)

                    agent_duration_ms = int((time.perf_counter() - agent_start_time) * 1000)
                    trace_emitter.emit_agent_done(
                        "NewsAgent",
                        duration_ms=agent_duration_ms,
                        success=bool(output and output.summary),
                    )

                    # P0-9: 删除了旧版关键词回退检查（编码损坏 bug），
                    # NewsAgent 的简报输出直接返回
                    if output and output.summary:
                        return self._result(
                            success=True,
                            intent=AgentIntent.NEWS,
                            response=output.summary,
                            agent_outputs={"news": output},
                            classification=classification,
                        )
                except Exception as e:
                    logger.info(f"[Supervisor] NewsAgent failed: {e}")

            # ── NewsAgent 不可用：降级为原始新闻列表（保留原有工具回退逻辑）──
            self._consume_round("tool:news")
            tool_name = "get_company_news"
            trace_emitter.emit_tool_start(tool_name, {"ticker": ticker})
            tool_start_time = time.perf_counter()

            news_data = self.tools_module.get_company_news(ticker)

            tool_duration_ms = int((time.perf_counter() - tool_start_time) * 1000)
            trace_emitter.emit_tool_end(
                tool_name,
                success=not (isinstance(news_data, dict) and news_data.get("error")),
                duration_ms=tool_duration_ms,
                result_preview=str(news_data)[:100] if news_data else None,
            )

            if isinstance(news_data, dict) and news_data.get("error"):
                return self._result(
                    success=True,
                    intent=AgentIntent.NEWS,
                    response=f"获取新闻失败：{news_data.get('error')}",
                    classification=classification,
                )

            if isinstance(news_data, list):
                formatter = getattr(self.tools_module, "format_news_items", None) if self.tools_module else None
                if formatter:
                    base_response = formatter(news_data, title=f"{ticker} 新闻")
                else:
                    base_response = "\n".join(
                        f"- {(item.get('headline') or item.get('title') or 'No title')}"
                        for item in news_data
                        if isinstance(item, dict)
                    )
                # 诚实标注这是降级输出
                base_response = f"{base_response}\n\n> ⚠️ 舆情分析暂不可用，以上为原始新闻列表"
            else:
                base_response = str(news_data) if news_data else "暂无相关新闻"

            if isinstance(base_response, str) and ("Connection error" in base_response or "Search error" in base_response):
                base_response = "新闻源连接失败，请稍后重试。"

            return self._result(
                success=True,
                intent=AgentIntent.NEWS,
                response=base_response,
                classification=classification,
            )
        except Exception as e:
            return self._result(
                success=False,
                intent=AgentIntent.NEWS,
                response="新闻源连接失败，请稍后重试。",
                classification=classification,
                errors=[str(e)],
            )
```

(d) **检查删除影响**：

```bash
grep -rn "_classify_news_subintent\|_handle_news\b" backend/ --include="*.py" | grep -v test_ | grep -v "_handle_news_brief\|_handle_news_analysis"
```

确认无残留引用。`_handle_general_news`（666-671 行）原来调用 `_handle_news(query, None, ...)`，
改为调用 `self._handle_news_brief(query, None, classification, context_summary)` 或直接删除
（如果它只是个转发函数且 NEWS 无 ticker 路由已收口到 `_handle_news_brief`）。

`_is_news_analysis_requested` 和 `_news_analysis_failure_response`（104-130 行）若只被旧
`_handle_news` 引用，一并删除；若被 `_handle_news_analysis` 引用则保留。

- [ ] **Step 5.4: 临时桩 `_handle_market_news_brief`**

Task 6 才实现泛市场简报，本任务先加最小桩（保持旧行为）：

```python
    async def _handle_market_news_brief(self, query: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """泛市场舆情简报（Task 6 实现完整版，当前为搜索降级）"""
        self._consume_round("tool:news")
        news_data = self.tools_module.search(query) if self.tools_module else None
        response = str(news_data) if news_data else "暂无相关新闻"
        if "Connection error" in response or "Search error" in response:
            response = "新闻源连接失败，请稍后重试。"
        return self._result(
            success=True,
            intent=AgentIntent.NEWS,
            response=response,
            classification=classification,
        )
```

- [ ] **Step 5.5: 运行测试 + 回归**

```bash
python -m pytest backend/tests/test_supervisor_news_routing.py backend/tests/test_supervisor_agent.py backend/tests/test_chat_response_contract.py -v
```

`test_supervisor_agent.py` 中引用 `_classify_news_subintent` / `_handle_news` 的旧测试：
删除二分法相关断言，保留并更新为新路由断言。

- [ ] **Step 5.6: 提交（需主人同意）**

```bash
git add backend/orchestration/supervisor_agent.py backend/tests/
git commit -m "refactor(supervisor): unified news brief routing, remove fetch/analyze split + encoding bug (P0-9)"
```

---

## Task 6: 泛市场舆情简报

**Files:**
- Modify: `backend/agents/sentiment_brief.py`（追加 `render_market_brief`）
- Modify: `backend/orchestration/supervisor_agent.py`（完善 `_handle_market_news_brief`）
- Test: 扩展 `backend/tests/test_sentiment_brief.py`

- [ ] **Step 6.1: 写失败测试（追加到 test_sentiment_brief.py）**

```python
from backend.agents.sentiment_brief import render_market_brief


def test_market_brief_with_themes():
    themes = [
        {"name": "美联储政策", "sentiment": "negative", "news_indices": [0, 1]},
        {"name": "科技股财报", "sentiment": "positive", "news_indices": [2]},
    ]
    news = [
        {"headline": "Fed signals higher rates", "url": "", "source": "Reuters"},
        {"headline": "Treasury yields spike", "url": "", "source": "Bloomberg"},
        {"headline": "NVDA earnings beat", "url": "", "source": "CNBC"},
    ]
    md = render_market_brief(themes=themes, news_items=news, opinion="市场观点段。")
    assert "市场舆情简报" in md
    assert "美联储政策" in md
    assert "市场观点段。" in md
    assert "3 条" in md


def test_market_brief_clustering_failed_fallback():
    """聚类失败（themes 为空）时退化为带说明的新闻列表"""
    news = [{"headline": "Some news", "url": "", "source": "x"}]
    md = render_market_brief(themes=[], news_items=news, opinion=None)
    assert "Some news" in md
    assert "主题聚类暂不可用" in md


def test_market_brief_low_confidence_news_marked():
    """spec 防线5：低置信（<0.5）新闻在列表标注 ⚠️"""
    news = [
        {"headline": "Reliable news", "url": "", "source": "Reuters", "confidence": 0.8},
        {"headline": "Sketchy search result", "url": "", "source": "search", "confidence": 0.4},
    ]
    md = render_market_brief(themes=[], news_items=news, opinion=None)
    # 低置信条目带 ⚠️ 标注，高置信条目不带
    assert "⚠️" in md
    lines = md.splitlines()
    sketchy_line = next(line for line in lines if "Sketchy" in line)
    reliable_line = next(line for line in lines if "Reliable" in line)
    assert "⚠️" in sketchy_line
    assert "⚠️" not in reliable_line
```

- [ ] **Step 6.2: 运行测试确认失败，然后实现 `render_market_brief`**

在 `backend/agents/sentiment_brief.py` 末尾追加：

```python
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
```

- [ ] **Step 6.3: 完善 supervisor 的 `_handle_market_news_brief`**

替换 Task 5 的临时桩。核心逻辑：搜索新闻 → 一次 LLM 调用做主题聚类+观点（JSON）→ 渲染：

```python
    _MARKET_CLUSTER_PROMPT = """<role>市场舆情分析师</role>
<task>对以下财经新闻做主题聚类并给出核心观点</task>

<news>
{news_block}
</news>

<output_format>
只输出 JSON（不要 markdown 代码块标记）：
{{"themes": [{{"name": "主题名", "sentiment": "positive|negative|neutral", "news_indices": [0, 1]}}], "opinion": "2-4 句核心观点，中文"}}
</output_format>

<rules>
- 主题 2-4 个；news_indices 是新闻在列表中的序号（从 0 开始）
- 低质量/无标题的新闻不参与聚类
- opinion 要点明市场主线与方向，不复述标题
</rules>"""

    async def _handle_market_news_brief(self, query: str, classification: ClassificationResult, context_summary: str = None) -> SupervisorResult:
        """泛市场舆情简报（P0-9 Task 6）"""
        from backend.agents.sentiment_brief import render_market_brief

        trace_emitter = get_trace_emitter()
        self._consume_round("tool:news")

        # 1. 采集新闻
        trace_emitter.emit_tool_start("search", {"query": query})
        tool_start = time.perf_counter()
        raw = self.tools_module.search(query) if self.tools_module else None
        trace_emitter.emit_tool_end(
            "search",
            success=bool(raw),
            duration_ms=int((time.perf_counter() - tool_start) * 1000),
            result_preview=str(raw)[:100] if raw else None,
        )

        # 解析为结构化条目（复用 tools.news 的解析能力）
        news_items: list = []
        if isinstance(raw, str) and raw.strip():
            try:
                from backend.tools.news import _extract_search_items
                news_items = [
                    {"headline": item.get("title", ""), "url": item.get("url", ""), "source": "search", "snippet": item.get("snippet", "")}
                    for item in _extract_search_items(raw)
                    if item.get("title")
                ]
            except Exception:
                news_items = []
        elif isinstance(raw, list):
            news_items = [item for item in raw if isinstance(item, dict)]

        if not news_items:
            return self._result(
                success=True,
                intent=AgentIntent.NEWS,
                response="暂无相关市场新闻。",
                classification=classification,
            )

        # 2. 一次 LLM 调用：主题聚类 + 观点
        themes: list = []
        opinion = None
        try:
            from langchain_core.messages import HumanMessage
            import json as _json

            # spec 防线5：低置信（<0.5）新闻不参与主题聚类情绪统计
            clusterable = [
                item for item in news_items[:12]
                if not (isinstance(item.get("confidence"), (int, float)) and item["confidence"] < 0.5)
            ]
            news_block = "\n".join(
                f"{idx}. {item.get('headline', '')}" for idx, item in enumerate(clusterable)
            )
            prompt = self._MARKET_CLUSTER_PROMPT.format(news_block=news_block)

            llm_model = getattr(self.llm, "model_name", None) or getattr(self.llm, "model", "unknown")
            trace_emitter.emit_llm_start(model=llm_model, prompt_preview=prompt[:150])
            llm_start = time.perf_counter()

            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            text = response.content if hasattr(response, "content") else str(response)

            trace_emitter.emit_llm_end(
                model=llm_model,
                duration_ms=int((time.perf_counter() - llm_start) * 1000),
                success=True,
                output_preview=str(text)[:100],
            )

            # 容错解析 JSON（剥掉可能的代码块标记）
            cleaned = str(text).strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = _json.loads(cleaned)
            if isinstance(parsed, dict):
                themes = parsed.get("themes") or []
                opinion = parsed.get("opinion")
        except Exception as e:
            logger.info(f"[Supervisor] market news clustering failed: {e}")
            # 降级阶梯：聚类失败 -> themes 为空，渲染器自动退化为带说明的列表

        # 3. 渲染简报
        brief = render_market_brief(themes=themes, news_items=news_items, opinion=opinion)
        return self._result(
            success=True,
            intent=AgentIntent.NEWS,
            response=brief,
            classification=classification,
        )
```

- [ ] **Step 6.4: 运行测试 + 回归**

```bash
python -m pytest backend/tests/test_sentiment_brief.py backend/tests/test_supervisor_news_routing.py backend/tests/ -k "news or supervisor" -v
```
预期：PASS

- [ ] **Step 6.5: 提交（需主人同意）**

```bash
git add backend/agents/sentiment_brief.py backend/orchestration/supervisor_agent.py backend/tests/
git commit -m "feat(news): market-wide sentiment brief with theme clustering (P0-9)"
```

---

## 完成检查清单

- [ ] 全量回归：`python -m pytest backend/tests/ -x -q`
- [ ] 手工验证（需后端运行）：Chat 输入"拉几条 AAPL 新闻" → 应返回舆情简报而非纯列表
- [ ] 手工验证：Chat 输入"今天有什么财经新闻" → 应返回泛市场简报
- [ ] 更新 goal 记忆与路线图文档的 P0-9 状态
- [ ] 向主人汇报偏差与测试结果
