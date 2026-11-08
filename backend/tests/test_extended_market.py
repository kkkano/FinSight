"""扩展时段与 FINRA 延迟统计的真实字段合同，不调用外部数据服务。"""
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.agent_runtime.analysis import render_chart
from backend.agent_runtime.data import RunData
from backend.tools import extended_market as market


def yahoo(monkeypatch, *, dates=None, volume=None, metadata=None):
    dates = dates or ["2026-11-06 04:00", "2026-11-06 09:25", "2026-11-06 09:30",
                      "2026-11-06 15:55", "2026-11-06 16:00", "2026-11-06 19:55"]
    index = pd.DatetimeIndex(dates, tz="America/New_York")
    frame = pd.DataFrame({"Open": 100.0, "High": 102.0, "Low": 99.0, "Close": 101.0,
                          "Volume": volume if volume is not None else [100] * len(index)}, index=index)
    calls = []

    def history(**kwargs):
        calls.append(kwargs)
        return frame

    monkeypatch.setattr(market, "create_ticker", lambda _: SimpleNamespace(
        history=history, get_history_metadata=lambda: metadata if metadata is not None else {"symbol": "AAPL", "currency": "USD"}))
    return frame, calls


def finra_row(week, kind, *, shares=100.5, trades=12, tier="T1"):
    return {"issueSymbolIdentifier": "AAPL", "issueName": "Apple Inc. Common Stock", "weekStartDate": week,
            "summaryTypeCode": kind, "tierIdentifier": tier, "totalWeeklyShareQuantity": shares,
            "totalWeeklyTradeCount": trades, "lastReportedDate": "2026-10-19",
            "initialPublishedDate": "2026-11-02", "lastUpdateDate": "2026-11-02"}


def finra(monkeypatch, payload, *, status=200):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=status, json=lambda: payload)

    monkeypatch.setattr(market, "_get_no_retry_http_session", lambda: SimpleNamespace(post=post))
    return calls


def test_extended_hours_preserve_all_sessions_and_unknown_provider_delay(monkeypatch):
    _, calls = yahoo(monkeypatch)

    result = market.get_us_extended_hours("AAPL")

    assert result["status"] == "ok"
    assert calls[0]["prepost"] is True and calls[0]["auto_adjust"] is False
    assert [row["session"] for row in result["rows"]] == ["pre_market", "pre_market", "regular", "regular", "after_hours", "after_hours"]
    assert result["rows"][0]["time"] == "2026-11-06T09:00:00+00:00"
    assert result["as_of"] == "2026-11-07T00:55:00+00:00"
    assert result["currency"] == "USD"
    assert result["delayed"] is None and result["delay_status"] == "unknown"


def test_extended_hours_filter_does_not_substitute_regular_bars_or_missing_volume(monkeypatch):
    yahoo(monkeypatch, volume=[None, 0, 100, 100, 100, 100])

    result = market.get_us_extended_hours("AAPL", session="pre_market")

    assert len(result["rows"]) == 2
    assert [row["volume"] for row in result["rows"]] == [None, 0]
    assert result["sessions_present"] == ["pre_market"]


@pytest.mark.parametrize("day,times,expected", [
    ("2026-11-27", ["12:55", "13:00"], ["regular", "after_hours"]),
    ("2026-07-06", ["09:25", "09:30"], ["pre_market", "regular"]),
])
def test_session_classification_uses_early_close_and_daylight_saving_calendar(monkeypatch, day, times, expected):
    yahoo(monkeypatch, dates=[f"{day} {clock}" for clock in times])

    result = market.get_us_extended_hours("AAPL")

    assert [row["session"] for row in result["rows"]] == expected
    if day == "2026-07-06":
        assert result["rows"][0]["time"] == "2026-07-06T13:25:00+00:00"


def test_missing_session_returns_unavailable_instead_of_regular_data(monkeypatch):
    yahoo(monkeypatch, dates=["2026-11-06 09:30", "2026-11-06 09:35"])

    result = market.get_us_extended_hours("AAPL", session="after_hours")

    assert result["status"] == "unavailable" and result["rows"] == []
    assert result["error"] == "extended_hours_session_empty"


def test_provider_declared_delay_is_preserved_and_unknown_currency_is_not_guessed(monkeypatch):
    yahoo(monkeypatch, metadata={"exchangeDataDelayedBy": 15})

    result = market.get_us_extended_hours("AAPL")

    assert result["delayed"] is True and result["delay_minutes"] == 15
    assert result["currency"] is None


def test_invalid_ohlc_is_excluded_without_filling_prices(monkeypatch):
    frame, _ = yahoo(monkeypatch)
    frame.iloc[0, frame.columns.get_loc("High")] = 1

    result = market.get_us_extended_hours("AAPL")

    assert result["invalid_bars_excluded"] == 1
    assert len(result["rows"]) == 5
    assert result["rows"][0]["time"] == "2026-11-06T14:25:00+00:00"


def test_wrong_source_symbol_is_unavailable(monkeypatch):
    yahoo(monkeypatch, metadata={"symbol": "MSFT", "currency": "USD"})
    assert market.get_us_extended_hours("AAPL")["error"] == "extended_hours_symbol_mismatch"


