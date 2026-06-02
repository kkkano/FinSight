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
