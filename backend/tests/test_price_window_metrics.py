"""窗口计算的离线边界回归。"""
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.tools import price_window


def _history(monkeypatch, closes, *, dates=None, volume=None, metadata=None):
    index = pd.to_datetime(dates) if dates is not None else pd.bdate_range("2026-09-25", periods=len(closes))
    frame = pd.DataFrame({"Close": closes, "High": [value + 1 for value in closes],
        "Low": [value - 1 for value in closes], "Volume": volume or [100] * len(closes)}, index=index)
    calls = []
    def history(**kwargs):
        calls.append(kwargs)
        return frame
    monkeypatch.setattr(price_window, "create_ticker", lambda _: SimpleNamespace(
        history=history, get_history_metadata=lambda: metadata or {"currency": "USD"}))
    return calls


def test_five_sessions_return_uses_six_closes_and_excludes_dividends(monkeypatch):
    calls = _history(monkeypatch, [100, 101, 102, 99, 104, 110])
    result = price_window.get_price_window_metrics("SPY", 5, ["cumulative_return"], "2026-10-04T09:31:00Z")
    assert result["error"] is None
    metric = result["metrics"]["cumulative_return"]
    assert metric["value"] == pytest.approx(.10)
    assert (metric["base_date"], metric["end_date"], metric["intervals"]) == ("2026-09-25", "2026-10-02", 5)
    assert result["source_timestamp"] == "2026-10-02"
    assert result["source_time_precision"] == "date"
    assert not result["dividends_included"]
    assert calls[0]["auto_adjust"] is False
    assert result["structured_data"]["bars"] == result["bars"]


def test_return_missing_sixth_point_is_not_four_interval_five_day_return(monkeypatch):
    _history(monkeypatch, [100, 101, 102, 99, 104], dates=pd.bdate_range("2026-09-28", periods=5))
    result = price_window.get_price_window_metrics("SPY", 5, ["cumulative_return"], "2026-10-04T09:31:00Z")
    assert "cumulative_return" in result["missing_metrics"]
    assert "cumulative_return" not in result["metrics"]


def test_mdd_uses_running_peak_inside_window_not_high_before_it(monkeypatch):
    _history(monkeypatch, [200, 100, 120, 90, 100, 110])
    result = price_window.get_price_window_metrics("GLD", 5, ["max_drawdown"], "2026-10-04T09:31:00Z")
    metric = result["metrics"]["max_drawdown"]
    assert metric["value"] == pytest.approx(-.25)
    assert (metric["peak_close"], metric["trough_close"]) == (120, 90)
    assert (metric["peak_date"], metric["trough_date"]) == ("2026-09-29", "2026-09-30")


def test_in_progress_session_excluded_from_return_and_volume(monkeypatch):
    _history(monkeypatch, [100, 105, 130], dates=["2026-10-01", "2026-10-02", "2026-10-05"], volume=[100, 100, 99999])
    result = price_window.get_price_window_metrics("DELL", 2, ["volume_breakout"], "2026-10-05T18:00:00Z")
    assert result["period_end"] == "2026-10-02"
    metric = result["metrics"]["volume_breakout"]
    assert metric["relative_volume"] == 1
    assert metric["breakout"] and not metric["volume_confirmed"]


def test_crypto_day_finishes_next_utc_midnight(monkeypatch):
    _history(monkeypatch, [100, 90, 200], dates=["2026-10-02", "2026-10-03", "2026-10-04"])
    result = price_window.get_price_window_metrics("ETH-USD", 2, ["max_drawdown"], "2026-10-04T09:31:00Z")
    assert result["period_end"] == "2026-10-03"
    assert result["metrics"]["max_drawdown"]["value"] == pytest.approx(-.10)


def test_provider_early_close_time_can_confirm_today_completed_session(monkeypatch):
    close_at = int(pd.Timestamp("2026-11-27T18:00:00Z").timestamp())
    _history(monkeypatch, [100, 105], dates=["2026-11-25", "2026-11-27"],
        metadata={"currency": "USD", "currentTradingPeriod": {"regular": {"end": close_at}}})
    result = price_window.get_price_window_metrics("SPY", 2, ["max_drawdown"], "2026-11-27T18:01:00Z")
    assert result["period_end"] == "2026-11-27"