@pytest.mark.parametrize("kwargs", [
    {"ticker": "0700.HK"}, {"ticker": "https://example.com"},
    {"ticker": "AAPL", "interval": "1d"}, {"ticker": "AAPL", "interval": "1m", "period": "1mo"},
])
def test_unsupported_windows_or_symbols_are_rejected_before_provider_calls(monkeypatch, kwargs):
    def unexpected(*_):
        pytest.fail("参数无效时不应访问供应商")
    monkeypatch.setattr(market, "create_ticker", unexpected)

    with pytest.raises(ValueError):
        market.get_us_extended_hours(**kwargs)


def test_finra_uses_symbol_totals_and_preserves_fractional_shares_and_publication_dates(monkeypatch):
    calls = finra(monkeypatch, [
        finra_row("2026-10-12", "OTC_W_SMBL", shares=61665665.455451, trades=1427252),
        finra_row("2026-10-05", "ATS_W_SMBL", shares=26620276, trades=501406),
        finra_row("2026-10-12", "ATS_W_SMBL", shares=34912671, trades=620539),
    ])

    result = market.get_finra_otc_activity("AAPL", weeks=2)

    assert result["status"] == "ok"
    assert calls[0][1]["json"]["domainFilters"] == [{"fieldName": "summaryTypeCode", "values": ["ATS_W_SMBL", "OTC_W_SMBL"]}]
    assert [row["date"] for row in result["rows"]] == ["2026-10-05", "2026-10-12"]
    assert result["rows"][-1]["non_ats_share_volume"] == pytest.approx(61665665.455451)
    assert result["rows"][-1]["ats_trade_count"] == 620539
    assert result["rows"][0]["non_ats_share_volume"] is None
    assert result["rows"][0]["missing_venues"] == ["non_ats"]
    assert result["rows"][-1]["venue_metadata"]["non_ats"]["last_reported_date"] == "2026-10-19"
    assert result["rows"][-1]["venue_metadata"]["ats"]["published_date"] == "2026-11-02"
    assert result["delayed"] is True and result["as_of"] == "2026-10-12"
    assert result["currency"] is None


def test_finra_activity_does_not_claim_net_flow_or_realtime_dark_pool_quotes(monkeypatch):
    finra(monkeypatch, [finra_row("2026-10-12", "ATS_W_SMBL", tier="T2")])

    result = market.get_finra_otc_activity("AAPL")

    assert result["unavailable_metrics"]["net_money_flow"]["status"] == "unavailable"
    assert result["unavailable_metrics"]["realtime_dark_pool_quotes"]["status"] == "unavailable"
    assert result["rows"][0]["venue_metadata"]["ats"]["nominal_publication_delay_weeks"] == 4
    assert not {"net_inflow", "net_outflow", "bid", "ask"}.intersection(result["rows"][0])


@pytest.mark.parametrize("payload", [
    [finra_row("2026-10-12", "ATS_W_SMBL_FIRM")],
    [finra_row("2026-10-12", "ATS_W_SMBL"), finra_row("2026-10-12", "ATS_W_SMBL")],
    [finra_row("2026-10-12", "ATS_W_SMBL", shares=float("nan"))],
    [{**finra_row("2026-10-12", "ATS_W_SMBL"), "issueSymbolIdentifier": "MSFT"}],
])
def test_finra_rejects_firm_detail_duplicate_totals_and_invalid_metrics(monkeypatch, payload):
    finra(monkeypatch, payload)

    result = market.get_finra_otc_activity("AAPL")

    assert result["status"] == "unavailable" and result["rows"] == []


def test_finra_provider_refusal_is_reported_without_substitute_data(monkeypatch):
    finra(monkeypatch, {"message": "provider detail"}, status=403)

    result = market.get_finra_otc_activity("AAPL")

    assert result["status"] == "unavailable" and result["http_status"] == 403
    assert result["rows"] == []
    assert "provider detail" not in str(result)


def test_both_tool_outputs_can_be_rendered_directly_without_compute_worker(monkeypatch):
    yahoo(monkeypatch)
    finra(monkeypatch, [finra_row("2026-10-12", "ATS_W_SMBL"), finra_row("2026-10-12", "OTC_W_SMBL")])
    data = RunData("fixture-user", "fixture-session", "fixture-run", "检查盘后与场外成交")
    history = market.get_us_extended_hours("AAPL")
    activity = market.get_finra_otc_activity("AAPL")

    history_ref = data.record("get_us_extended_hours", {"ticker": "AAPL"}, history)
    activity_ref = data.record("get_finra_otc_activity", {"ticker": "AAPL"}, activity)
    candle = render_chart(data, history_ref, "扩展时段", "candlestick", "date", [{"field": "close", "unit": "USD"}])
    bars = render_chart(data, activity_ref, "场外周成交量", "bar", "date", [{"field": "ats_share_volume"}, {"field": "non_ats_share_volume"}])

    assert len(candle["data"]["rows"]) == 6
    assert bars["data"]["rows"][0]["ats_share_volume"] == 100.5
    assert bars["source_refs"] and candle["source_refs"]
