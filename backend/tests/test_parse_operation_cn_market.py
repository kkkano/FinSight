# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.nodes.parse_operation import parse_operation


def test_parse_operation_cn_market_keyword_hits_cn_market():
    result = parse_operation(
        {
            "query": "northbound fund flow for A-share today",
            "subject": {"subject_type": "company", "tickers": ["600519.SH"]},
        }
    )
    op = result.get("operation") or {}
    assert op.get("name") == "cn_market"