def test_missing_currency_is_not_assumed_dollars(monkeypatch):
    _history(monkeypatch, [100, 110], dates=["2026-10-01", "2026-10-02"], metadata={"exchangeName": "OTHER"})
    result = price_window.get_price_window_metrics("SPY", 2, ["max_drawdown"], "2026-10-04T09:31:00Z")
    assert result["currency"] is None
    assert "currency" in result["missing_metrics"]


def test_one_session_return_supported_and_breakout_not_fabricated(monkeypatch):
    _history(monkeypatch, [100, 105], dates=["2026-10-01", "2026-10-02"])
    result = price_window.get_price_window_metrics("SPY", 1, ["cumulative_return", "volume_breakout"], "2026-10-04T09:31:00Z")
    assert result["metrics"]["cumulative_return"]["value"] == pytest.approx(.05)
    assert "volume_breakout" in result["missing_metrics"]


def test_duplicate_date_is_not_an_extra_trading_session(monkeypatch):
    _history(monkeypatch, [100, 110], dates=["2026-10-02", "2026-10-02"])
    result = price_window.get_price_window_metrics("SPY", 2, ["max_drawdown"], "2026-10-04T09:31:00Z")
    assert result["error"] == "duplicate_session"
    assert not result["metrics"]


@pytest.mark.parametrize("dates", [
    ["2026-09-30", "2026-10-01"],
    ["2026-09-30", "2026-10-02"],
])
def test_missing_latest_or_intermediate_session_not_replaced_with_older_bar(monkeypatch, dates):
    _history(monkeypatch, [100, 110], dates=dates)
    result = price_window.get_price_window_metrics("SPY", 2, ["max_drawdown"], "2026-10-04T09:31:00Z")
    assert result["error"] == "insufficient_completed_sessions"
    assert result["missing_session_dates"]
    assert not result["metrics"]


def test_nyse_half_day_and_holiday_apply_even_without_provider_period_metadata(monkeypatch):
    _history(monkeypatch, [100, 105], dates=["2026-11-25", "2026-11-27"])
    result = price_window.get_price_window_metrics("SPY", 2, ["max_drawdown"], "2026-11-27T18:01:00Z")
    assert result["expected_session_dates"] == ["2026-11-25", "2026-11-27"]
    assert result["period_end"] == "2026-11-27"
    assert result["completed_only"] is True


def test_explicit_date_as_of_means_end_of_that_utc_day(monkeypatch):
    _history(monkeypatch, [100, 105], dates=["2026-10-01", "2026-10-02"])
    result = price_window.get_price_window_metrics("SPY", 1, ["cumulative_return"], "2026-10-02")
    assert result["error"] is None
    assert result["period_end"] == "2026-10-02"
    assert result["metrics"]["cumulative_return"]["value"] == pytest.approx(.05)


def test_bad_close_reports_date_and_retains_valid_observations(monkeypatch):
    _history(monkeypatch, [100, 0], dates=["2026-10-01", "2026-10-02"])
    result = price_window.get_price_window_metrics("SPY", 1, ["cumulative_return"], "2026-10-04T09:31:00Z")
    assert result["error"] == "invalid_close_path"
    assert result["invalid_session_date"] == "2026-10-02"
    assert result["invalid_close_reason"] == "nonpositive"
    assert result["bars"][0]["close"] == 100
    assert not result["metrics"]


def test_empty_action_row_does_not_replace_or_duplicate_real_close(monkeypatch):
    _history(monkeypatch, [100, float("nan"), 110], dates=["2026-10-01", "2026-10-02", "2026-10-02"], volume=[100, 0, 100])
    result = price_window.get_price_window_metrics("SPY", 1, ["cumulative_return"], "2026-10-04T09:31:00Z")
    assert result["error"] is None
    assert result["metrics"]["cumulative_return"]["value"] == pytest.approx(.1)
