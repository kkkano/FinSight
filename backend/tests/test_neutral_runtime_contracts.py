"""个人预测与历史 checkpoint 的中性宿主合同；只使用合成行情和假存储。"""
from __future__ import annotations

import asyncio
from importlib import import_module
from types import SimpleNamespace

import pytest

from backend.common import checkpoint_store, prediction_contract, prediction_submit


@pytest.mark.parametrize("module_name", [
    "backend.services.agent_prediction_store",
    "backend.services.monitor_commentator",
    "backend.services.monitor_signals",
    "backend.services.prediction_outcomes",
    "backend.services.prediction_service",
])
def test_personal_prediction_consumers_share_one_contract_class(module_name):
    assert import_module(module_name).AgentPrediction is prediction_contract.AgentPrediction


def test_registered_api_consumers_share_neutral_contracts():
    from backend.api import predictions_router, session_context

    assert predictions_router.PredictionAnchor is prediction_contract.PredictionAnchor
    assert predictions_router.PredictionScenario is prediction_contract.PredictionScenario
    assert session_context.adelete_graph_thread is checkpoint_store.adelete_graph_thread


def test_neutral_submission_preserves_server_identity_provenance_and_json_roundtrip():
    draft = {
        "symbol": "MODEL_SYMBOL", "agent": "model_agent", "direction": "long",
        "confidence": 0.8, "thesis": "合成行情测试",
        "anchor": {"timeframe": "1h", "time": "2026-07-10", "price": 102.0},
        "entry_type": "limit", "entry": 101.0, "stop": 96.0, "target1": 111.0,
        "invalidation_price": 95.0,
        "scenarios": [
            {"name": "延续", "probability": 60, "invalidation": "跌破止损"},
            {"name": "失败", "probability": 40, "invalidation": "突破目标"},
        ],
    }
    anchor_bar = {"time": "2026-07-10", "open": 100, "high": 103, "low": 99, "close": 102}
    market = {
        "kline_data": [anchor_bar], "interval": "1d", "quality": "trusted",
        "provider": "fixture", "as_of": "2026-07-10T20:00:00Z",
    }
    stored = []
    fetched = []

    def fetch_bars(symbol, **kwargs):
        fetched.append((symbol, kwargs))
        return market

    def create(prediction):
        assert isinstance(prediction, prediction_contract.AgentPrediction)
        stored.append(prediction)
        return prediction

    prediction, trace = asyncio.run(prediction_submit.submit_prediction_with_async_correction(
        lambda _feedback: draft,
        symbol="aapl", agent="prediction_analyst", user_id="alice", run_id="fixture-run",
        operation="technical", fetch_bars=fetch_bars, store=SimpleNamespace(create=create),
        prompt_version="fixture-version",
    ))

    assert prediction is stored[0]
    assert trace == [{"attempt": 1, "ok": True, "issues": []}]
    assert fetched == [("AAPL", {"period": "1mo", "interval": "1d"})]
    assert (prediction.symbol, prediction.agent, prediction.user_id, prediction.run_id) == (
        "AAPL", "prediction_analyst", "alice", "fixture-run",
    )
    assert prediction.anchor.model_dump() == {"timeframe": "1d", "time": "2026-07-10", "price": 102.0}
    assert prediction.prompt_version == "fixture-version"
    assert prediction.evidence_provider == "fixture"
    assert prediction.evidence_as_of.isoformat() == "2026-07-10T20:00:00+00:00"
    assert prediction.risk_reward == 2.0
    serialized = prediction.model_dump_json(exclude={"risk_reward"})
    assert prediction_contract.AgentPrediction.model_validate_json(serialized) == prediction

    outcome = prediction_submit.evaluate_prediction_bars(
        draft,
        [anchor_bar, {"time": "2026-07-11", "open": 101, "high": 112, "low": 95, "close": 108}],
    )
    assert outcome.status == "hit_stop"
    assert outcome.entry_price == 101.0


def test_checkpoint_async_cache_delete_and_close_share_one_bundle(monkeypatch):
    created = []
    deleted = []
    closed = []
    sync_closed = []
    for name in ("_async_bundle", "_async_lock", "_async_bundle_loop_id"):
        monkeypatch.setattr(checkpoint_store, name, None)

    class Saver:
        async def adelete_thread(self, thread_id):
            deleted.append(thread_id)

    class AsyncContext:
        async def __aexit__(self, *args):
            closed.append(args)

    async def build_bundle():
        bundle = checkpoint_store.CheckpointerBundle(
            saver=Saver(),
            info=checkpoint_store.CheckpointerInfo(
                schema_version=checkpoint_store.CHECKPOINTER_SCHEMA_VERSION,
                backend="memory", persistent=False, location=None,
                fallback_used=False, fallback_reason=None,
            ),
            _async_cm=AsyncContext(),
        )
        created.append(bundle)
        await asyncio.sleep(0)
        return bundle

    def sync_bundle():
        return SimpleNamespace(close=lambda: sync_closed.append(True))

    sync_bundle.cache_clear = lambda: None
    monkeypatch.setattr(checkpoint_store, "_build_async_bundle", build_bundle)
    monkeypatch.setattr(checkpoint_store, "get_checkpointer_bundle", sync_bundle)

    async def scenario():
        first, second = await asyncio.gather(
            checkpoint_store.aget_checkpointer_bundle(), checkpoint_store.aget_checkpointer_bundle(),
        )
        assert first is second
        assert len(created) == 1
        assert await checkpoint_store.adelete_graph_thread(" public:alice:thread ") is True
        assert deleted == ["public:alice:thread"]
        assert checkpoint_store.get_graph_checkpointer_info()["backend"] == "memory"
        await checkpoint_store.areset_checkpointer_caches()
        assert closed == [(None, None, None)]
        assert checkpoint_store._async_bundle is None
        assert checkpoint_store._async_lock is None
        assert checkpoint_store._async_bundle_loop_id is None
        await first.aclose()
        assert closed == [(None, None, None)]

    asyncio.run(scenario())
    assert sync_closed == [True]


def test_checkpoint_delete_keeps_sync_saver_support(monkeypatch):
    deleted = []

    async def get_saver():
        return SimpleNamespace(delete_thread=deleted.append)

    monkeypatch.setattr(checkpoint_store, "aget_graph_checkpointer", get_saver)
    assert asyncio.run(checkpoint_store.adelete_graph_thread("public:alice:thread")) is True
    assert deleted == ["public:alice:thread"]
