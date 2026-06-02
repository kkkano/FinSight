# -*- coding: utf-8 -*-
"""P0-9 corrected: 舆情简报接入真实 Chat 生产路径（render_stub -> chat_renderer）。

两层测试：
- build_light_snapshot 单元测试（轻量快照构建，零额外 API 调用）
- Chat 链路集成测试（render_stub 真实路径，验证个股/泛市场新闻走简报渲染）
"""
from __future__ import annotations

from backend.agents.sentiment_brief import build_light_snapshot
from backend.graph.nodes.render_stub import render_stub


# ──────────────────────────────────────────────────────────────
# build_light_snapshot 单元测试
# ──────────────────────────────────────────────────────────────


def test_build_light_snapshot_from_news_items():
    """从新闻列表构建轻量快照：ticker / heat / catalyst / price_transmission=todo。"""
    news_items = [
        {"title": "Apple Q2 earnings beat expectations", "url": "https://x.com/a", "source": "Reuters"},
        {"title": "Apple announces new product launch", "url": "https://x.com/b", "source": "CNBC"},
        {"title": "Random commentary", "url": "https://x.com/c", "source": "blog"},
    ]
    snap = build_light_snapshot("AAPL", news_items)

    assert snap["ticker"] == "AAPL"
    # heat = 新闻数量
    assert snap["heat"]["news_count"] == 3
    # 催化：earnings / launch 命中关键词
    assert snap["catalyst_events"]["count"] >= 2
    catalyst_titles = [e["title"] for e in snap["catalyst_events"]["events"]]
    assert any("earnings" in t.lower() for t in catalyst_titles)
    # 价格传导防线：status=todo（渲染器自动跳过该区块）
    assert snap["price_transmission"]["status"] == "todo"


def test_build_light_snapshot_chinese_catalyst():
    """中文催化关键词识别（A 股新闻）。"""
    news_items = [
        {"title": "某公司发布业绩预告，净利润超预期", "url": "", "source": "新浪财经"},
        {"title": "控股股东宣布增持计划", "url": "", "source": "东方财富"},
        {"title": "今日天气晴朗", "url": "", "source": "blog"},
    ]
    snap = build_light_snapshot("600519.SS", news_items)
    # 业绩/超预期/净利润 + 增持 -> 至少 2 条催化
    assert snap["catalyst_events"]["count"] >= 2
    catalyst_titles = [e["title"] for e in snap["catalyst_events"]["events"]]
    assert any("业绩" in t or "增持" in t for t in catalyst_titles)


def test_build_light_snapshot_empty_news():
    """空新闻：heat=0，无催化，sentiment 样本不足。"""
    snap = build_light_snapshot("TSLA", [])
    assert snap["ticker"] == "TSLA"
    assert snap["heat"]["news_count"] == 0
    assert snap["catalyst_events"]["count"] == 0
    assert snap["catalyst_events"]["events"] == []
    # 无 sentiment 字段 -> 样本量 0（渲染器显示"情绪样本不足"）
    assert snap["sentiment_bias"]["sample_size"] == 0
    assert snap["price_transmission"]["status"] == "todo"


def test_build_light_snapshot_sentiment_from_item_fields():
    """新闻条目自带 sentiment 字段时统计样本（与 NewsAgent 字段约定一致）。"""
    news_items = [
        {"title": "A", "sentiment_score": 0.5},
        {"title": "B", "sentiment_score": 0.4},
        {"title": "C", "sentiment_score": -0.3},
        {"title": "D", "sentiment_label": "positive"},
    ]
    snap = build_light_snapshot("AAPL", news_items)
    bias = snap["sentiment_bias"]
    assert bias["sample_size"] == 4
    assert bias["positive_count"] == 3
    assert bias["negative_count"] == 1


def test_build_light_snapshot_catalyst_english_word():
    """英文 "catalyst" 关键词识别（实测 "WWDC Key Catalyst" 标题没被识别的小修）。"""
    snap = build_light_snapshot("AAPL", [{"title": "WWDC Key Catalyst for AAPL", "url": ""}])
    assert snap["catalyst_events"]["count"] == 1
    assert any("Catalyst" in e["title"] for e in snap["catalyst_events"]["events"])


def test_build_light_snapshot_no_extra_api_calls():
    """轻量快照纯确定性：不依赖任何 tools / agent 实例。"""
    # 仅传 ticker + dict 列表即可完整构建，无任何外部依赖
    snap = build_light_snapshot("NVDA", [{"title": "NVDA revenue guidance raised", "url": ""}])
    assert snap["catalyst_events"]["count"] == 1  # revenue + guidance


# ──────────────────────────────────────────────────────────────
# Chat 链路集成测试（render_stub 真实生产路径）
# ──────────────────────────────────────────────────────────────


def _render_chat(state: dict) -> str:
    result = render_stub(
        {
            "query": state.get("query", ""),
            "output_mode": state.get("output_mode", "chat"),
            "subject": state.get("subject", {"subject_type": "company", "tickers": ["AAPL"]}),
            "operation": state.get("operation", {"name": "fetch"}),
            "tasks": state.get("tasks", []),
            "memory_context": state.get("memory_context", {}),
            "artifacts": state.get("artifacts", {}),
            "plan_ir": state.get("plan_ir", {"steps": []}),
            "trace": state.get("trace", {}),
            "intent_contract": state.get("intent_contract"),
        }
    )
    return result["artifacts"]["draft_markdown"]


