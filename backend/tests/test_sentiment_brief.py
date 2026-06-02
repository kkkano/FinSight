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
