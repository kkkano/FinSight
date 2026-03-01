# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta

from backend.services import backtest_engine as backtest_engine_module


def _build_series(start_price: float = 100.0, days: int = 120) -> list[dict]:
    rows: list[dict] = []
    price = start_price
    base = datetime(2025, 1, 1)
    for i in range(days):
        price += 0.5
        rows.append({"time": (base + timedelta(days=i)).date().isoformat(), "close": round(price, 2)})
    return rows


def test_backtest_engine_runs_with_primary_historical_source(monkeypatch):
    monkeypatch.setattr(
        backtest_engine_module,
        "get_stock_historical_data",
        lambda ticker, period="5y", interval="1d": {"kline_data": _build_series(), "source": "unit_test_hist"},
    )
    monkeypatch.setattr(backtest_engine_module, "fetch_cn_hk_kline", lambda ticker, limit=1200: [])

    engine = backtest_engine_module.BacktestEngine()
    result = engine.run(ticker="AAPL", strategy="ma_cross", t_plus_one=True)

    assert result["success"] is True
    assert result["source"] == "unit_test_hist"
    assert result["ticker"] == "AAPL"
    assert result["metrics"]["final_equity"] > 0
    assert len(result["equity_curve"]) > 0


def test_backtest_engine_uses_cn_hk_fallback(monkeypatch):
    monkeypatch.setattr(
        backtest_engine_module,
        "get_stock_historical_data",
        lambda ticker, period="5y", interval="1d": {"kline_data": [], "source": "empty"},
    )
    monkeypatch.setattr(backtest_engine_module, "fetch_cn_hk_kline", lambda ticker, limit=1200: _build_series(80.0, 150))

    engine = backtest_engine_module.BacktestEngine()
    result = engine.run(ticker="600519.SH", strategy="macd", market="CN")

    assert result["success"] is True
    assert result["source"] == "eastmoney_kline"
    assert result["period"]["bars"] >= 100


def test_backtest_engine_returns_insufficient_data(monkeypatch):
    monkeypatch.setattr(
        backtest_engine_module,
        "get_stock_historical_data",
        lambda ticker, period="5y", interval="1d": {"kline_data": _build_series(days=10), "source": "short"},
    )
    monkeypatch.setattr(backtest_engine_module, "fetch_cn_hk_kline", lambda ticker, limit=1200: [])

    engine = backtest_engine_module.BacktestEngine()
    result = engine.run(ticker="AAPL", strategy="rsi_mean_reversion")

    assert result["success"] is False
    assert result["error"] == "insufficient_price_data"


def test_backtest_engine_t_plus_one_uses_previous_bar_signal(monkeypatch):
    series = _build_series(days=80)

    monkeypatch.setattr(
        backtest_engine_module,
        "get_stock_historical_data",
        lambda ticker, period="5y", interval="1d": {"kline_data": series, "source": "unit_test_hist"},
    )
    monkeypatch.setattr(backtest_engine_module, "fetch_cn_hk_kline", lambda ticker, limit=1200: [])

    signals = [1] + [0] * (len(series) - 1)

    def _fake_signals(_strategy, closes, params=None):
        return {"name": "unit_test", "signals": signals[: len(closes)], "params": {}}

    monkeypatch.setattr(backtest_engine_module, "build_strategy_signals", _fake_signals)

    engine = backtest_engine_module.BacktestEngine()
    t1_result = engine.run(ticker="AAPL", strategy="ma_cross", t_plus_one=True)
    t0_result = engine.run(ticker="AAPL", strategy="ma_cross", t_plus_one=False)

    t1_buy = next(item for item in t1_result["trades"] if item.get("type") == "buy")
    t0_buy = next(item for item in t0_result["trades"] if item.get("type") == "buy")
    assert t1_buy["time"] == series[1]["time"]
    assert t0_buy["time"] == series[0]["time"]


def test_backtest_engine_cost_and_slippage_reduce_final_equity(monkeypatch):
    series = _build_series(days=120)

    monkeypatch.setattr(
        backtest_engine_module,
        "get_stock_historical_data",
        lambda ticker, period="5y", interval="1d": {"kline_data": series, "source": "unit_test_hist"},
    )
    monkeypatch.setattr(backtest_engine_module, "fetch_cn_hk_kline", lambda ticker, limit=1200: [])

    def _fake_signals(_strategy, closes, params=None):
        return {"name": "unit_test", "signals": [1 for _ in closes], "params": {}}

    monkeypatch.setattr(backtest_engine_module, "build_strategy_signals", _fake_signals)

    engine = backtest_engine_module.BacktestEngine()
    no_cost = engine.run(ticker="AAPL", strategy="ma_cross", t_plus_one=False, fee_bps=0.0, slippage_bps=0.0)
    with_cost = engine.run(ticker="AAPL", strategy="ma_cross", t_plus_one=False, fee_bps=50.0, slippage_bps=50.0)

    assert no_cost["success"] is True
    assert with_cost["success"] is True
    assert with_cost["metrics"]["final_equity"] < no_cost["metrics"]["final_equity"]


def test_backtest_engine_t_plus_one_prevents_same_day_round_trip(monkeypatch):
    series = _build_series(days=90)

    monkeypatch.setattr(
        backtest_engine_module,
        "get_stock_historical_data",
        lambda ticker, period="5y", interval="1d": {"kline_data": series, "source": "unit_test_hist"},
    )
    monkeypatch.setattr(backtest_engine_module, "fetch_cn_hk_kline", lambda ticker, limit=1200: [])

    def _fake_signals(_strategy, closes, params=None):
        return {"name": "unit_test", "signals": [1 if idx % 2 == 0 else 0 for idx, _ in enumerate(closes)], "params": {}}

    monkeypatch.setattr(backtest_engine_module, "build_strategy_signals", _fake_signals)

    engine = backtest_engine_module.BacktestEngine()
    result = engine.run(ticker="AAPL", strategy="ma_cross", t_plus_one=True)

    assert result["success"] is True
    trades = result["trades"]
    for idx in range(1, len(trades)):
        prev_trade = trades[idx - 1]
        curr_trade = trades[idx]
        if prev_trade.get("type") == "buy" and curr_trade.get("type") == "sell":
            assert curr_trade.get("time") != prev_trade.get("time")