def _stock_news_state() -> dict:
    return {
        "query": "AAPL 最近有什么新闻？",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "operation": {"name": "fetch"},
        "tasks": [
            {"id": "task_1", "subject_type": "company", "tickers": ["AAPL"], "operation": {"name": "fetch"}}
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "AAPL"}},
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {
                    "output": [
                        {
                            "title": "Apple Q2 earnings beat expectations",
                            "url": "https://example.com/aapl-earnings",
                            "source": "Reuters",
                            "published_at": "2026-05-30",
                        },
                        {
                            "title": "Apple unveils product launch",
                            "url": "https://example.com/aapl-launch",
                            "source": "CNBC",
                            "published_at": "2026-05-29",
                        },
                    ]
                }
            }
        },
    }


def test_chat_stock_news_renders_brief_not_freeform():
    """个股新闻走简报渲染：出现简报标题，不再是"我找到几条比较相关的消息"自由发挥。"""
    md = _render_chat(_stock_news_state())
    assert "AAPL 舆情简报" in md
    assert "依据新闻" in md
    assert "Apple Q2 earnings beat expectations" in md
    # 替换掉旧的 LLM 自由发挥格式
    assert "我找到几条比较相关的消息" not in md


def test_chat_stock_news_brief_has_catalyst():
    """个股简报含催化区块（earnings / launch 命中）。"""
    md = _render_chat(_stock_news_state())
    assert "催化事件" in md


def test_chat_stock_news_no_fake_price_transmission():
    """轻量快照 price_transmission=todo，简报不渲染情绪与价格区块（数据真实性防线）。"""
    md = _render_chat(_stock_news_state())
    assert "情绪与价格" not in md
    assert "TODO" not in md


def test_chat_market_news_no_ticker_renders_market_brief():
    """泛市场新闻（无 ticker，search 工具）走 render_market_brief。"""
    state = {
        "query": "今天市场有什么大事？",
        "subject": {"subject_type": "macro", "tickers": []},
        "operation": {"name": "fetch"},
        "tasks": [
            {"id": "task_1", "subject_type": "macro", "tickers": [], "operation": {"name": "fetch"}}
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "tool", "name": "search", "inputs": {"query": "market news"}},
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {
                    "output": [
                        {"title": "Fed signals higher rates", "url": "https://example.com/fed", "source": "Reuters"},
                        {"title": "Treasury yields spike", "url": "https://example.com/yields", "source": "Bloomberg"},
                    ]
                }
            }
        },
    }
    md = _render_chat(state)
    assert "市场舆情简报" in md
    assert "Fed signals higher rates" in md
    assert "我找到几条比较相关的消息" not in md


def test_chat_news_brief_does_not_break_price_only():
    """纯价格请求（无新闻）不受影响，不渲染简报。"""
    state = {
        "query": "AAPL 现在多少钱？",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "operation": {"name": "price"},
        "tasks": [
            {"id": "task_1", "subject_type": "company", "tickers": ["AAPL"], "operation": {"name": "price"}}
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "AAPL"}},
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {"output": {"ticker": "AAPL", "price": 276.83, "change_percent": -1.22}}
            }
        },
    }
    md = _render_chat(state)
    assert "舆情简报" not in md
    assert "276.83" in md


# ──────────────────────────────────────────────────────────────
# P0-9-2 双快照打架修复：NewsAgent 完整快照 > 轻量快照
#
# 现象（FINSIGHT_FORCE_AGENT_RESEARCH_CONFIG=true 时）：
# - NewsAgent 完整快照以 evidence(source=news_sentiment_snapshot) 混进新闻流
# - chat_renderer 把快照文本当新闻渲染，却用轻量快照渲染标题/催化
# 修复目标：
# 1. 快照条目不出现在新闻列表（被识别并移除）
# 2. 有完整快照时标题行用它的情绪数据（偏多 +0.10），不是"样本不足"
# 3. 催化区块用完整快照真实数量，不是"未识别到催化事件"
# ──────────────────────────────────────────────────────────────

# NewsAgent 完整快照的 EvidenceItem.text 文本格式（_snapshot_text 输出）
_SNAPSHOT_TEXT = (
    "AAPL 整体舆情: bullish (平均分 +0.10, 正/负/中占比 25%/12%/62%); "
    "趋势: deteriorating; 热度: active (新闻 3 条, 事件 3 个); "
    "催化事件: 3 个; 价格传导: neutral。"
)

