"""/api/chart/data 端点测试。

覆盖：
- composition 成功（mock FMP 营收分部）→ labels/values 正确、最多 8 个
- composition 无数据 → success=False + fallback_reason
- composition FMP 未配置 → success=False（不 500）
- comparison 成功（mock peer 对比）→ labels/values 正确
- comparison 指标缺失 → success=False
- 不支持的 data_kind → success=False
- 无效 ticker → 400

诚实原则守护：数据拿不到时端点必须返回 success=False，绝不编造。
"""

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.market_router import MarketRouterDeps, create_market_router


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(
        create_market_router(
            MarketRouterDeps(
                get_orchestrator_safe=lambda: None,
                get_stock_price=lambda _ticker: {"price": 100.0},
                get_company_news=lambda _ticker: [],
                get_financial_statements=lambda _ticker: {},
                get_financial_statements_summary=lambda _ticker: {},
                get_stock_historical_data=lambda _ticker, period="1y", interval="1d": {
                    "kline_data": [],
                    "period": period,
                    "interval": interval,
                },
                detect_chart_type=None,
                logger=logging.getLogger("test_chart_data"),
            )
        )
    )
    return TestClient(app)


# ── composition（pie / 营收构成）─────────────────────────────────────────────


def test_composition_success_returns_labels_and_values(monkeypatch):
    segments = [
        {"segment": "iPhone", "revenue": 200_000_000_000, "percentage": 52.0},
        {"segment": "Services", "revenue": 85_000_000_000, "percentage": 22.0},
        {"segment": "Mac", "revenue": 40_000_000_000, "percentage": 10.0},
    ]
    monkeypatch.setattr("backend.tools.fmp.is_fmp_configured", lambda: True)
    monkeypatch.setattr(
        "backend.tools.fmp.get_revenue_product_segmentation", lambda symbol: segments
    )

    client = _build_client()
    response = client.post(
        "/api/chart/data", json={"ticker": "AAPL", "data_kind": "composition"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["source"] == "fmp"
    assert payload["data"]["labels"] == ["iPhone", "Services", "Mac"]
    assert payload["data"]["values"] == [200_000_000_000, 85_000_000_000, 40_000_000_000]
    assert payload["data"]["unit"] == "$"


def test_composition_caps_at_eight_segments(monkeypatch):
    segments = [
        {"segment": f"Seg{i}", "revenue": (20 - i) * 1_000_000_000, "percentage": 5.0}
        for i in range(12)
    ]
    monkeypatch.setattr("backend.tools.fmp.is_fmp_configured", lambda: True)
    monkeypatch.setattr(
        "backend.tools.fmp.get_revenue_product_segmentation", lambda symbol: segments
    )

    client = _build_client()
    response = client.post(
        "/api/chart/data", json={"ticker": "AAPL", "data_kind": "composition"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert len(payload["data"]["labels"]) == 8
    assert len(payload["data"]["values"]) == 8


def test_composition_no_data_returns_fallback(monkeypatch):
    monkeypatch.setattr("backend.tools.fmp.is_fmp_configured", lambda: True)
    monkeypatch.setattr(
        "backend.tools.fmp.get_revenue_product_segmentation", lambda symbol: []
    )

    client = _build_client()
    response = client.post(
        "/api/chart/data", json={"ticker": "TINYCO", "data_kind": "composition"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["fallback_reason"] == "no_segmentation_data"


def test_composition_fmp_not_configured_returns_fallback(monkeypatch):
    monkeypatch.setattr("backend.tools.fmp.is_fmp_configured", lambda: False)

    client = _build_client()
    response = client.post(
        "/api/chart/data", json={"ticker": "AAPL", "data_kind": "composition"}
    )

    # 关键：FMP key 未配置时优雅返回，绝不 500。
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["fallback_reason"] == "fmp_not_configured"


# ── comparison（bar / 同行对比）─────────────────────────────────────────────


def test_comparison_success_returns_pe_values(monkeypatch):
    comparison = {
        "subject_symbol": "AAPL",
        "peers": [
            {"symbol": "AAPL", "name": "Apple", "trailing_pe": 30.5},
            {"symbol": "MSFT", "name": "Microsoft", "trailing_pe": 35.2},
            {"symbol": "GOOGL", "name": "Alphabet", "trailing_pe": 25.1},
        ],
    }
    monkeypatch.setattr(
        "backend.dashboard.peer_service.fetch_peer_comparison",
        lambda symbol, peers: comparison,
    )

    client = _build_client()
    response = client.post(
        "/api/chart/data", json={"ticker": "AAPL", "data_kind": "comparison"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["source"] == "peer_comparison"
    assert payload["data"]["labels"] == ["AAPL", "MSFT", "GOOGL"]
    assert payload["data"]["values"] == [30.5, 35.2, 25.1]
    assert payload["data"]["unit"] == "x"


def test_comparison_custom_field_market_cap_uses_dollar_unit(monkeypatch):
    comparison = {
        "subject_symbol": "AAPL",
        "peers": [
            {"symbol": "AAPL", "market_cap": 3_000_000_000_000},
            {"symbol": "MSFT", "market_cap": 2_800_000_000_000},
        ],
    }
    monkeypatch.setattr(
        "backend.dashboard.peer_service.fetch_peer_comparison",
        lambda symbol, peers: comparison,
    )

    client = _build_client()
    response = client.post(
        "/api/chart/data",
        json={"ticker": "AAPL", "data_kind": "comparison", "fields": "market_cap"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["unit"] == "$"
    assert payload["data"]["values"] == [3_000_000_000_000, 2_800_000_000_000]


def test_comparison_caps_at_eight(monkeypatch):
    comparison = {
        "subject_symbol": "AAPL",
        "peers": [
            {"symbol": f"SYM{i}", "trailing_pe": 20.0 + i} for i in range(12)
        ],
    }
    monkeypatch.setattr(
        "backend.dashboard.peer_service.fetch_peer_comparison",
        lambda symbol, peers: comparison,
    )

    client = _build_client()
    response = client.post(
        "/api/chart/data", json={"ticker": "AAPL", "data_kind": "comparison"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert len(payload["data"]["values"]) == 8


def test_comparison_no_metric_returns_fallback(monkeypatch):
    # peers 有数据，但目标指标 trailing_pe 全部缺失 → 诚实跳过。
    comparison = {
        "subject_symbol": "AAPL",
        "peers": [
            {"symbol": "AAPL", "trailing_pe": None},
            {"symbol": "MSFT", "trailing_pe": None},
        ],
    }
    monkeypatch.setattr(
        "backend.dashboard.peer_service.fetch_peer_comparison",
        lambda symbol, peers: comparison,
    )

    client = _build_client()
    response = client.post(
        "/api/chart/data", json={"ticker": "AAPL", "data_kind": "comparison"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert "no_metric_data" in payload["fallback_reason"]


def test_comparison_no_peer_data_returns_fallback(monkeypatch):
    monkeypatch.setattr(
        "backend.dashboard.peer_service.fetch_peer_comparison",
        lambda symbol, peers: None,
    )

    client = _build_client()
    response = client.post(
        "/api/chart/data", json={"ticker": "AAPL", "data_kind": "comparison"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["fallback_reason"] == "no_peer_data"


# ── 边界 / 错误处理 ─────────────────────────────────────────────────────────


def test_unsupported_data_kind_returns_failure():
    client = _build_client()
    response = client.post(
        "/api/chart/data", json={"ticker": "AAPL", "data_kind": "financial"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["reason"] == "unsupported_data_kind"


def test_invalid_ticker_returns_400():
    client = _build_client()
    response = client.post(
        "/api/chart/data",
        json={"ticker": "GOOGL VS GOOGLE", "data_kind": "composition"},
    )

    assert response.status_code == 400
    detail = str(response.json().get("detail", ""))
    assert "ticker" in detail


def test_empty_ticker_returns_400():
    client = _build_client()
    response = client.post(
        "/api/chart/data", json={"ticker": "", "data_kind": "composition"}
    )

    assert response.status_code == 400


def test_composition_fmp_exception_returns_fallback(monkeypatch):
    # FMP 调用抛异常时端点不能 500，必须优雅返回 success=False。
    monkeypatch.setattr("backend.tools.fmp.is_fmp_configured", lambda: True)

    def _boom(symbol):
        raise RuntimeError("network down")

    monkeypatch.setattr(
        "backend.tools.fmp.get_revenue_product_segmentation", _boom
    )

    client = _build_client()
    response = client.post(
        "/api/chart/data", json={"ticker": "AAPL", "data_kind": "composition"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert "composition_error" in payload["fallback_reason"]
