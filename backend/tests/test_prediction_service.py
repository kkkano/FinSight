# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any, Mapping

import pytest

from backend.agents.prediction_contract import AgentPrediction
from backend.services.prediction_service import (
    MARKET_DATA_UNAVAILABLE,
    PREDICTION_VALIDATION_FAILED,
    PredictionRun,
    PredictionRunStore,
    PredictionService,
    _summarize_stats,
)


NOW = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
RUN_ID = "00000000-0000-4000-8000-000000000101"
PREDICTION_ID = "00000000-0000-4000-8000-000000000201"


def _run(**overrides: Any) -> PredictionRun:
    payload = {
        "id": RUN_ID,
        "user_id": "alice",
        "symbol": "AAPL",
        "timeframe": "1d",
        "prompt_version": "prediction-analyst-v1",
        "status": "queued",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return PredictionRun.model_validate(payload)


def _bars(count: int = 60) -> list[dict[str, Any]]:
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    result: list[dict[str, Any]] = []
    for index in range(count):
        close = round(100 + index * 0.1, 2)
        result.append({
            "time": (start + timedelta(days=index)).date().isoformat(),
            "open": close - 0.2,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000_000 + index,
        })
    return result


def _market(*, quality: str = "trusted") -> dict[str, Any]:
    return {
        "quality": quality,
        "error_code": None if quality == "trusted" else MARKET_DATA_UNAVAILABLE,
        "provider": "fixture-provider" if quality == "trusted" else None,
        "as_of": "2026-07-15T12:00:00Z" if quality == "trusted" else None,
        "interval": "1d",
        "kline_data": _bars(),
    }


def _draft_payload(*, valid: bool = True) -> dict[str, Any]:
    anchor = _bars()[-1]
    return {
        "symbol": "FORGED",
        "agent": "forged",
        "direction": "long",
        "confidence": 0.78,
        "thesis": "趋势与风险收益结构支持看多。",
        "anchor": {
            "timeframe": "1d",
            "time": anchor["time"],
            "price": anchor["close"],
        },
        "entry_type": "market",
        "entry": anchor["close"],
        "stop": anchor["close"] + 2 if not valid else anchor["close"] - 5,
        "target1": anchor["close"] + 10,
        "invalidation_price": anchor["close"] - 6,
        "scenarios": [
            {"name": "延续", "probability": 60, "invalidation": "跌破止损"},
            {"name": "回撤", "probability": 40, "invalidation": "突破目标"},
        ],
    }


def _prediction() -> AgentPrediction:
    payload = _draft_payload()
    payload.update({
        "id": PREDICTION_ID,
        "user_id": "alice",
        "run_id": RUN_ID,
        "symbol": "AAPL",
        "agent": "prediction_analyst",
        "status": "waiting",
        "prompt_version": "prediction-analyst-v1",
        "evidence_provider": "fixture-provider",
        "evidence_as_of": NOW,
        "source_type": "ai",
        "created_at": NOW,
        "updated_at": NOW,
    })
    return AgentPrediction.model_validate(payload)


class _Store:
    def __init__(self, run: PredictionRun | None = None) -> None:
        self.run = run or _run()
        self.claimed = False
        self.market_context: Mapping[str, Any] | None = None
        self.success: dict[str, Any] | None = None
        self.failure: dict[str, Any] | None = None
        self.create_calls = 0

    def create_or_get_active(self, **_kwargs: Any) -> tuple[PredictionRun, bool]:
        self.create_calls += 1
        return self.run, self.create_calls == 1

    def claim(self, _run_id: str) -> PredictionRun | None:
        if self.claimed:
            return None
        self.claimed = True
        return self.run.model_copy(update={"status": "running"})

    def set_market_context(self, _run: PredictionRun, market: Mapping[str, Any]) -> None:
        self.market_context = market

    def get_by_anchor(self, **_kwargs: Any) -> None:
        return None

    def get_latest_prediction(self, **_kwargs: Any) -> None:
        return None

    def complete_success(
        self,
        run: PredictionRun,
        prediction: AgentPrediction,
        **kwargs: Any,
    ) -> None:
        self.success = {"run": run, "prediction": prediction, **kwargs}

    def complete_failure(self, run: PredictionRun, **kwargs: Any) -> None:
        self.failure = {"run": run, **kwargs}


class _Gateway:
    def __init__(self, market: Mapping[str, Any]) -> None:
        self.market = market
        self.kline_calls = 0
        self.news_calls = 0

    def get_kline(self, _symbol: str, **_kwargs: Any) -> Mapping[str, Any]:
        self.kline_calls += 1
        return self.market

    def get_news(self, _symbol: str, **_kwargs: Any) -> dict[str, Any]:
        self.news_calls += 1
        return {"quality": "trusted", "news": []}


def _observed_invoke(outputs: list[Any], prompts: list[str]):
    async def invoke(messages: Any, *, context: Any, **_kwargs: Any) -> Any:
        prompts.append(messages[0].content)
        attempt = context.budget.reserve_provider_attempt()
        value = outputs[attempt - 1]
        status = "failed" if isinstance(value, BaseException) else "success"
        context.on_attempt({
            "attempt": attempt,
            "provider": "fixture-provider",
            "model": "fixture-model",
            "status": status,
            "prompt_tokens": 100 if status == "success" else None,
            "completion_tokens": 50 if status == "success" else None,
            "duration_ms": 20,
            "error_code": getattr(value, "code", None),
        })
        if isinstance(value, BaseException):
            raise value
        return type("Response", (), {"content": json.dumps(value, ensure_ascii=False)})()

    return invoke


@pytest.mark.asyncio
async def test_generate_returns_queued_run_without_market_or_llm_and_reuses_active_run():
    store = _Store()
    gateway = _Gateway(_market())

    async def unexpected_llm(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("generate request must not call LLM")

    service = PredictionService(store=store, market_gateway=gateway, invoke_llm=unexpected_llm)
    scheduled: list[str] = []
    service._schedule = scheduled.append  # type: ignore[method-assign]

    started = perf_counter()
    first, first_created = await service.generate(user_id="alice", symbol="aapl")
    second, second_created = await service.generate(user_id="alice", symbol="AAPL")

    assert perf_counter() - started < 0.5
    assert first.status == second.status == "queued"
    assert first.id == second.id == RUN_ID
    assert (first_created, second_created) == (True, False)
    assert scheduled == [RUN_ID]
    assert gateway.kline_calls == gateway.news_calls == 0


@pytest.mark.asyncio
async def test_scheduler_thread_enqueue_uses_the_running_service_loop():
    store = _Store()
    service = PredictionService(store=store, market_gateway=_Gateway(_market()))
    scheduled: list[str] = []
    service._schedule = scheduled.append  # type: ignore[method-assign]
    service._loop = asyncio.get_running_loop()

    first, first_created = await asyncio.to_thread(
        service.enqueue,
        user_id="alice",
        symbol="aapl",
    )
    second, second_created = await asyncio.to_thread(
        service.enqueue,
        user_id="alice",
        symbol="AAPL",
    )
    await asyncio.sleep(0)

    assert first.id == second.id == RUN_ID
    assert (first_created, second_created) == (True, False)
    assert scheduled == [RUN_ID]


@pytest.mark.asyncio
async def test_prediction_contract_gets_one_correction_and_never_exceeds_two_provider_attempts(monkeypatch):
    store = _Store()
    gateway = _Gateway(_market())
    prompts: list[str] = []
    invoke = _observed_invoke([_draft_payload(valid=False), _draft_payload(valid=True)], prompts)
    monkeypatch.setattr("backend.services.prediction_service._compute_indicators", lambda _bars: {"rsi": 55})
    service = PredictionService(store=store, market_gateway=gateway, invoke_llm=invoke)

    await service._process_run(RUN_ID)

    assert store.failure is None
    assert store.success is not None
    assert len(prompts) == 2
    assert "逐项修正" in prompts[1]
    assert len(store.success["attempts"]) == 2
    prediction = store.success["prediction"]
    assert prediction.symbol == "AAPL"
    assert prediction.agent == "prediction_analyst"
    assert prediction.evidence_provider == "fixture-provider"
    assert prediction.source_type == "ai"


@pytest.mark.asyncio
async def test_two_invalid_contracts_fail_without_a_third_provider_attempt(monkeypatch):
    store = _Store()
    prompts: list[str] = []
    invoke = _observed_invoke([_draft_payload(valid=False), _draft_payload(valid=False)], prompts)
    monkeypatch.setattr("backend.services.prediction_service._compute_indicators", lambda _bars: {"rsi": 55})
    service = PredictionService(store=store, market_gateway=_Gateway(_market()), invoke_llm=invoke)

    await service._process_run(RUN_ID)

    assert store.success is None
    assert store.failure is not None
    assert store.failure["failure_code"] == PREDICTION_VALIDATION_FAILED
    assert len(store.failure["attempts"]) == len(prompts) == 2


@pytest.mark.asyncio
async def test_invalid_contract_then_exhausted_correction_stays_validation_failure(monkeypatch):
    store = _Store()
    prompts: list[str] = []
    invoke = _observed_invoke([_draft_payload(valid=False), TimeoutError("provider timeout")], prompts)
    monkeypatch.setattr("backend.services.prediction_service._compute_indicators", lambda _bars: {"rsi": 55})
    service = PredictionService(store=store, market_gateway=_Gateway(_market()), invoke_llm=invoke)

    await service._process_run(RUN_ID)

    assert store.success is None
    assert store.failure is not None
    assert store.failure["failure_code"] == PREDICTION_VALIDATION_FAILED
    assert len(store.failure["attempts"]) == len(prompts) == 2


@pytest.mark.asyncio
async def test_untrusted_market_is_unavailable_and_never_calls_llm(monkeypatch):
    store = _Store()
    called = False

    async def unexpected_llm(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("untrusted market must stop before LLM")

    monkeypatch.setattr(
        "backend.services.prediction_service._compute_indicators",
        lambda _bars: (_ for _ in ()).throw(AssertionError("indicators must not run")),
    )
    service = PredictionService(
        store=store,
        market_gateway=_Gateway(_market(quality="degraded")),
        invoke_llm=unexpected_llm,
    )

    await service._process_run(RUN_ID)

    assert called is False
    assert store.success is None
    assert store.failure is not None
    assert store.failure["status"] == "unavailable"
    assert store.failure["failure_code"] == MARKET_DATA_UNAVAILABLE


@pytest.mark.asyncio
async def test_llm_authentication_failure_uses_stable_public_error_code(monkeypatch):
    class AuthenticationError(RuntimeError):
        status_code = 401
        code = "invalid_api_key"

    store = _Store()
    prompts: list[str] = []
    invoke = _observed_invoke([AuthenticationError("invalid api key")], prompts)
    monkeypatch.setattr("backend.services.prediction_service._compute_indicators", lambda _bars: {"rsi": 55})
    service = PredictionService(store=store, market_gateway=_Gateway(_market()), invoke_llm=invoke)

    await service._process_run(RUN_ID)

    assert len(prompts) == 1
    assert store.failure is not None
    assert store.failure["failure_code"] == "llm_authentication_failed"


@pytest.mark.asyncio
async def test_prediction_llm_attempt_timeout_leaves_budget_for_rotation():
    observed: dict[str, Any] = {}

    async def invoke(_messages: Any, **kwargs: Any) -> Any:
        observed.update(kwargs)
        return type("Response", (), {"content": "{}"})()

    service = PredictionService(
        store=_Store(),
        market_gateway=_Gateway(_market()),
        invoke_llm=invoke,
        llm_attempt_timeout_seconds=30,
    )
    from backend.services.llm_retry import LLMCallContext

    await service._invoke(
        "prediction prompt",
        context=LLMCallContext.create(stage="prediction", max_provider_attempts=2),
    )

    assert observed["request_timeout"] == 30
    assert observed["acquire_timeout_seconds"] == 10
    assert observed["endpoint_names"] == ("openai-compatible-primary",)


@pytest.mark.asyncio
async def test_optional_news_timeout_does_not_block_prediction(monkeypatch):
    class SlowNewsGateway(_Gateway):
        def get_news(self, _symbol: str, **_kwargs: Any) -> dict[str, Any]:
            import time

            time.sleep(0.2)
            return {"quality": "trusted", "news": []}

    store = _Store()
    prompts: list[str] = []
    monkeypatch.setattr("backend.services.prediction_service._compute_indicators", lambda _bars: {"rsi": 55})
    service = PredictionService(
        store=store,
        market_gateway=SlowNewsGateway(_market()),
        invoke_llm=_observed_invoke([_draft_payload(valid=True)], prompts),
        news_timeout_seconds=0.1,
    )

    await service._process_run(RUN_ID)

    assert store.failure is None
    assert store.success is not None
    assert len(prompts) == 1


class _RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: Any, params: Mapping[str, Any] | None = None) -> None:
        self.calls.append((str(statement), dict(params or {})))


class _RecordingEngine:
    def __init__(self) -> None:
        self.connection = _RecordingConnection()
        self.begin_count = 0

    @contextmanager
    def begin(self):
        self.begin_count += 1
        yield self.connection


def test_success_archive_writes_four_core_tables_in_one_transaction():
    engine = _RecordingEngine()
    store = PredictionRunStore(engine=engine)
    store.complete_success(
        _run(status="running"),
        _prediction(),
        attempts=[{
            "attempt": 1,
            "provider": "fixture-provider",
            "model": "fixture-model",
            "status": "success",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "duration_ms": 20,
            "error_code": None,
        }],
        latency_ms=25,
    )

    sql = "\n".join(statement for statement, _params in engine.connection.calls)
    assert engine.begin_count == 1
    for table in ("agent_predictions", "llm_usage", "agent_run_archive", "prediction_runs"):
        assert table in sql


def test_stats_separate_ai_and_manual_and_exclude_open_from_hit_rate():
    stats = _summarize_stats([
        {"source_type": "ai", "direction": "long", "status": "hit_target", "count": 3},
        {"source_type": "ai", "direction": "short", "status": "open", "count": 4},
        {"source_type": "manual", "direction": "short", "status": "hit_stop", "count": 2},
    ], days=90, symbol=None)

    assert stats["predictions"] == 9
    assert stats["resolved"] == 5
    assert stats["hit_rate"] == 0.6
    assert stats["by_source"]["ai"]["hit_rate"] == 1.0
    assert stats["by_source"]["manual"]["hit_rate"] == 0.0
