import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.market_router import MarketRouterDeps, create_market_router


def _build_client(
    *,
    get_stock_price=None,
    get_company_news=None,
    get_financial_statements=None,
    get_financial_statements_summary=None,
    get_stock_historical_data=None,
    detect_chart_type=None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_market_router(
            MarketRouterDeps(
                get_orchestrator_safe=lambda: None,
                get_stock_price=get_stock_price or (lambda _ticker: {"price": 100.0}),
                get_company_news=get_company_news or (lambda _ticker: []),
                get_financial_statements=get_financial_statements or (lambda _ticker: {}),
                get_financial_statements_summary=get_financial_statements_summary or (lambda _ticker: {}),
                get_stock_historical_data=get_stock_historical_data
                or (lambda _ticker, period="1y", interval="1d": {"kline_data": [], "period": period, "interval": interval}),
                detect_chart_type=detect_chart_type,
                logger=logging.getLogger("test_market_router"),
            )
        )
    )
    return TestClient(app)


def test_price_endpoint_normalizes_ticker_before_fetch():
    called: list[str] = []

    def _get_stock_price(ticker: str):
        called.append(ticker)
        return {"price": 123.45}

    client = _build_client(get_stock_price=_get_stock_price)
    response = client.get("/api/stock/price/aapl")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AAPL"
    assert called == ["AAPL"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/stock/price/GOOGL%20VS%20GOOGLE",
        "/api/stock/kline/GOOGL%20VS%20GOOGLE",
        "/api/stock/news/GOOGL%20VS%20GOOGLE",
        "/api/financials/GOOGL%20VS%20GOOGLE",
        "/api/financials/GOOGL%20VS%20GOOGLE/summary",
    ],
)
def test_market_endpoints_reject_phrase_like_ticker(path: str):
    client = _build_client()
    response = client.get(path)

    assert response.status_code == 400
    detail = str(response.json().get("detail", ""))
    assert "ticker" in detail


def test_kline_endpoint_normalizes_special_symbol():
    called: list[str] = []

    def _get_stock_historical_data(ticker: str, period: str = "1y", interval: str = "1d"):
        called.append(ticker)
        return {"kline_data": [], "period": period, "interval": interval}

    client = _build_client(get_stock_historical_data=_get_stock_historical_data)
    response = client.get("/api/stock/kline/gc=f")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "GC=F"
    assert called == ["GC=F"]


def test_chart_detect_returns_dynamic_ticker_candidates():
    client = _build_client()
    response = client.post(
        "/api/chart/detect",
        json={"query": "compare google and TSLA trend", "ticker": "aapl"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("ticker_candidates"), list)
    assert "AAPL" in payload["ticker_candidates"]
    assert "TSLA" in payload["ticker_candidates"]
    assert payload.get("resolved_ticker") == payload["ticker_candidates"][0]
