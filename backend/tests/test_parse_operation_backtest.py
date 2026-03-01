# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.nodes.parse_operation import parse_operation


def test_parse_operation_backtest_keyword_hits_backtest():
    result = parse_operation(
        {
            "query": "backtest MACD strategy on AAPL",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        }
    )
    op = result.get("operation") or {}
    assert op.get("name") == "backtest"
