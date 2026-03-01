# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.nodes.parse_operation import parse_operation


def test_parse_operation_screen_keyword_hits_screen():
    result = parse_operation(
        {
            "query": "screen US stocks by market cap",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        }
    )
    op = result.get("operation") or {}
    assert op.get("name") == "screen"
