from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.rebalance_router import RebalanceRouterDeps, create_rebalance_router
from backend.services.rebalance_engine import RebalanceEngine


def _build_client(
    *,
    get_stock_price,
    get_company_info,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_rebalance_router(
            RebalanceRouterDeps(
                rebalance_engine=RebalanceEngine(),
                get_stock_price=get_stock_price,
                get_company_info=get_company_info,
            )
        )
    )
    return TestClient(app)


def test_generate_rebalance_degrades_when_live_price_missing():
    client = _build_client(
        get_stock_price=lambda _ticker: {},
        get_company_info=lambda _ticker: "- Sector: Technology",
    )

    payload = {
        "session_id": "public:test_user:thread-1",
        "portfolio": [
            {"ticker": "AAPL", "shares": 10},
            {"ticker": "MSFT", "shares": 5},
        ],
    }
    response = client.post("/api/rebalance/suggestions/generate", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["degraded_mode"] is True
    assert data["actions"] == []
    assert "missing_live_prices" in (data.get("fallback_reason") or "")


def test_generate_rebalance_returns_actions_when_inputs_complete():
    price_map = {"AAPL": 200.0, "MSFT": 100.0}
    client = _build_client(
        get_stock_price=lambda ticker: {"price": price_map[ticker]},
        get_company_info=lambda _ticker: "- Sector: Technology",
    )

    payload = {
        "session_id": "public:test_user:thread-2",
        "portfolio": [
            {"ticker": "AAPL", "shares": 10},
            {"ticker": "MSFT", "shares": 5},
        ],
        "constraints": {
            "max_single_position_pct": 55,
            "max_turnover_pct": 30,
            "sector_concentration_limit": 100,
            "min_action_delta_pct": 1,
        },
    }
    response = client.post("/api/rebalance/suggestions/generate", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["degraded_mode"] is False
    assert data.get("fallback_reason") in (None, "")
    assert len(data["actions"]) >= 1
