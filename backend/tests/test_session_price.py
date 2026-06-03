# -*- coding: utf-8 -*-
"""交易时段感知价格快照测试（session_price）。

覆盖：
- 盘前时段：Yahoo v8 chart 含盘前成交点 → 用盘前价，price_basis="pre_market"
- 盘前时段：无盘前数据 → 回退常规价，price_basis="regular_fallback"（诚实标注）
- 盘后时段：含盘后成交点 → 用盘后价，price_basis="post_market"
- 常规时段：用常规价，price_basis="regular"
- 常规价也拿不到 → 返回 None
"""

from __future__ import annotations

from backend.services import session_price
from backend.services.alert_scheduler import PriceSnapshot
from backend.services.session_price import fetch_session_aware_price_snapshot


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _chart_payload(pre_start, pre_end, points, previous_close):
    """构造 Yahoo v8 chart 返回：currentTradingPeriod.pre 窗口 + timestamp/close。

    points: list[(ts, close)]
    """
    timestamps = [p[0] for p in points]
    closes = [p[1] for p in points]
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "previousClose": previous_close,
                        "chartPreviousClose": previous_close,
                        "currentTradingPeriod": {
                            "pre": {"start": pre_start, "end": pre_end},
                            "regular": {"start": pre_end, "end": pre_end + 23400},
                            "post": {"start": pre_end + 23400, "end": pre_end + 37800},
                        },
                    },
                    "timestamp": timestamps,
                    "indicators": {"quote": [{"close": closes}]},
                }
            ]
        }
    }


def test_pre_market_uses_pre_price(monkeypatch):
    """盘前窗口内有成交点 → 用最后一个盘前成交价，涨跌幅相对昨收。"""
    # 盘前窗口 [1000, 2000)，最后一个盘前点收盘价 110，昨收 100 → +10%
    payload = _chart_payload(
        pre_start=1000,
        pre_end=2000,
        points=[(1100, 105.0), (1500, 110.0), (2500, 120.0)],  # 2500 落在 regular，不算盘前
        previous_close=100.0,
    )
    monkeypatch.setattr(session_price.requests, "get", lambda *a, **k: _FakeResp(payload))

    snap = fetch_session_aware_price_snapshot("AAPL", "pre_market")
    assert snap is not None
    assert snap.price == 110.0
    assert snap.change_percent == 10.0
    assert snap.market_session == "pre_market"
    assert snap.price_basis == "pre_market"


def test_pre_market_no_data_falls_back_to_regular(monkeypatch):
    """盘前无成交点 → 回退常规价，price_basis=regular_fallback（不冒充盘前价）。"""
    # chart 端点返回但盘前窗口内无有效点（盘前点 close 全 None）
    payload = _chart_payload(
        pre_start=1000,
        pre_end=2000,
        points=[(1100, None), (2500, 130.0)],
        previous_close=100.0,
    )
    monkeypatch.setattr(session_price.requests, "get", lambda *a, **k: _FakeResp(payload))
    monkeypatch.setattr(
        session_price,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=128.0, change_percent=3.5),
    )

    snap = fetch_session_aware_price_snapshot("AAPL", "pre_market")
    assert snap is not None
    assert snap.price == 128.0
    assert snap.change_percent == 3.5
    assert snap.market_session == "pre_market"
    assert snap.price_basis == "regular_fallback"


def test_pre_market_endpoint_failure_falls_back(monkeypatch):
    """chart 端点 401/异常 → 回退常规价，price_basis=regular_fallback。"""
    monkeypatch.setattr(session_price.requests, "get", lambda *a, **k: _FakeResp({}, status=401))
    monkeypatch.setattr(
        session_price,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=200.0, change_percent=-2.0),
    )

    snap = fetch_session_aware_price_snapshot("TSLA", "pre_market")
    assert snap is not None
    assert snap.price == 200.0
    assert snap.price_basis == "regular_fallback"


def test_after_hours_uses_post_price(monkeypatch):
    """盘后窗口内有成交点 → 用盘后价，price_basis=post_market。"""
    pre_end = 2000
    post_start = pre_end + 23400  # = 25400
    post_end = post_start + 14400
    payload = _chart_payload(
        pre_start=1000,
        pre_end=pre_end,
        points=[(post_start + 100, 90.0), (post_start + 500, 88.0)],
        previous_close=100.0,
    )
    monkeypatch.setattr(session_price.requests, "get", lambda *a, **k: _FakeResp(payload))

    snap = fetch_session_aware_price_snapshot("AAPL", "after_hours")
    assert snap is not None
    assert snap.price == 88.0  # 最后一个盘后点
    assert snap.change_percent == -12.0  # (88-100)/100*100
    assert snap.price_basis == "post_market"


def test_regular_uses_regular_price(monkeypatch):
    """常规时段：直接用常规价，price_basis=regular，不打 chart 端点。"""
    def boom(*a, **k):
        raise AssertionError("regular session should not hit yahoo chart pre/post endpoint")

    monkeypatch.setattr(session_price.requests, "get", boom)
    monkeypatch.setattr(
        session_price,
        "fetch_price_snapshot",
        lambda ticker: PriceSnapshot(ticker=ticker, price=150.0, change_percent=1.2),
    )

    snap = fetch_session_aware_price_snapshot("MSFT", "regular")
    assert snap is not None
    assert snap.price == 150.0
    assert snap.change_percent == 1.2
    assert snap.market_session == "regular"
    assert snap.price_basis == "regular"


def test_regular_none_when_no_price(monkeypatch):
    """常规价拿不到 → 返回 None。"""
    monkeypatch.setattr(session_price, "fetch_price_snapshot", lambda ticker: None)
    assert fetch_session_aware_price_snapshot("XXXX", "regular") is None
