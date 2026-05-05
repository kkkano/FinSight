# -*- coding: utf-8 -*-
from backend.graph.nodes.alert_extractor import alert_extractor


def test_alert_extractor_prefers_subject_ticker_over_active_symbol():
    state = {
        "query": "涨到 12 元提醒我",
        "subject": {"tickers": ["000001.SZ"]},
        "ui_context": {"active_symbol": "AAPL"},
    }
    result = alert_extractor(state)
    assert result["alert_valid"] is True
    params = result["alert_params"]
    assert params["ticker"] == "000001.SZ"
    assert params["alert_mode"] == "price_target"
    assert params["price_target"] == 12.0


def test_alert_extractor_falls_back_to_active_symbol():
    state = {
        "query": "跌到 8 元提醒我",
        "subject": {"tickers": []},
        "ui_context": {"active_symbol": "000001.sz"},
    }
    result = alert_extractor(state)
    assert result["alert_valid"] is True
    params = result["alert_params"]
    assert params["ticker"] == "000001.SZ"
    assert params["direction"] == "below"


def test_alert_extractor_under_price_target_phrase():
    state = {
        "query": "AAPL 跌破 180 的时候提醒我",
        "subject": {"tickers": ["AAPL"]},
        "ui_context": {},
    }
    result = alert_extractor(state)
    assert result["alert_valid"] is True
    params = result["alert_params"]
    assert params["alert_mode"] == "price_target"
    assert params["price_target"] == 180.0
    assert params["direction"] == "below"
    assert "remaining_query" not in params


def test_alert_extractor_preserves_compound_followup_text():
    state = {
        "query": "TSLA 跌破 180 提醒我，顺便说说最近新闻。",
        "subject": {"tickers": ["TSLA"]},
        "ui_context": {},
    }
    result = alert_extractor(state)
    assert result["alert_valid"] is True
    params = result["alert_params"]
    assert params["alert_mode"] == "price_target"
    assert params["remaining_query"] == "说说最近新闻"


def test_alert_extractor_missing_trigger_prompt_is_natural():
    state = {
        "query": "AAPL 提醒我",
        "subject": {"tickers": ["AAPL"]},
        "ui_context": {},
    }
    result = alert_extractor(state)
    assert result["alert_valid"] is False
    markdown = (result.get("artifacts") or {}).get("draft_markdown") or ""
    assert "问题：" not in markdown
    assert "缺少提醒阈值" in markdown


def test_alert_extractor_missing_ticker_returns_clarify():
    state = {
        "query": "涨到 20 元提醒我",
        "subject": {"tickers": []},
        "ui_context": {},
    }
    result = alert_extractor(state)
    assert result["alert_valid"] is False
    clarify = result.get("clarify") or {}
    assert clarify.get("needed") is True


def test_alert_extractor_pct_mode():
    state = {
        "query": "AAPL 涨跌超过 3% 提醒我",
        "subject": {"tickers": ["AAPL"]},
        "ui_context": {},
    }
    result = alert_extractor(state)
    assert result["alert_valid"] is True
    params = result["alert_params"]
    assert params["alert_mode"] == "price_change_pct"
    assert params["price_threshold"] == 3.0
