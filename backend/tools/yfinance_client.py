"""The only yfinance entry point with process-local proxy configuration."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)


class YFinanceProxyConfigurationChanged(RuntimeError):
    """Raised when a running process would need to reconfigure yfinance."""

    code = "yfinance_proxy_changed_requires_restart"

    def __init__(self) -> None:
        super().__init__(self.code)


_configuration_lock = threading.Lock()
_UNCONFIGURED = object()
_configured_proxy: str | None | object = _UNCONFIGURED


def get_yfinance_proxy() -> str | None:
    value = os.getenv("YFINANCE_PROXY", "").strip().strip('"')
    return value or None


def _ensure_configured() -> None:
    global _configured_proxy
    proxy = get_yfinance_proxy()
    with _configuration_lock:
        if _configured_proxy is _UNCONFIGURED:
            yf.set_config(proxy=proxy)
            _configured_proxy = proxy
            logger.info("yfinance proxy initialized: proxy_configured=%s", bool(proxy))
            return
        if proxy != _configured_proxy:
            logger.error("yfinance proxy configuration rejected: code=%s", YFinanceProxyConfigurationChanged.code)
            raise YFinanceProxyConfigurationChanged()


def create_ticker(symbol: str, **kwargs: Any) -> Any:
    if "proxy" in kwargs:
        raise TypeError("create_ticker() does not accept proxy")
    _ensure_configured()
    return yf.Ticker(symbol, **kwargs)


def download(*args: Any, **kwargs: Any) -> Any:
    if "proxy" in kwargs:
        raise TypeError("download() does not accept proxy")
    _ensure_configured()
    return yf.download(*args, **kwargs)


__all__ = [
    "YFinanceProxyConfigurationChanged",
    "create_ticker",
    "download",
    "get_yfinance_proxy",
]
