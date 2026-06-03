# -*- coding: utf-8 -*-
"""P2-11 报告与实时价差提示接口测试。

覆盖：
- 价差计算正确（report_price=100, current=105 → drift_pct=5.0, significant=true）
- 阈值内不显著
- 实时价拿不到时诚实降级（current_price=null, significant=false）
- report_age_hours 计算 + 时效触发 significant
- ticker 非法返回 422
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.report_router import ReportRouterDeps, create_report_router


@dataclass
class _FakeSnapshot:
    """模拟 PriceSnapshot，仅需 .price 属性。"""

    price: Optional[float]


def _build_client(*, price: Optional[float] = None, raise_on_fetch: bool = False) -> TestClient:
    """构造仅挂载 report_router 的最小 app，价格获取器可控。"""

    def _fetcher(ticker: str):
        if raise_on_fetch:
            raise RuntimeError("price source unavailable")
        if price is None:
            return None
        return _FakeSnapshot(price=price)

    deps = ReportRouterDeps(
        resolve_thread_id=lambda s: s or "tenant:user:thread",
        get_report_index_store=lambda: None,
        fetch_price_snapshot=_fetcher,
    )
    app = FastAPI()
    app.include_router(create_report_router(deps))
    return TestClient(app)


def _iso_hours_ago(hours: float) -> str:
    """返回 hours 小时前的 UTC ISO 时间戳（带 Z 后缀）。"""
    moment = datetime.now(timezone.utc) - timedelta(hours=hours)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_drift_pct_computed_and_significant():
    """report_price=100, current=105 → drift_pct=5.0, significant=true。"""
    client = _build_client(price=105.0)
    resp = client.get(
        "/api/reports/price-drift",
        params={"ticker": "AAPL", "report_price": 100.0, "report_generated_at": _iso_hours_ago(1)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "AAPL"
    assert body["report_price"] == 100.0
    assert body["current_price"] == 105.0
    assert body["drift_pct"] == 5.0
    assert body["significant"] is True


def test_drift_within_threshold_not_significant():
    """价差 1%（< 默认 2%）且报告很新 → 不显著。"""
    client = _build_client(price=101.0)
    resp = client.get(
        "/api/reports/price-drift",
        params={"ticker": "AAPL", "report_price": 100.0, "report_generated_at": _iso_hours_ago(1)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["drift_pct"] == 1.0
    assert body["significant"] is False


def test_negative_drift_significant():
    """价格下跌超过阈值同样应触发 significant（绝对值判定）。"""
    client = _build_client(price=95.0)
    resp = client.get(
        "/api/reports/price-drift",
        params={"ticker": "AAPL", "report_price": 100.0, "report_generated_at": _iso_hours_ago(1)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["drift_pct"] == -5.0
    assert body["significant"] is True


def test_price_unavailable_honest_degrade():
    """实时价拿不到 → current_price=null, drift_pct=null, significant=false。"""
    client = _build_client(price=None)
    resp = client.get(
        "/api/reports/price-drift",
        params={"ticker": "AAPL", "report_price": 100.0, "report_generated_at": _iso_hours_ago(1)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_price"] is None
    assert body["drift_pct"] is None
    assert body["significant"] is False


def test_price_fetch_raises_honest_degrade():
    """价格源抛异常时也应诚实降级，不 500。"""
    client = _build_client(raise_on_fetch=True)
    resp = client.get(
        "/api/reports/price-drift",
        params={"ticker": "AAPL", "report_price": 100.0, "report_generated_at": _iso_hours_ago(1)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_price"] is None
    assert body["significant"] is False


def test_report_age_hours_computed():
    """report_age_hours 应约等于传入的小时差。"""
    client = _build_client(price=100.0)
    resp = client.get(
        "/api/reports/price-drift",
        params={"ticker": "AAPL", "report_price": 100.0, "report_generated_at": _iso_hours_ago(5)},
    )
    assert resp.status_code == 200
    age = resp.json()["report_age_hours"]
    assert age is not None
    assert 4.9 <= age <= 5.2


def test_old_report_significant_even_without_price_drift():
    """报告超过 24 小时 → 即使价差为 0 也应 significant（时效提示）。"""
    client = _build_client(price=100.0)
    resp = client.get(
        "/api/reports/price-drift",
        params={"ticker": "AAPL", "report_price": 100.0, "report_generated_at": _iso_hours_ago(30)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["drift_pct"] == 0.0
    assert body["report_age_hours"] >= 24.0
    assert body["significant"] is True


def test_no_report_price_falls_back_to_age_only():
    """report_price 缺失 → 只看时效；新报告应不显著。"""
    client = _build_client(price=100.0)
    resp = client.get(
        "/api/reports/price-drift",
        params={"ticker": "AAPL", "report_generated_at": _iso_hours_ago(1)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_price"] is None
    assert body["drift_pct"] is None
    assert body["significant"] is False


def test_invalid_ticker_returns_422():
    """非法 ticker（含空格/特殊字符）应被拒绝。"""
    client = _build_client(price=100.0)
    resp = client.get(
        "/api/reports/price-drift",
        params={"ticker": "AA PL!", "report_price": 100.0},
    )
    assert resp.status_code == 422


def test_unparsable_timestamp_degrades_age_to_null():
    """时间戳无法解析 → report_age_hours=null，不报错。"""
    client = _build_client(price=105.0)
    resp = client.get(
        "/api/reports/price-drift",
        params={"ticker": "AAPL", "report_price": 100.0, "report_generated_at": "not-a-date"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["report_age_hours"] is None
    # 价差仍然有效
    assert body["drift_pct"] == 5.0
    assert body["significant"] is True
