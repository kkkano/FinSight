# -*- coding: utf-8 -*-

from backend.dashboard.data_service import fetch_macro_snapshot


def test_fetch_macro_snapshot_parses_fear_greed_and_fred(monkeypatch):
    import backend.tools.macro as macro_tools

    monkeypatch.setattr(
        macro_tools,
        "get_market_sentiment",
        lambda: "CNN Fear & Greed Index: 62 (Greed)",
    )
    monkeypatch.setattr(
        macro_tools,
        "get_fred_data",
        lambda: {
            "fed_rate": 5.25,
            "cpi": 3.2,
            "unemployment": 4.0,
            "gdp_growth": 2.1,
            "treasury_10y": 4.15,
            "yield_spread": -0.25,
            "as_of": "2026-02-18T00:00:00+00:00",
        },
    )

    payload = fetch_macro_snapshot()

    assert payload["status"] == "ok"
    assert payload["fear_greed_index"] == 62.0
    assert payload["fear_greed_label"] == "greed"
    assert payload["fed_rate"] == 5.25
    assert payload["cpi"] == 3.2
    assert payload["unemployment"] == 4.0
    assert payload["as_of"] == "2026-02-18T00:00:00+00:00"


def test_fetch_macro_snapshot_gracefully_handles_tool_failures(monkeypatch):
    import backend.tools.macro as macro_tools

    def _raise_sentiment():
        raise RuntimeError("sentiment down")

    def _raise_fred():
        raise RuntimeError("fred down")

    monkeypatch.setattr(macro_tools, "get_market_sentiment", _raise_sentiment)
    monkeypatch.setattr(macro_tools, "get_fred_data", _raise_fred)

    payload = fetch_macro_snapshot()

    assert payload["status"] == "unavailable"
    assert payload["fear_greed_index"] is None
    assert payload["fed_rate"] is None
    assert isinstance(payload.get("as_of"), str) and payload["as_of"]
