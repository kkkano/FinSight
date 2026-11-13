"""直接技术工具与既有 Agent 口径及行情元数据的数值回归。"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pandas as pd
import pytest

import backend.langchain_tools as tools
from backend.agents.technical_agent import TechnicalAgent
from backend.services.market_data_gateway import MarketDataGateway, _fetch_yfinance


def _rows():
    rows = []
    for index, day in enumerate(pd.bdate_range("2026-07-13", periods=60)):
        close = 100 + index
        rows.append({"time": day.strftime("%Y-%m-%d"), "open": close - 1, "high": close + 2,
            "low": close - 3, "close": close, "volume": 1000 + index})
    return rows


def _snapshot(monkeypatch, payload):
    monkeypatch.setattr(tools, "_get_stock_historical_data", lambda *args, **kwargs: deepcopy(payload))
    return json.loads(tools.get_technical_snapshot.invoke({"ticker": "9988.HK"}))


def test_daily_snapshot_preserves_currency_and_matches_agent_indicators_and_range_levels(monkeypatch):
    rows = _rows()
    rows[0]["low"] = 1  # 窗口之外的旧低点不得冒领近期支撑。
    payload = _snapshot(monkeypatch, {"kline_data": rows, "currency": "HKD", "source": "fixture",
        "interval": "1d", "source_timestamp": rows[-1]["time"], "source_time_precision": "date",
        "source_url": "https://example.com/history", "source_timezone": "Asia/Hong_Kong"})
    existing = TechnicalAgent(None, None)._compute_indicators(rows)
    assert payload["support"] == 137
    assert payload["resistance"] == 161
    assert payload["support"] == existing["support"]
    assert payload["resistance"] == existing["resistance"]
    assert payload["rsi14"] == existing["rsi"] == 100
    assert payload["macd"] == pytest.approx(existing["macd"])
    assert payload["macd"] == pytest.approx(6.866964287009332)
    assert payload["macd_signal"] == pytest.approx(6.804975589431558)
    assert payload["macd_signal"] == pytest.approx(existing["signal"])
    assert payload["macd_hist"] == pytest.approx(existing["hist"])
    assert payload["ma20"] == 149.5
    assert payload["trend"] == "uptrend"
    assert payload["frequency"] == "daily" and payload["interval"] == "1d"
    assert payload["currency"] == payload["unit"] == "HKD"
    assert payload["source_time_precision"] == "date"
    assert payload["source_timestamp"] == rows[-1]["time"]
    assert payload["source_timezone"] == "Asia/Hong_Kong"
    assert payload["support_resistance_period_start"] == rows[-20]["time"]
    assert payload["indicator_parameters"]["rsi"]["smoothing"] == "simple_rolling_mean"
    assert payload["structured_data"]["support"] == 137


@pytest.mark.parametrize("field", ["open", "high", "low"])
def test_missing_ohlc_preserves_computable_rsi_but_does_not_make_up_levels(monkeypatch, field):
    rows = _rows()
    del rows[-1][field]
    payload = _snapshot(monkeypatch, {"kline_data": rows})
    assert payload["support"] is None and payload["resistance"] is None
    assert {"support", "resistance", "currency"} <= set(payload["missing_metrics"])
    assert payload["currency"] is None
    assert payload["rsi14"] == 100


def test_invalid_high_low_range_does_not_publish_support_resistance(monkeypatch):
    rows = _rows()
    rows[-1]["high"] = 1
    payload = _snapshot(monkeypatch, {"kline_data": rows, "currency": "CNY"})
    assert payload["support"] is None and payload["resistance"] is None


def test_missing_latest_bar_time_not_borrowed_from_previous_bar(monkeypatch):
    rows = _rows()
    del rows[-1]["time"]
    payload = _snapshot(monkeypatch, {"kline_data": rows})
    assert payload["as_of"] is None
    assert payload["source_timestamp"] is None
    assert payload["source_time_status"] == "unknown"
    assert "source_time" in payload["missing_metrics"]


@pytest.mark.parametrize("data,error", [
    ({"error": "market_data_unavailable", "kline_data": _rows()}, "market_data_unavailable"),
    ({"interval": "1h", "kline_data": _rows()}, "daily_interval_required"),
    ({"kline_data": _rows()[:10]}, "insufficient_points"),
])
def test_failure_envelope_wrong_interval_and_short_data_not_reported_as_daily_facts(monkeypatch, data, error):
    assert _snapshot(monkeypatch, data)["error"] == error


def test_nan_close_is_unavailable_not_a_nan_indicator(monkeypatch):
    rows = _rows()
    rows[-1]["close"] = float("nan")
    result = _snapshot(monkeypatch, {"kline_data": rows})
    assert result["error"] == "invalid_close_data"


@pytest.mark.parametrize("fail_metadata", [False, True])
def test_yahoo_history_metadata_is_preserved_but_failure_keeps_valid_bars(monkeypatch, fail_metadata):
    import backend.tools.yfinance_client as yfinance_client
    rows = _rows()
    frame = pd.DataFrame(rows).rename(columns={name: name.title() for name in ("open", "high", "low", "close", "volume")})
    frame.index = pd.to_datetime(frame.pop("time"))
    def metadata():
        if fail_metadata:
            raise RuntimeError("fixture metadata unavailable")
        return {"currency": "HKD", "exchangeTimezoneName": "Asia/Hong_Kong"}
    monkeypatch.setattr(yfinance_client, "create_ticker", lambda *args, **kwargs: SimpleNamespace(
        history=lambda **kwargs: frame, get_history_metadata=metadata))
    raw = _fetch_yfinance("9988.HK", "6mo", "1d")
    assert len(raw["kline_data"]) == 60
    assert raw["currency"] == (None if fail_metadata else "HKD")
    assert raw["source_timestamp"] == rows[-1]["time"]
    assert raw["source_time_precision"] == "date"


def test_gateway_keeps_raw_currency_and_source_time_for_direct_snapshot(monkeypatch):
    rows = _rows()
    def source(*args):
        return {"kline_data": rows, "currency": "HKD", "source_timestamp": rows[-1]["time"],
            "source_time_precision": "date", "source_timezone": "Asia/Hong_Kong", "interval": "1d"}
    gateway = MarketDataGateway(providers={"primary": source}, primary_provider="primary",
        secondary_provider=None, trusted_providers={"primary"}, cache_ttl_seconds=0)
    result = gateway.get_kline("9988.HK", period="6mo")
    assert result["currency"] == "HKD"
    assert result["source_timestamp"] == rows[-1]["time"]
    assert _snapshot(monkeypatch, result)["currency"] == "HKD"


def test_failed_primary_metadata_does_not_leak_into_secondary_currency():
    def primary(*args):
        rows = _rows()
        rows[-1]["high"] = 1
        return {"kline_data": rows, "currency": "USD"}
    def secondary(*args):
        return {"kline_data": _rows()}
    gateway = MarketDataGateway(providers={"primary": primary, "secondary": secondary},
        primary_provider="primary", secondary_provider="secondary", trusted_providers={"secondary"}, cache_ttl_seconds=0)
    result = gateway.get_kline("9988.HK")
    assert result["provider"] == "secondary"
    assert result.get("currency") is None


def test_open_daily_bar_is_removed_from_direct_and_agent_indicators(monkeypatch):
    rows = _rows()
    rows.append({"time": "2026-10-08", "open": 200, "high": 2000, "low": 10, "close": 1000, "volume": 5})
    raw = {"kline_data": rows, "currency": "USD", "source": "fixture", "interval": "1d",
           "source_timestamp": "2026-10-08", "observed_at": "2026-10-08T15:00:00Z"}
    monkeypatch.setattr(tools, "_get_stock_historical_data", lambda *args, **kwargs: deepcopy(raw))
    direct = json.loads(tools.get_technical_snapshot.invoke({"ticker": "TSLA"}))
    agent = TechnicalAgent(None, None, SimpleNamespace())
    enriched = agent._enrich_with_side_signals(raw, "TSLA")
    native = agent._compute_indicators(enriched["kline_data"])
    assert direct["close"] == native["close"] == 159
    assert direct["points"] == len(enriched["kline_data"]) == 60
    assert direct["source_timestamp"] == enriched["source_timestamp"] == rows[-2]["time"]
    assert direct["market_session"] == "regular_close"
    assert direct["resistance"] == native["resistance"] == 161


def test_cached_intraday_bar_is_not_relabelled_closed_after_the_bell(monkeypatch):
    from backend.services.market_hours import filter_open_daily_bars
    rows = [{"time": "2026-10-07", "close": 100}, {"time": "2026-10-08", "close": 110}]
    assert filter_open_daily_bars(rows, symbol="TSLA", as_of="2026-10-08T15:00:00Z") == rows[:1]
    assert filter_open_daily_bars(rows, symbol="0700.HK", as_of="2026-10-08T15:00:00Z") == rows
