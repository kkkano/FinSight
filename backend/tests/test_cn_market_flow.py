# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.tools import cn_market_flow


class _DummyResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_fund_flow_parses_rows(monkeypatch):
    def _fake_get(_url: str, params: dict, timeout: int, headers: dict):
        return _DummyResponse(
            200,
            {
                "data": {
                    "diff": [
                        {"f12": "600519", "f13": "1", "f14": "贵州茅台", "f2": "1680.5", "f3": "2.15", "f62": "1000", "f184": "3.2"}
                    ]
                }
            },
        )

    monkeypatch.setattr(cn_market_flow, "_http_get", _fake_get)

    result = cn_market_flow.fetch_fund_flow(limit=10)

    assert result["success"] is True
    assert result["count"] == 1
    assert result["items"][0]["symbol"] == "600519.SH"
    assert result["items"][0]["change_percent"] == 2.15


def test_fetch_northbound_empty_payload(monkeypatch):
    def _fake_get(_url: str, params: dict, timeout: int, headers: dict):
        return _DummyResponse(200, {"data": {"diff": []}})

    monkeypatch.setattr(cn_market_flow, "_http_get", _fake_get)

    result = cn_market_flow.fetch_northbound(limit=5)

    assert result["success"] is True
    assert result["count"] == 0
    assert result["items"] == []
