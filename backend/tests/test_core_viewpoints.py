# -*- coding: utf-8 -*-
"""Tests for _build_core_viewpoints and _extract_headline in report_builder."""

from backend.graph.report_builder import (
    _build_core_viewpoints,
    _extract_headline,
    build_report_payload,
)


# ---------------------------------------------------------------------------
#  _extract_headline unit tests
# ---------------------------------------------------------------------------

def test_extract_headline_chinese_period():
    """First sentence ending with Chinese period is extracted correctly."""
    text = "苹果公司股价上涨5.3%，创历史新高。后续走势需关注财报发布。"
    headline = _extract_headline(text)
    assert headline == "苹果公司股价上涨5.3%，创历史新高。"


def test_extract_headline_english_period():
    """First sentence ending with English period is extracted correctly."""
    text = "AAPL rose 5.3% to a new all-time high. Further upside depends on earnings."
    headline = _extract_headline(text)
    assert headline == "AAPL rose 5.3% to a new all-time high."


def test_extract_headline_newline_split():
    """First line before newline is extracted as headline."""
    text = "宏观环境总体稳定\n美联储维持利率不变，市场预期年内降息两次。"
    headline = _extract_headline(text)
    assert headline == "宏观环境总体稳定"


def test_extract_headline_truncation():
    """Headline exceeding 120 chars is truncated with ellipsis."""
    long_sentence = "这是一个非常非常长的句子" * 20 + "。结束。"
    headline = _extract_headline(long_sentence)
    assert len(headline) <= 121  # 120 + '…'
    assert headline.endswith("…")


def test_extract_headline_empty_summary():
    """Empty or whitespace-only summary returns placeholder."""
    assert _extract_headline("") == "（无摘要）"
    assert _extract_headline("   ") == "（无摘要）"
    assert _extract_headline("  \n  ") == "（无摘要）"


def test_extract_headline_strips_markdown_bullets():
    """Leading markdown bullets/numbering are stripped."""
    text = "- 技术指标显示超买信号。RSI高于70。"
    headline = _extract_headline(text)
    assert not headline.startswith("-")
    assert "技术指标显示超买信号。" in headline


# ---------------------------------------------------------------------------
#  _build_core_viewpoints unit tests
# ---------------------------------------------------------------------------

def _make_agent_summary(
    agent_name: str,
    title: str = "",
    status: str = "success",
    summary: str = "默认摘要内容。第二句话。",
    confidence: float = 0.75,
    data_sources: list | None = None,
    evidence_full: list | None = None,
    order: int = 1,
) -> dict:
    return {
        "agent_name": agent_name,
        "title": title or agent_name,
        "order": order,
        "status": status,
        "summary": summary,
        "confidence": confidence,
        "data_sources": data_sources or ["yahoo_finance"],
        "evidence_full": evidence_full or [{"text": "evidence"}],
        "raw_output": {},
        "trace_full": [],
    }


def test_build_core_viewpoints_normal():
    """3 success agents produce 3 viewpoints with correct fields."""
    summaries = [
        _make_agent_summary("price_agent", "价格分析", order=1,
                            summary="苹果股价上涨5%。盘后交易平稳。",
                            confidence=0.8, data_sources=["yahoo_finance"]),
        _make_agent_summary("technical_agent", "技术分析", order=2,
                            summary="RSI处于超买区间。MACD金叉确认。",
                            confidence=0.7, data_sources=["yahoo_finance", "tradingview"]),
        _make_agent_summary("news_agent", "新闻分析", order=3,
                            summary="最新消息：苹果发布新产品。市场反应积极。",
                            confidence=0.65, data_sources=["newsapi"]),
    ]

    viewpoints = _build_core_viewpoints(summaries)

    assert len(viewpoints) == 3
    assert viewpoints[0]["agent_name"] == "price_agent"
    assert viewpoints[1]["agent_name"] == "technical_agent"
    assert viewpoints[2]["agent_name"] == "news_agent"

    for vp in viewpoints:
        assert "headline" in vp
        assert "detail" in vp
        assert "confidence" in vp
        assert "data_sources" in vp
        assert "evidence_count" in vp
        assert vp["status"] == "success"
        assert 0.0 <= vp["confidence"] <= 1.0


def test_build_core_viewpoints_mixed_status():
    """Only success agents are included; error and not_run are filtered out."""
    summaries = [
        _make_agent_summary("price_agent", "价格分析", status="success", order=1),
        _make_agent_summary("news_agent", "新闻分析", status="error", order=2),
        _make_agent_summary("technical_agent", "技术分析", status="not_run", order=3),
        _make_agent_summary("macro_agent", "宏观分析", status="success", order=4),
    ]

    viewpoints = _build_core_viewpoints(summaries)

    assert len(viewpoints) == 2
    names = [vp["agent_name"] for vp in viewpoints]
    assert "price_agent" in names
    assert "macro_agent" in names
    assert "news_agent" not in names
    assert "technical_agent" not in names


