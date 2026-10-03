"""同一请求的取数去重与替代来源失败语义。"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

from backend.graph.execution.request_data import RequestData, SharedToolView, request_data_scope
from backend.graph.dag_executor import execute_plan_dag


def test_concurrent_consumers_share_one_fetch_and_receive_independent_values():
    data = RequestData()
    entered = Event()
    release = Event()
    count = []
    def fetch():
        count.append(1)
        entered.set()
        assert release.wait(2)
        return {"price": 123}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(data.call, "quote", {"ticker": "AAPL"}, fetch)
        assert entered.wait(2)
        second = pool.submit(data.call, "quote", {"ticker": "AAPL"}, fetch)
        release.set()
        one, two = first.result(), second.result()
    one["price"] = 1
    assert two["price"] == 123
    assert count == [1]
    assert data.reused == 1


def test_agent_tool_view_normalizes_defaults_and_does_not_cross_runs():
    calls = []
    def news(ticker, limit=5):
        calls.append(ticker)
        return [ticker]
    with request_data_scope() as data:
        view = SharedToolView(SimpleNamespace(news=news), data)
        assert view.news("AAPL") == view.news(ticker="AAPL", limit=5)
    with request_data_scope() as data:
        assert SharedToolView(SimpleNamespace(news=news), data).news("AAPL") == ["AAPL"]
    assert calls == ["AAPL", "AAPL"]


def test_agent_receives_finished_data_even_when_one_alternative_source_failed():
    observed = []
    async def bad(_):
        raise ConnectionError("fixture outage")
    async def good(_):
        return {"price": 123}
    async def agent(inputs):
        observed.extend(inputs["__evidence_inputs"])
        return {"summary": "可用事实仍为123"}
    plan = {"steps": [
        {"id": "agent", "kind": "agent", "name": "agent", "inputs": {}, "depends_on": [], "data_dependencies": ["bad", "good"]},
        {"id": "bad", "kind": "tool", "name": "bad", "inputs": {}, "optional": False, "depends_on": []},
        {"id": "good", "kind": "tool", "name": "good", "inputs": {}, "depends_on": []},
    ]}
    artifacts, _ = asyncio.run(execute_plan_dag(plan, tool_invokers={"bad": bad, "good": good},
        agent_invokers={"agent": agent}, dry_run=False))
    assert artifacts["step_results"]["agent"]["output"]["summary"] == "可用事实仍为123"
    assert next(row for row in observed if row["step_id"] == "good")["output"] == {"price": 123}
