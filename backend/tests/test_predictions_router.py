# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.agents.prediction_contract import AgentPrediction
from backend.api.predictions_router import PredictionsRouterDeps, create_predictions_router
from backend.services.llm_usage_store import UserDailyCostLimitExceeded
from backend.services.prediction_service import PredictionRun


NOW = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
RUN_ID = "00000000-0000-4000-8000-000000000301"
PREDICTION_ID = "00000000-0000-4000-8000-000000000302"


def _run() -> PredictionRun:
    return PredictionRun.model_validate({
        "id": RUN_ID,
        "user_id": "alice",
        "symbol": "AAPL",
        "timeframe": "1d",
        "prompt_version": "prediction-analyst-v1",
        "status": "queued",
        "created_at": NOW,
        "updated_at": NOW,
    })


def _prediction() -> AgentPrediction:
    return AgentPrediction.model_validate({
        "id": PREDICTION_ID,
        "user_id": "alice",
        "run_id": RUN_ID,
        "symbol": "AAPL",
        "agent": "prediction_analyst",
        "direction": "long",
        "confidence": 0.8,
        "thesis": "趋势延续，风险收益满足合同。",
        "anchor": {"timeframe": "1d", "time": "2026-07-15", "price": 100},
        "entry_type": "market",
        "entry": 100,
        "stop": 95,
        "target1": 110,
        "invalidation_price": 94,
        "scenarios": [
            {"name": "延续", "probability": 60, "invalidation": "跌破止损"},
            {"name": "回撤", "probability": 40, "invalidation": "突破目标"},
        ],
        "status": "waiting",
        "prompt_version": "prediction-analyst-v1",
        "evidence_provider": "fixture-provider",
        "evidence_as_of": NOW,
        "source_type": "ai",
        "created_at": NOW,
        "updated_at": NOW,
    })


def _outcome() -> dict[str, Any]:
    return {
        "prediction_id": PREDICTION_ID,
        "user_id": "alice",
        "status": "open",
        "resolved_at": None,
        "entry_time": NOW,
        "entry_price": 100,
        "pct_since_anchor": 1.25,
        "resolution_reason": None,
        "evaluated_through": NOW,
        "market_provider": "fixture-provider",
        "market_as_of": NOW,
        "algorithm_version": "prediction-outcome-v1",
    }


def _stats() -> dict[str, Any]:
    empty = {
        "predictions": 0,
        "hits": 0,
        "misses": 0,
        "invalidated": 0,
        "resolved": 0,
        "hit_rate": None,
    }
    ai = {**empty, "predictions": 1}
    return {
        **ai,
        "days": 90,
        "symbol": "AAPL",
        "by_source": {"ai": ai, "manual": empty},
        "by_direction": {"long": ai},
    }


class _Service:
    def __init__(self) -> None:
        self.generated = False
        self.raise_reads = False

    async def generate(self, *, user_id: str, symbol: str, timeframe: str):
        assert user_id == "alice"
        assert symbol == "AAPL"
        assert timeframe == "1d"
        created = not self.generated
        self.generated = True
        return _run(), created

    async def get_run(self, run_id: str, *, user_id: str):
        if self.raise_reads:
            raise RuntimeError("database unavailable")
        return _run() if run_id == RUN_ID and user_id == "alice" else None

    async def get_prediction(self, prediction_id: str, *, user_id: str):
        return _prediction() if prediction_id == PREDICTION_ID and user_id == "alice" else None

    async def get_latest(self, *, user_id: str, symbol: str):
        return _prediction() if user_id == "alice" and symbol.strip().upper() == "AAPL" else None

    async def get_outcome(self, prediction_id: str, *, user_id: str):
        return _outcome() if prediction_id == PREDICTION_ID and user_id == "alice" else None

    async def history(self, **kwargs: Any):
        return (
            [{"prediction": _prediction(), "outcome": _outcome()}]
            if kwargs["user_id"] == "alice"
            else []
        )

    async def stats(self, **kwargs: Any):
        assert kwargs["user_id"] == "alice"
        return _stats()


def _allow_quota(_user_id: str) -> None:
    return None