# NewsAgent 完整快照的结构化 dict（asdict(NewsSentimentSnapshot)），meta.snapshot 形态
_SNAPSHOT_DICT = {
    "ticker": "AAPL",
    "as_of": "2026-06-02T10:00:00",
    "sentiment_bias": {
        "label": "bullish",
        "average_score": 0.10,
        "sample_size": 8,
        "positive_ratio": 0.25,
        "negative_ratio": 0.12,
        "neutral_ratio": 0.62,
    },
    "sentiment_trend": {"direction": "deteriorating"},
    "heat": {"level": "active", "news_count": 3, "event_count": 3},
    "catalyst_events": {
        "count": 3,
        "events": [
            {"title": "WWDC Key Catalyst", "category": "high_impact_news", "date": "2026-06-01"},
            {"title": "Q2 earnings call", "category": "earnings", "date": "2026-06-10"},
            {"title": "Dividend declaration", "category": "dividend", "date": "2026-06-15"},
        ],
    },
    "price_transmission": {"status": "neutral", "analysis": "舆情方向或价格方向不够明确。"},
}


def _agent_snapshot_news_state(*, with_meta: bool = True) -> dict:
    """构造 news_agent step 输出（含 snapshot evidence 条目），模拟真实生产路径。

    with_meta=True: snapshot 条目带 meta.snapshot 结构化 dict（NewsAgent 正常路径）
    with_meta=False: snapshot 条目只有文本（meta 丢失时的兜底，走正则解析）
    """
    snapshot_evidence = {
        "text": _SNAPSHOT_TEXT,
        "source": "news_sentiment_snapshot",
        "url": None,
        "timestamp": "2026-06-02T10:00:00",
        "confidence": 0.6,
    }
    if with_meta:
        snapshot_evidence["meta"] = {"snapshot": _SNAPSHOT_DICT}

    return {
        "query": "拉几条 AAPL 新闻",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "operation": {"name": "fetch"},
        "tasks": [
            {"id": "task_1", "subject_type": "company", "tickers": ["AAPL"], "operation": {"name": "fetch"}}
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "agent", "name": "news_agent", "inputs": {"ticker": "AAPL"}},
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {
                    "output": {
                        "agent_name": "news_agent",
                        "summary": "AAPL 舆情分析",
                        "evidence": [
                            {
                                "text": "Apple Q2 earnings beat expectations",
                                "source": "Reuters",
                                "url": "https://example.com/aapl-earnings",
                                "timestamp": "2026-05-30",
                            },
                            {
                                "text": "Apple unveils product launch",
                                "source": "CNBC",
                                "url": "https://example.com/aapl-launch",
                                "timestamp": "2026-05-29",
                            },
                            snapshot_evidence,
                        ],
                    }
                }
            }
        },
    }


def test_snapshot_item_not_rendered_as_news():
    """快照条目（source=news_sentiment_snapshot）不出现在新闻列表里。"""
    md = _render_chat(_agent_snapshot_news_state())
    # 快照文本的特征片段绝不能作为新闻条目渲染
    assert "整体舆情: bullish" not in md
    assert "news_sentiment_snapshot" not in md
    assert "正/负/中占比" not in md
    # 真实新闻还在
    assert "Apple Q2 earnings beat expectations" in md


def test_full_snapshot_preferred_over_light():
    """有完整快照时标题行用它的情绪数据（偏多 +0.10），不是"样本不足"。"""
    md = _render_chat(_agent_snapshot_news_state())
    # 完整快照 sample_size=8 -> 显示偏多 + 平均分，不是"情绪样本不足"
    assert "情绪样本不足" not in md
    assert "偏多" in md
    assert "+0.10" in md
    # 催化区块用完整快照真实数量（3 条），不是"未识别到催化事件"
    assert "未识别到催化事件" not in md
    assert "WWDC Key Catalyst" in md


def test_snapshot_text_parsing():
    """meta 丢失时从快照文本正则提取数值（平均分/占比/催化数/趋势）。"""
    from backend.graph.nodes.chat_renderer import _parse_snapshot_text

    parsed = _parse_snapshot_text(_SNAPSHOT_TEXT)
    assert parsed is not None
    bias = parsed.get("sentiment_bias") or {}
    assert bias.get("label") == "bullish"
    assert abs(float(bias.get("average_score")) - 0.10) < 1e-6
    # 占比 25%/12%/62% -> 0.25/0.12/0.62
    assert abs(float(bias.get("positive_ratio")) - 0.25) < 1e-6
    assert abs(float(bias.get("negative_ratio")) - 0.12) < 1e-6
    assert abs(float(bias.get("neutral_ratio")) - 0.62) < 1e-6
    # sample_size 从"新闻 3 条"提取 -> >0（让标题行不显示"样本不足"）
    assert int(bias.get("sample_size") or 0) >= 3
    # 催化数 3 个
    assert int((parsed.get("catalyst_events") or {}).get("count") or 0) == 3
    # 趋势 deteriorating
    assert (parsed.get("sentiment_trend") or {}).get("direction") == "deteriorating"


def test_snapshot_text_only_fallback_renders_real_sentiment():
    """meta 丢失（只有快照文本）时，正则解析兜底仍能渲染真实情绪，不退回样本不足。"""
    md = _render_chat(_agent_snapshot_news_state(with_meta=False))
    assert "整体舆情: bullish" not in md  # 快照文本不当新闻
    assert "情绪样本不足" not in md       # 正则解析出 sample_size>0
    assert "偏多" in md
    assert "+0.10" in md
