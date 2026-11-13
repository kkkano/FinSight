"""旁路只观察同一次已完成调用，不改变生产者或被测工具的返回值。"""
from concurrent.futures import ThreadPoolExecutor
import json

import httpx
import numpy as np
import pandas as pd
import pytest
import requests
from yfinance.base import TickerBase

from backend.services.market_data_gateway import MarketDataGateway
from .capture import capture_producers, install_capture_hooks
from .tapes import ToolTape


def test_tape_stores_same_call_raw_and_structured_without_refetch(tmp_path, monkeypatch):
    calls = []
    structured = {"status": "ok", "data": {"price": 42.0, "currency": "USD"}}
    def quote(_gateway, symbol):
        calls.append(symbol)
        return structured
    monkeypatch.setattr(MarketDataGateway, "get_quote", quote)
    gateway = object.__new__(MarketDataGateway)
    def legacy(args):
        result = gateway.get_quote(args["ticker"])
        assert result is structured
        return "Price: " + str(result["data"]["price"])
    tape = ToolTape(tmp_path, "record")
    with install_capture_hooks():
        assert tape.invoke("get_stock_price", {"ticker": "AAPL"}, legacy) == "Price: 42.0"
        assert tape.invoke("get_stock_price", {"ticker": "AAPL"}, legacy) == "Price: 42.0"
    assert calls == ["AAPL"]
    record = tape.records()[0]
    assert record["raw_output"] == "Price: 42.0"
    assert record["producer_capture"]["status"] == "captured"
    assert record["producer_outputs"][0]["data"] == structured
    assert record["producer_outputs"][0]["arguments"] == {"symbol": "AAPL"}
    assert MarketDataGateway.get_quote is quote


def test_returned_yfinance_frame_and_numpy_values_are_serialized_as_data(monkeypatch):
    frame = pd.DataFrame({"Close": [np.float64(42), np.nan]}, index=pd.date_range("2026-11-01", periods=2, tz="UTC"))
    info = {"marketCap": np.int64(12345), "time": pd.Timestamp("2026-11-01T00:00Z")}
    monkeypatch.setattr(TickerBase, "history", lambda *_a, **_k: frame)
    monkeypatch.setattr(TickerBase, "get_info", lambda *_a, **_k: info)
    ticker = object.__new__(TickerBase)
    ticker.ticker = "AAPL"
    with install_capture_hooks(), capture_producers() as captured:
        assert ticker.history(period="1y", interval="1d") is frame
        assert ticker.get_info() is info
    outputs = captured.snapshot()
    assert outputs[0]["data_format"] == "dataframe_split"
    assert outputs[0]["data"]["columns"] == ["Close"]
    assert outputs[0]["data"]["data"] == [[42.0], [None]]
    assert outputs[0]["data"]["index"][0] == "2026-11-01T00:00:00+00:00"
    assert outputs[0]["arguments"] == {"ticker": "AAPL", "period": "1y", "interval": "1d"}
    assert outputs[1]["data"]["marketCap"] == 12345


def test_response_capture_excludes_credentials_headers_and_query(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_API_KEY", "fixture-secret-value")
    response = httpx.Response(200, json={"note": "fixture-secret-value", "price": 42},
        request=httpx.Request("GET", "https://user:password@provider.invalid/data?apikey=fixture-secret-value",
                              headers={"Authorization": "Bearer another-credential"}))
    with install_capture_hooks(), capture_producers() as captured:
        result = response.json()
    output = captured.snapshot()[0]
    assert result["note"] == "fixture-secret-value"
    assert output["arguments"] == {"status_code": 200, "url": "https://provider.invalid/data"}
    encoded = json.dumps(output)
    assert "fixture-secret-value" not in encoded and "another-credential" not in encoded
    assert "Authorization" not in encoded and "apikey" not in encoded and "password@" not in encoded
    assert output["data"]["note"] == "[REDACTED]"


def test_collectors_are_nested_and_thread_context_is_propagated(monkeypatch):
    monkeypatch.setattr(MarketDataGateway, "get_quote", lambda _self, symbol: {"symbol": symbol})
    gateway = object.__new__(MarketDataGateway)
    with install_capture_hooks(), capture_producers() as outer:
        gateway.get_quote("outer")
        with capture_producers() as inner:
            gateway.get_quote("inner")
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(gateway.get_quote, "child").result() == {"symbol": "child"}
    assert [item["data"]["symbol"] for item in outer.snapshot()] == ["outer", "child"]
    assert [item["data"]["symbol"] for item in inner.snapshot()] == ["inner"]


def test_concurrent_collectors_do_not_mix_provider_outputs(monkeypatch):
    monkeypatch.setattr(MarketDataGateway, "get_quote", lambda _self, symbol: {"symbol": symbol})
    gateway = object.__new__(MarketDataGateway)
    def collect(symbol):
        with capture_producers() as capture:
            gateway.get_quote(symbol)
        return capture.snapshot()
    with install_capture_hooks(), ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(collect, ["first", "second"]))
    assert [item["data"]["symbol"] for item in first] == ["first"]
    assert [item["data"]["symbol"] for item in second] == ["second"]


def test_hooks_restore_after_exception_and_inactive_calls_are_untouched():
    original_json, original_submit = requests.Response.json, ThreadPoolExecutor.submit
    response = requests.Response()
    response._content = b'{"price":42}'
    with pytest.raises(RuntimeError, match="fixture"):
        with install_capture_hooks():
            assert response.json() == {"price": 42}
            raise RuntimeError("fixture")
    assert requests.Response.json is original_json
    assert ThreadPoolExecutor.submit is original_submit


def test_unknown_lazy_object_is_not_read_or_stringified(monkeypatch):
    class Lazy:
        def __str__(self):
            raise AssertionError("不能将未知lazy对象转换为文本")
    value = Lazy()
    monkeypatch.setattr(MarketDataGateway, "get_quote", lambda *_a: value)
    with install_capture_hooks(), capture_producers() as captured:
        assert object.__new__(MarketDataGateway).get_quote("AAPL") is value
    assert captured.snapshot()[0]["status"] == "unavailable"
    assert captured.snapshot()[0]["reason"] == "producer_serialization_unavailable"


def test_producer_failure_retains_original_exception_without_message(monkeypatch):
    def failing(*_args):
        raise TimeoutError("provider-secret-error-body")
    monkeypatch.setattr(MarketDataGateway, "get_quote", failing)
    with install_capture_hooks(), capture_producers() as captured:
        with pytest.raises(TimeoutError, match="provider-secret-error-body"):
            object.__new__(MarketDataGateway).get_quote("AAPL")
    output = captured.snapshot()[0]
    assert output["exception_type"] == "TimeoutError" and output["status"] == "unavailable"
    assert "provider-secret-error-body" not in json.dumps(output)


def test_installed_ddgs_list_is_not_fetched_twice(monkeypatch):
    from backend.tools.search import DDGS
    if DDGS is None:
        pytest.skip("当前评测环境没有安装仓库声明的ddgs依赖")
    rows, calls = [{"title": "fixture", "href": "https://source.invalid", "body": "fixture data"}], []
    def text(_self, query, **kwargs):
        calls.append((query, kwargs))
        return rows
    monkeypatch.setattr(DDGS, "text", text)
    with install_capture_hooks(), capture_producers() as captured:
        assert object.__new__(DDGS).text("fixture query", max_results=2) is rows
    assert calls == [("fixture query", {"max_results": 2})]
    assert captured.snapshot()[0]["data"] == rows
