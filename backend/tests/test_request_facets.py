# -*- coding: utf-8 -*-
import asyncio

from backend.graph.request_facets import derive_request_facets
from backend.graph.nodes.understand_request import understand_request


def test_derive_facets_for_earnings_price_impact():
    facets = derive_request_facets(
        query="请问英伟达这个季度财报对股价的影响",
        operation={"name": "earnings_impact", "params": {}},
        subject={"tickers": ["NVDA"]},
    )

    assert facets["asset"] == "NVDA"
    assert facets["primary_task"] == "impact_analysis"
    assert facets["event_type"] == "earnings"
    assert facets["target_metric"] == "stock_price"
    assert set(facets["analysis_need"]) >= {"fundamental", "news", "risk", "price"}


def test_derive_facets_keeps_price_short_path_narrow():
    facets = derive_request_facets(
        query="NVDA 当前价格是多少",
        operation={"name": "price", "params": {}},
        subject={"tickers": ["NVDA"]},
    )

    assert facets["primary_task"] == "price_lookup"
    assert facets["target_metric"] == "stock_price"
    assert facets["analysis_need"] == ["price"]


def test_understand_request_outputs_valuation_facets(monkeypatch):
    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    result = asyncio.run(
        understand_request(
            {
                "query": "NVDA 现在估值贵不贵，和增长匹配吗",
                "ui_context": {},
                "output_mode": "chat",
            }
        )
    )

    assert (result.get("operation") or {}).get("name") == "valuation_sanity"
    assert (result.get("facets") or {}).get("primary_task") == "valuation_analysis"
    assert (result.get("facets") or {}).get("target_metric") == "valuation"