def test_build_core_viewpoints_all_failed():
    """When all agents fail, returns empty list (frontend falls back to summary)."""
    summaries = [
        _make_agent_summary("price_agent", status="error", order=1),
        _make_agent_summary("news_agent", status="not_run", order=2),
    ]

    viewpoints = _build_core_viewpoints(summaries)
    assert viewpoints == []


def test_build_core_viewpoints_empty_summary():
    """Agent with empty summary gets '（无摘要）' headline."""
    summaries = [
        _make_agent_summary("price_agent", "价格分析", summary="", order=1),
    ]

    viewpoints = _build_core_viewpoints(summaries)
    assert len(viewpoints) == 1
    assert viewpoints[0]["headline"] == "（无摘要）"


def test_build_core_viewpoints_headline_extraction():
    """Headline is correctly extracted from first sentence."""
    summaries = [
        _make_agent_summary(
            "fundamental_agent", "基本面分析", order=1,
            summary="苹果公司Q3营收同比增长12%。毛利率提升至46.2%。净利润超市场预期8%。"
        ),
    ]

    viewpoints = _build_core_viewpoints(summaries)
    assert len(viewpoints) == 1
    assert viewpoints[0]["headline"] == "苹果公司Q3营收同比增长12%。"


def test_build_core_viewpoints_preserves_order():
    """Viewpoints preserve the original agent_summaries order."""
    summaries = [
        _make_agent_summary("macro_agent", "宏观分析", order=5),
        _make_agent_summary("price_agent", "价格分析", order=1),
        _make_agent_summary("technical_agent", "技术分析", order=3),
    ]

    viewpoints = _build_core_viewpoints(summaries)
    names = [vp["agent_name"] for vp in viewpoints]
    assert names == ["macro_agent", "price_agent", "technical_agent"]


# ---------------------------------------------------------------------------
#  Integration test: build_report_payload includes core_viewpoints
# ---------------------------------------------------------------------------

def test_build_report_payload_includes_core_viewpoints():
    """Report payload contains core_viewpoints field with correct structure."""
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["TSLA"]},
        "policy": {
            "allowed_agents": ["price_agent", "news_agent"],
        },
        "plan_ir": {
            "steps": [
                {"kind": "agent", "name": "price_agent", "id": "step_price"},
                {"kind": "agent", "name": "news_agent", "id": "step_news"},
            ]
        },
        "artifacts": {
            "draft_markdown": "## TSLA 分析\n\n基本信息。\n",
            "evidence_pool": [],
            "step_results": {
                "step_price": {
                    "output": {
                        "summary": "特斯拉股价上涨3.2%。交易量放大。",
                        "confidence": 0.82,
                        "data_sources": ["yahoo_finance"],
                        "evidence": [{"text": "price data", "source": "yf"}],
                    }
                },
                "step_news": {
                    "output": {
                        "summary": "特斯拉宣布新工厂计划。市场反应正面。",
                        "confidence": 0.7,
                        "data_sources": ["newsapi"],
                        "evidence": [{"text": "news item", "source": "newsapi"}],
                    }
                },
            },
            "errors": [],
            "render_vars": {},
        },
        "trace": {},
    }

    report = build_report_payload(state=state, query="分析TSLA", thread_id="t-cv")
    assert isinstance(report, dict)

    # core_viewpoints must exist
    cvs = report.get("core_viewpoints")
    assert isinstance(cvs, list)
    assert len(cvs) == 2

    # Verify structure
    for cv in cvs:
        assert "agent_name" in cv
        assert "title" in cv
        assert "headline" in cv
        assert "detail" in cv
        assert "confidence" in cv
        assert "evidence_count" in cv
        assert cv["status"] == "success"

    # summary field still exists (backward compat)
    assert "summary" in report
    assert isinstance(report["summary"], str)


def test_build_report_payload_core_viewpoints_empty_when_no_success():
    """When no agents succeed, core_viewpoints is an empty list."""
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": ["price_agent"]},
        "plan_ir": {"steps": []},
        "artifacts": {
            "draft_markdown": "## AAPL\n\n",
            "evidence_pool": [],
            "step_results": {},
            "errors": [],
            "render_vars": {},
        },
        "trace": {},
    }

    report = build_report_payload(state=state, query="分析AAPL", thread_id="t-empty")
    assert isinstance(report, dict)

    cvs = report.get("core_viewpoints")
    assert isinstance(cvs, list)
    assert len(cvs) == 0

    # summary fallback still works
    assert "summary" in report
