"""评测专用旁路捕获：只观察本次调用已经返回的结构化对象。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar, copy_context
from copy import deepcopy
from datetime import date, datetime, time
from functools import wraps
import json
import math
import os
from threading import Lock
from urllib.parse import urlsplit, urlunsplit
from unittest.mock import patch


_CURRENT: ContextVar[ProducerCapture | None] = ContextVar("agent_eval_producer_capture", default=None)
_INSTALLED: dict | None = None
_SAFE_ARGUMENTS = {"symbol", "ticker", "period", "interval", "limit", "days", "start", "end",
                   "auto_adjust", "actions", "query", "keywords", "max_results", "region", "safesearch", "timelimit"}


def _normalise(value):
    """显式转换已返回的 pandas/numpy 值，未知对象不调用 str 或 lazy 属性。"""
    import numpy as np
    import pandas as pd
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, pd.DataFrame):
        return {**_normalise(value.to_dict(orient="split")),
                "index_names": list(value.index.names), "column_names": list(value.columns.names)}
    if isinstance(value, np.ndarray):
        return _normalise(value.tolist())
    if isinstance(value, np.generic):
        return _normalise(value.item())
    if value is None or type(value) in {str, bool, int} or isinstance(value, (datetime, date, time)):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _normalise(item) for key, item in value.items()}
    raise TypeError("producer_serialization_unavailable")


def _redactor():
    secrets = sorted({value for name, value in os.environ.items() if value and (
        name.upper() in {"API_KEY", "TOKEN", "SECRET", "PASSWORD"}
        or name.upper().endswith(("_API_KEY", "_ACCESS_TOKEN", "_AUTH_TOKEN", "_SECRET", "_PASSWORD")))}, key=len, reverse=True)
    def redact(value):
        if isinstance(value, str):
            for secret in secrets:
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {redact(key): redact(item) for key, item in value.items()}
        return value
    return redact


class ProducerCapture:
    def __init__(self, redact=None):
        self._redact = redact or _redactor()
        self._outputs, self._lock, self._closed = [], Lock(), False
        self.hooks = deepcopy(_INSTALLED)

    def append(self, producer, method, arguments, data=None, *, error=None):
        from backend.agent_runtime.context import dumps
        import pandas as pd
        output = {"producer": producer, "method": method, "arguments": arguments,
                  "status": "captured", "data_format": "dataframe_split" if isinstance(data, pd.DataFrame) else "json"}
        try:
            if error is not None:
                output.update(status="unavailable", reason="producer_exception", exception_type=type(error).__name__, data=None)
            else:
                output["data"] = _normalise(data)
            output = self._redact(json.loads(dumps(_normalise(output))))
        except Exception:
            output = {"producer": producer, "method": method, "arguments": {}, "status": "unavailable",
                      "reason": "producer_serialization_unavailable", "data": None}
        with self._lock:
            if not self._closed:
                self._outputs.append(output)

    def snapshot(self):
        with self._lock:
            return deepcopy(self._outputs)

    def capability(self):
        outputs = self.snapshot()
        captured = sum(item["status"] == "captured" for item in outputs)
        return {"status": "captured" if captured else "unavailable", "captured_count": captured,
                "unavailable_count": len(outputs) - captured,
                "reason": None if captured else "no_structured_producer_output" if self.hooks else "capture_hooks_not_installed",
                "hooks": self.hooks or {"installed": [], "unavailable": []}}

    def close(self):
        with self._lock:
            self._closed = True


@contextmanager
def capture_producers(redact=None):
    collector = ProducerCapture(redact)
    token = _CURRENT.set(collector)
    try:
        yield collector
    finally:
        collector.close()
        _CURRENT.reset(token)


def _arguments(instance, args, kwargs, positional):
    values = {key: value for key, value in kwargs.items() if key in _SAFE_ARGUMENTS}
    values.update({key: value for key, value in zip(positional, args) if key in _SAFE_ARGUMENTS})
    ticker = vars(instance).get("ticker")
    if isinstance(ticker, str):
        values.setdefault("ticker", ticker)
    return values


def _response_arguments(response, _args, _kwargs, _positional):
    fields = vars(response)
    request = fields.get("_request")
    url = fields.get("url") or (vars(request).get("url") if request is not None else None)
    result = {"status_code": fields.get("status_code")}
    if url is not None:
        parsed = urlsplit(str(url))
        host = parsed.hostname or ""
        if parsed.port:
            host += ":" + str(parsed.port)
        result["url"] = urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    return result


def _observed(original, producer, method, positional=(), arguments=_arguments):
    @wraps(original)
    def call(instance, *args, **kwargs):
        collector = _CURRENT.get()
        if collector is None:
            return original(instance, *args, **kwargs)
        # 不允许旁路元数据采集失败改变被测供应商的调用。
        try:
            selected = arguments(instance, args, kwargs, positional)
        except Exception:
            selected = {}
        try:
            result = original(instance, *args, **kwargs)
        except Exception as exc:
            collector.append(producer, method, selected, error=exc)
            raise
        collector.append(producer, method, selected, result)
        return result
    return call


@contextmanager
def install_capture_hooks():
    """仅在评测进程作用域安装；返回实际安装与缺失的 hook 清单。"""
    global _INSTALLED
    if _INSTALLED is not None:
        yield deepcopy(_INSTALLED)
        return
    import httpx
    import requests
    from curl_cffi.requests import Response as CurlResponse
    from yfinance.base import TickerBase
    from backend.services.market_data_gateway import MarketDataGateway
    from backend.tools.search import DDGS

    capabilities = {"installed": [], "unavailable": []}
    targets = [
        (MarketDataGateway, "get_quote", "market_data_gateway", ("symbol",), _arguments),
        (MarketDataGateway, "get_kline", "market_data_gateway", ("symbol",), _arguments),
        (MarketDataGateway, "get_news", "market_data_gateway", ("symbol",), _arguments),
        (TickerBase, "get_info", "yfinance.TickerBase", (), _arguments),
        (TickerBase, "history", "yfinance.TickerBase", ("period",), _arguments),
        (requests.Response, "json", "requests.Response", (), _response_arguments),
        (httpx.Response, "json", "httpx.Response", (), _response_arguments),
        (CurlResponse, "json", "curl_cffi.requests.Response", (), _response_arguments),
    ]
    if DDGS is not None:
        targets.append((DDGS, "text", "ddgs.DDGS", ("query",), _arguments))
    else:
        capabilities["unavailable"].append("ddgs.DDGS.text")
    with ExitStack() as stack:
        for cls, method, producer, positional, argument_picker in targets:
            stack.enter_context(patch.object(cls, method,
                _observed(getattr(cls, method), producer, method, positional, argument_picker)))
            capabilities["installed"].append(producer + "." + method)
        original_submit = ThreadPoolExecutor.submit
        @wraps(original_submit)
        def submit(executor, fn, /, *args, **kwargs):
            if _CURRENT.get() is None:
                return original_submit(executor, fn, *args, **kwargs)
            context = copy_context()
            return original_submit(executor, context.run, fn, *args, **kwargs)
        stack.enter_context(patch.object(ThreadPoolExecutor, "submit", submit))
        capabilities["installed"].append("ThreadPoolExecutor.submit")
        _INSTALLED = capabilities
        try:
            yield deepcopy(capabilities)
        finally:
            _INSTALLED = None
