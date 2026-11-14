import asyncio
import time
from types import SimpleNamespace

import pytest

from backend.agent_runtime.config import ModelConfig
from backend.agent_runtime.limits import LeaseLimiter, TokenReservations
from backend.agent_runtime.model import BudgetedModel, ModelProtocolError
from backend.services.run_context import RunContext
from .grading_transport import EvaluationBudgetedModel, retrying_quota_transport_class


def fixture_factory(outcomes):
    class Transport:
        def __init__(self, config):
            self.config = config
            self.count = 0
            self.inputs = []

        async def stream(self, messages, tools, **kwargs):
            self.inputs.append((messages, tools))
            result = outcomes[self.count]
            self.count += 1
            for item in result:
                if isinstance(item, Exception):
                    raise item
                yield item
    return lambda _path, _attempts: Transport


def test_failed_partial_network_response_is_not_duplicated_into_successful_read():
    events = []
    factory = fixture_factory([[{'partial': True}, ModelProtocolError('model_connection_error')],
                               [{'score': 1}, {'complete': True}]])
    transport = retrying_quota_transport_class(None, [], events, retry_delay=0, transport_factory=factory)(SimpleNamespace())
    async def run():
        return [item async for item in transport.stream([{'role': 'user', 'content': 'fixed'}], [])]
    assert asyncio.run(run()) == [{'score': 1}, {'complete': True}]
    assert transport.inputs[0] == transport.inputs[1] and transport.count == 2
    assert events[0]['discarded_incomplete_chunks'] == 1


def test_authentication_error_is_not_retried_or_hidden():
    factory = fixture_factory([[ModelProtocolError('model_http_401')]])
    transport = retrying_quota_transport_class(None, [], [], retry_delay=0, transport_factory=factory)(SimpleNamespace())
    async def run():
        return [item async for item in transport.stream([], [])]
    with pytest.raises(ModelProtocolError, match='model_http_401'):
        asyncio.run(run())
    assert transport.count == 1


def test_successful_low_score_is_not_retried():
    factory = fixture_factory([[{'score': 1}]])
    transport = retrying_quota_transport_class(None, [], [], retry_delay=0, transport_factory=factory)(SimpleNamespace())
    async def run():
        return [item async for item in transport.stream([], [])]
    assert asyncio.run(run()) == [{'score': 1}] and transport.count == 1


def test_connection_attempts_are_bounded():
    factory = fixture_factory([[ModelProtocolError('model_connection_error')]] * 3)
    transport = retrying_quota_transport_class(None, [], [], retry_delay=0, transport_factory=factory)(SimpleNamespace())
    async def run():
        return [item async for item in transport.stream([], [])]
    with pytest.raises(ModelProtocolError, match='model_connection_error'):
        asyncio.run(run())
    assert transport.count == 3


def test_evaluation_relaxes_network_wait_without_changing_production_or_token_settlement(tmp_path, monkeypatch):
    monkeypatch.setenv('FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS', '0')
    received = []

    class Target:
        config = ModelConfig('test-model', 'https://test.invalid/v1', 'test-placeholder',
                             context_window=131072, max_output=8192)

        async def stream(self, messages, tools, **kwargs):
            received.append(kwargs['timeout'])
            yield {'choices': [{'finish_reason': 'stop'}],
                   'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}

    async def run(model_class):
        target = Target()
        context = RunContext(owner='grading-test', entry='judge', deadline=time.monotonic() + 360)
        context.quota_checker = lambda _owner: None
        runtime = SimpleNamespace(context=context, budget=TokenReservations(160000),
            limiter=LeaseLimiter(tmp_path / 'quota.sqlite'), model=target, model_duration_seconds={})
        spec = SimpleNamespace(model=target, agent_id='judge', role='judge')
        result = [chunk async for chunk in model_class(runtime, spec).stream([], [], timeout=240)]
        assert result and runtime.budget.spent == 15 and runtime.budget.reserved == 0

    asyncio.run(run(EvaluationBudgetedModel))
    asyncio.run(run(BudgetedModel))
    assert received == [240, 90]
