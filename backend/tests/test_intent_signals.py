# -*- coding: utf-8 -*-
"""WP2-T2：关键词单一来源 + QuerySignals 提取。"""
import importlib


def test_hints_have_single_source():
    ur = importlib.import_module("backend.graph.nodes.understand_request")
    kw = importlib.import_module("backend.graph.intent.keywords")
    # identity 断言：消费方与 keywords 是同一对象，不是两份拷贝
    assert ur._TECHNICAL_HINTS is kw._TECHNICAL_HINTS
    assert ur._MACRO_HINTS is kw._MACRO_HINTS
    assert ur._THEME_HINTS is kw._THEME_HINTS
    assert ur._NON_ASSET_TOKENS is kw._NON_ASSET_TOKENS


def test_extract_signals_basic():
    from backend.graph.intent.signals import extract_signals

    s = extract_signals("对比 AAPL 和 MSFT 的估值，顺便看下美联储利率")
    assert set(s.tickers) >= {"AAPL", "MSFT"}
    assert s.has_macro is True
    assert s.is_casual is False
    assert s.has_financial_intent is True


def test_extract_signals_url_stripped_before_tickers():
    from backend.graph.intent.signals import extract_signals

    s = extract_signals("总结 https://example.com/CSV-report 的要点")
    assert s.urls == ["https://example.com/CSV-report"]
    # URL 内的大写词不得被当作 ticker
    assert "CSV" not in s.tickers


def test_extract_signals_empty():
    from backend.graph.intent.signals import extract_signals

    s = extract_signals("")
    assert s.tickers == [] and s.urls == [] and s.is_casual is False
