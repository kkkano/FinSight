# -*- coding: utf-8 -*-
"""12 条典型 query 的金样快照（WP2 Task 0）。"""
import pytest

from .conftest import assert_matches_snapshot, run_pipeline_deterministic

GOLDEN_QUERIES = {
    "single_price": "AAPL 现在多少钱",
    "single_report": "给我一份 NVDA 的投资分析",
    "compare": "对比 AAPL 和 MSFT 的估值",
    "multi_question": "对比 AAPL 和 MSFT 的估值，另外美联储下次议息是什么时候",
    "macro_only": "美国 CPI 最近走势怎么样",
    "news_impact": "TSLA 最近的新闻对股价有什么影响",
    "greeting": "你好",
    "vague_no_subject": "帮我分析一下",
    "url_doc": "总结一下 https://example.com/a-16k-filing 的要点",
    "alert": "AAPL 涨到 250 提醒我",
    "portfolio_no_context": "我的持仓该怎么调仓",
    "cn_ticker": "600036 走势如何",
}


@pytest.mark.parametrize("name", sorted(GOLDEN_QUERIES))
def test_golden(name, deterministic_env):
    payload = run_pipeline_deterministic(GOLDEN_QUERIES[name])
    assert_matches_snapshot(name, payload)