def _client(
    *,
    check_user_quota: Any = _allow_quota,
) -> tuple[TestClient, _Service, list[dict[str, Any]]]:
    service = _Service()
    recompute_calls: list[dict[str, Any]] = []

    def recompute(**kwargs: Any) -> int:
        recompute_calls.append(kwargs)
        return 1

    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "public")
        return await call_next(request)

    app.include_router(create_predictions_router(PredictionsRouterDeps(
        get_service=lambda: service,
        check_user_quota=check_user_quota,
        run_outcome_cycle=recompute,
        is_internal_authorized=lambda request: request.headers.get("x-internal-key") == "allowed",
    )))
    return TestClient(app), service, recompute_calls


def test_generate_requires_auth_and_returns_202_queued_with_idempotent_reuse():
    client, _service, _calls = _client()
    unauthorized = client.post("/api/predictions/generate", json={"symbol": "AAPL"})
    assert unauthorized.status_code == 401
    assert unauthorized.json()["detail"]["code"] == "auth_required"

    first = client.post(
        "/api/predictions/generate",
        headers={"x-test-user": "alice"},
        json={"symbol": " aapl "},
    )
    second = client.post(
        "/api/predictions/generate",
        headers={"x-test-user": "alice"},
        json={"symbol": "AAPL"},
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["run"]["status"] == "queued"
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert second.json()["idempotent_reuse"] is True


def test_generate_checks_quota_before_creating_run():
    checked_users: list[str] = []

    def reject_quota(user_id: str) -> None:
        checked_users.append(user_id)
        raise UserDailyCostLimitExceeded(user_id=user_id, limit_usd=1.0, used_usd=1.25)

    client, service, _calls = _client(check_user_quota=reject_quota)
    response = client.post(
        "/api/predictions/generate",
        headers={"x-test-user": "alice"},
        json={"symbol": "AAPL"},
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "llm_quota_exceeded"
    assert checked_users == ["alice"]
    assert service.generated is False


def test_run_and_prediction_reads_hide_cross_tenant_resources_with_same_404():
    client, _service, _calls = _client()
    for path in (
        f"/api/predictions/runs/{RUN_ID}",
        f"/api/predictions/{PREDICTION_ID}",
    ):
        missing = client.get(path, headers={"x-test-user": "alice"})
        other_tenant = client.get(path, headers={"x-test-user": "bob"})
        assert missing.status_code == 200
        assert other_tenant.status_code == 404

    invalid = client.get("/api/predictions/not-a-uuid", headers={"x-test-user": "alice"})
    assert invalid.status_code == 404
    assert invalid.json()["detail"]["code"] == "prediction_not_found"


def test_latest_detail_history_and_stats_share_prediction_outcome_provenance():
    client, _service, _calls = _client()
    headers = {"x-test-user": "alice"}

    latest = client.get("/api/predictions/latest?symbol=AAPL", headers=headers)
    detail = client.get(f"/api/predictions/{PREDICTION_ID}", headers=headers)
    history = client.get("/api/predictions/history?symbol=AAPL", headers=headers)
    stats = client.get("/api/predictions/stats?symbol=AAPL", headers=headers)

    for response in (latest, detail):
        assert response.status_code == 200
        assert response.json()["prediction"]["prediction_id"] == PREDICTION_ID
        assert response.json()["outcome"]["market_provider"] == "fixture-provider"
        assert response.json()["outcome"]["algorithm_version"] == "prediction-outcome-v1"
    assert history.json()["items"][0]["prediction"]["source_type"] == "ai"
    assert history.json()["items"][0]["outcome"]["prediction_id"] == PREDICTION_ID
    assert set(stats.json()["stats"]["by_source"]) == {"ai", "manual"}


def test_outcome_recompute_requires_internal_key_and_is_tenant_scoped():
    client, _service, calls = _client()
    payload = {"prediction_id": PREDICTION_ID, "limit": 10}
    headers = {"x-test-user": "alice"}

    denied = client.post("/api/predictions/outcomes/recompute", headers=headers, json=payload)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "internal_authorization_required"

    accepted = client.post(
        "/api/predictions/outcomes/recompute",
        headers={**headers, "x-internal-key": "allowed"},
        json=payload,
    )
    assert accepted.status_code == 200
    assert accepted.json() == {"evaluated": 1, "prediction_id": PREDICTION_ID}
    assert calls == [{"user_id": "alice", "prediction_id": PREDICTION_ID, "limit": 10}]


def test_store_failure_uses_stable_code_instead_of_generic_unavailable_text():
    client, service, _calls = _client()
    service.raise_reads = True
    response = client.get(
        f"/api/predictions/runs/{RUN_ID}",
        headers={"x-test-user": "alice"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "store_unavailable"
