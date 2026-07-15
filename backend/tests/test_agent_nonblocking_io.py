"""回归：慢速同步数据源不得阻塞 ASGI 事件循环。"""

from __future__ import annotations

import asyncio
import threading

import pytest

from backend.agents.fundamental_agent import FundamentalAgent
from backend.agents.macro_agent import MacroAgent
from backend.agents.price_agent import PriceAgent
from backend.graph.trace import with_node_trace
from backend.rag import execution_pipeline


class _Cache:
    def get(self, _key):
        return None

    def set(self, _key, _value, _ttl=None, **_kwargs):
        return None


async def _assert_event_loop_stays_responsive(coro, started: threading.Event) -> None:
    task = asyncio.create_task(coro)
    assert await asyncio.to_thread(started.wait, 0.5)

    loop = asyncio.get_running_loop()
    start = loop.time()
    await asyncio.sleep(0.02)
    elapsed = loop.time() - start

    assert elapsed < 0.15
    await task


def _slow_result(started: threading.Event, result):
    started.set()
    threading.Event().wait(0.3)
    return result


@pytest.mark.asyncio
async def test_macro_sync_tool_does_not_block_event_loop() -> None:
    started = threading.Event()

    class Tools:
        def search(self, _query):
            return _slow_result(started, "CPI 2.5%, federal funds rate 4.5%")

    agent = MacroAgent(None, _Cache(), Tools())
    await _assert_event_loop_stays_responsive(agent._initial_search("macro", "NVDA"), started)


@pytest.mark.asyncio
async def test_price_sync_source_does_not_block_event_loop() -> None:
    started = threading.Event()

    class Tools:
        def _fetch_with_yfinance(self, ticker):
            return _slow_result(started, {"ticker": ticker, "price": 123.0})

    agent = PriceAgent(None, _Cache(), Tools())
    await _assert_event_loop_stays_responsive(agent._fetch_from_source("yfinance", "NVDA"), started)


@pytest.mark.asyncio
async def test_fundamental_sync_tool_does_not_block_event_loop() -> None:
    started = threading.Event()

    class Tools:
        def get_financial_statements(self, ticker):
            return _slow_result(started, {"ticker": ticker, "error": "unavailable"})

    agent = FundamentalAgent(None, _Cache(), Tools())
    await _assert_event_loop_stays_responsive(agent._initial_search("fundamental", "NVDA"), started)


@pytest.mark.asyncio
async def test_sync_graph_node_does_not_block_event_loop() -> None:
    started = threading.Event()

    def slow_node(_state):
        return _slow_result(started, {"result": "done"})

    wrapped = with_node_trace("test_sync_node", slow_node)
    await _assert_event_loop_stays_responsive(wrapped({}), started)


@pytest.mark.asyncio
async def test_rag_service_initialization_does_not_block_event_loop(monkeypatch) -> None:
    started = threading.Event()

    class FakePriority:
        value = "normal"

    class FakeRagService:
        fallback_reason = None
        backend_name = "memory"

        def ingest_documents(self, _docs):
            return {"indexed": 0, "skipped": 0}

        def hybrid_search(self, *_args, **_kwargs):
            return []

        def hybrid_search_many(self, *_args, **_kwargs):
            return []

        def cleanup_expired(self):
            return 0

    def slow_get_rag_service():
        return _slow_result(started, FakeRagService())

    monkeypatch.setattr("backend.rag.hybrid_service.get_rag_service", slow_get_rag_service)
    monkeypatch.setattr("backend.rag.rag_router.decide_rag_priority", lambda **_kwargs: FakePriority())
    monkeypatch.setattr("backend.rag.observability_store.get_rag_observability_store", lambda: None)

    coro = execution_pipeline.run_execution_rag_pipeline(
        state={"query": "NVDA", "thread_id": "test:nonblocking"},
        subject={},
        deduped=[{"source_id": "source-1", "text": "evidence"}],
        step_index={},
        artifacts={},
        evidence_input_count=1,
    )
    await _assert_event_loop_stays_responsive(coro, started)
