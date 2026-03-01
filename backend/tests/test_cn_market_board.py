# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.tools import cn_market_board


class _DummyResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_limit_board_parses_rows(monkeypatch):
    def _fake_get(_url: str, params: dict, timeout: int, headers: dict):
        return _DummyResponse(
            200,
            {"data": {"diff": [{"f12": "000001", "f14": "平安银行", "f2": "12.30", "f3": "1.2", "f8": "3.5", "f10": "1.1", "f62": "500"}]}},
        )

    monkeypatch.setattr(cn_market_board, "_http_get", _fake_get)

    result = cn_market_board.fetch_limit_board(limit=20)

    assert result["success"] is True
    assert result["count"] == 1
    assert result["items"][0]["symbol"] == "000001"
    assert result["items"][0]["last_price"] == 12.3


def test_fetch_lhb_parses_rows(monkeypatch):
    def _fake_get(_url: str, params: dict, timeout: int, headers: dict):
        return _DummyResponse(
            200,
            {
                "result": {
                    "data": [
                        {
                            "SECURITY_CODE": "002594",
                            "SECURITY_NAME_ABBR": "比亚迪",
                            "TRADE_DATE": "2026-02-28",
                            "CLOSE_PRICE": "200",
                            "CHANGE_RATE": "5.0",
                            "NET_BUY_AMT": "1000000",
                            "BUY_AMT": "2000000",
                            "SELL_AMT": "1000000",
                            "EXPLAIN": "日涨幅偏离值达7%",
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(cn_market_board, "_http_get", _fake_get)

    result = cn_market_board.fetch_lhb(limit=20)

    assert result["success"] is True
    assert result["count"] == 1
    assert result["items"][0]["symbol"] == "002594"
    assert result["items"][0]["change_percent"] == 5.0
