# -*- coding: utf-8 -*-
"""WP6-F6 组合归因 API 数学与降级契约。"""
from __future__ import annotations

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import attribution_router as attribution_module


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(attribution_module.attribution_router)
    return TestClient(app)


def _history_frame() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=21, freq="D")
    return pd.DataFrame(
        {
            "AAPL": [100 + index for index in range(21)],
            "MSFT": [200 - index for index in range(21)],
            "SPY": [100 + index * 0.5 for index in range(21)],
        },
        index=dates,
    )


def test_attribution_contribution_math_and_benchmark(monkeypatch):
    monkeypatch.setattr(attribution_module.price_tools, "_download_close_frame", lambda *_args, **_kwargs: _history_frame())
    monkeypatch.setattr(
        attribution_module.price_tools,
        "get_factor_exposure",
        lambda *_args, **_kwargs: {"factor_beta": {"market": 1.25}, "source": "test"},
    )

    response = _client().post(
        "/api/portfolio/attribution",
        json={
            "positions": [
                {"ticker": "aapl", "weight": 0.4},
                {"ticker": "MSFT", "weight": 0.6},
            ],
            "lookback_days": 252,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["beta"] == 1.25
    assert payload["benchmark"] == {"symbol": "SPY", "return_pct": 10.0}
    assert payload["as_of"] == "2026-01-21"
    assert payload["warnings"] == []
    assert payload["contribution"] == [
        {"ticker": "AAPL", "weight": 0.4, "return_pct": 20.0, "contribution_pct": 8.0},
        {"ticker": "MSFT", "weight": 0.6, "return_pct": -10.0, "contribution_pct": -6.0},
    ]


def test_attribution_missing_symbol_is_warning_not_whole_request_failure(monkeypatch):
    monkeypatch.setattr(attribution_module.price_tools, "_download_close_frame", lambda *_args, **_kwargs: _history_frame())
    monkeypatch.setattr(
        attribution_module.price_tools,
        "get_factor_exposure",
        lambda *_args, **_kwargs: {"factor_beta": {"market": None}, "source": "test"},
    )

    response = _client().post(
        "/api/portfolio/attribution",
        json={
            "positions": [
                {"ticker": "AAPL", "weight": 0.5},
                {"ticker": "NVDA", "weight": 0.5},
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["contribution"][1] == {
        "ticker": "NVDA",
        "weight": 0.5,
        "return_pct": None,
        "contribution_pct": None,
    }
    assert payload["warnings"] == ["NVDA 缺少可用历史数据，已跳过该标的贡献计算"]


def test_attribution_rejects_empty_positions_with_guidance():
    response = _client().post(
        "/api/portfolio/attribution",
        json={"positions": [], "lookback_days": 252},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "请先录入至少一个持仓，再计算组合归因"
