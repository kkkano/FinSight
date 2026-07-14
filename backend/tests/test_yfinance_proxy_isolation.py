"""WP0: yfinance configuration must not leak into process-wide HTTP clients."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_tools_env_import_does_not_mutate_http_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YFINANCE_PROXY", "socks5h://proxy.example:1080")
    before = {key: __import__("os").environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
    import backend.tools.env as env

    importlib.reload(env)
    after = {key: __import__("os").environ.get(key) for key in before}
    assert after == before


def test_yfinance_proxy_is_initialized_once_and_then_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.tools.yfinance_client as client

    calls: list[tuple[str, object]] = []

    class FakeYFinance:
        @staticmethod
        def set_config(*, proxy: str | None) -> None:
            calls.append(("set_config", proxy))

        @staticmethod
        def Ticker(symbol: str, **kwargs: object) -> tuple[str, str, dict[str, object]]:
            calls.append(("ticker", symbol))
            return ("ticker", symbol, kwargs)

        @staticmethod
        def download(*args: object, **kwargs: object) -> tuple[str, tuple[object, ...], dict[str, object]]:
            calls.append(("download", args))
            return ("download", args, kwargs)

    monkeypatch.setattr(client, "yf", FakeYFinance)
    monkeypatch.setattr(client, "_configured_proxy", client._UNCONFIGURED)
    monkeypatch.setenv("YFINANCE_PROXY", " socks5h://proxy.example:1080 ")

    assert client.create_ticker("AAPL")[1] == "AAPL"
    assert client.download("AAPL", period="5d")[0] == "download"
    assert calls == [
        ("set_config", "socks5h://proxy.example:1080"),
        ("ticker", "AAPL"),
        ("download", ("AAPL",)),
    ]

    monkeypatch.setenv("YFINANCE_PROXY", "socks5h://other.example:1080")
    with pytest.raises(client.YFinanceProxyConfigurationChanged, match="yfinance_proxy_changed_requires_restart"):
        client.create_ticker("MSFT")
    assert calls[-1] == ("download", ("AAPL",))


def test_yfinance_callers_do_not_import_or_bypass_the_helper() -> None:
    root = Path(__file__).resolve().parents[2]
    files = (
        "backend/utils/quote.py",
        "backend/dashboard/peer_service.py",
        "backend/dashboard/data_service.py",
        "backend/tools/financial.py",
        "backend/tools/screener.py",
        "backend/tools/price.py",
        "backend/tools/news.py",
        "backend/services/alert_scheduler.py",
    )
    for relative_path in files:
        source = (root / relative_path).read_text(encoding="utf-8")
        assert "import yfinance" not in source
        assert "yf.Ticker" not in source
        assert "yf.download" not in source
