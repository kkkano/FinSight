# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import importlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest


def _reload_llm_config():
    import backend.llm_config as llm_config

    importlib.reload(llm_config)
    return llm_config


def _reset_manager(llm_config, endpoints):
    llm_config._ENDPOINT_MANAGER.endpoints = [  # type: ignore[attr-defined]
        llm_config.EndpointRuntime(cfg=ep) for ep in endpoints
    ]
    llm_config._ENDPOINT_MANAGER.fingerprint = 'test-fingerprint'  # type: ignore[attr-defined]


def test_single_endpoint_selection_and_config(monkeypatch):
    llm_config = _reload_llm_config()
    ep = llm_config.EndpointConfig(
        name='single',
        provider='openai_compatible',
        api_base='https://api.example.com/v1',
        api_key='sk-test-1234567890',
        model='gemini-2.5-flash',
        weight=1,
        enabled=True,
        cooldown_sec=10,
    )
    monkeypatch.setattr(llm_config, '_resolve_endpoints', lambda provider, model: [ep])

    cfg = llm_config.get_llm_config(provider='gemini_proxy', model=None)
    assert cfg['endpoint_name'] == 'single'
    assert cfg['provider'] == 'openai_compatible'
    assert cfg['model'] == 'gemini-2.5-flash'


def test_weighted_round_robin_order():
    llm_config = _reload_llm_config()
    ep_a = llm_config.EndpointConfig(
        name='a',
        provider='openai_compatible',
        api_base='https://a.example.com/v1',
        api_key='sk-a-1234567890',
        model='m-a',
        weight=2,
        enabled=True,
        cooldown_sec=30,
    )
    ep_b = llm_config.EndpointConfig(
        name='b',
        provider='openai_compatible',
        api_base='https://b.example.com/v1',
        api_key='sk-b-1234567890',
        model='m-b',
        weight=1,
        enabled=True,
        cooldown_sec=30,
    )
    _reset_manager(llm_config, [ep_a, ep_b])

    order = [llm_config._ENDPOINT_MANAGER.select().name for _ in range(6)]  # type: ignore[attr-defined]
    assert order == ['a', 'b', 'a', 'a', 'b', 'a']


def test_failover_cools_down_primary_and_uses_backup(monkeypatch):
    llm_config = _reload_llm_config()
    now = {'t': 1000.0}
    monkeypatch.setattr(llm_config.time, 'time', lambda: now['t'])

    ep_a = llm_config.EndpointConfig(
        name='primary',
        provider='openai_compatible',
        api_base='https://a.example.com/v1',
        api_key='sk-a-1234567890',
        model='m-a',
        weight=1,
        enabled=True,
        cooldown_sec=60,
    )
    ep_b = llm_config.EndpointConfig(
        name='backup',
        provider='openai_compatible',
        api_base='https://b.example.com/v1',
        api_key='sk-b-1234567890',
        model='m-b',
        weight=1,
        enabled=True,
        cooldown_sec=60,
    )
    _reset_manager(llm_config, [ep_a, ep_b])

    first = llm_config._ENDPOINT_MANAGER.select().name  # type: ignore[attr-defined]
    assert first in ('primary', 'backup')

    llm_config._ENDPOINT_MANAGER.report_failure('primary', reason='429')  # type: ignore[attr-defined]

    second = llm_config._ENDPOINT_MANAGER.select().name  # type: ignore[attr-defined]
    assert second == 'backup'


def test_recovery_after_cooldown(monkeypatch):
    llm_config = _reload_llm_config()
    now = {'t': 1000.0}
    monkeypatch.setattr(llm_config.time, 'time', lambda: now['t'])

    ep = llm_config.EndpointConfig(
        name='primary',
        provider='openai_compatible',
        api_base='https://a.example.com/v1',
        api_key='sk-a-1234567890',
        model='m-a',
        weight=1,
        enabled=True,
        cooldown_sec=30,
    )
    _reset_manager(llm_config, [ep])

    llm_config._ENDPOINT_MANAGER.report_failure('primary', reason='timeout')  # type: ignore[attr-defined]
    runtime = llm_config._ENDPOINT_MANAGER.endpoints[0]  # type: ignore[attr-defined]
    assert runtime.cooldown_until == pytest.approx(1030.0)

    now['t'] = 1031.0
    llm_config._ENDPOINT_MANAGER.report_success('primary')  # type: ignore[attr-defined]
    assert runtime.cooldown_until == 0.0


def test_get_llm_config_raises_when_all_sources_empty(monkeypatch):
    llm_config = _reload_llm_config()
    monkeypatch.setattr(llm_config, '_load_user_config', lambda: {})
    monkeypatch.setattr(llm_config, '_parse_env_endpoints', lambda provider, model: [])

    with pytest.raises(ValueError) as exc:
        llm_config.get_llm_config(provider='openai_compatible', model=None)
    assert 'No LLM endpoint configured' in str(exc.value)


def test_retry_helper_reports_failure_and_success(monkeypatch):
    import backend.services.llm_retry as llm_retry

    calls: list[tuple[str, str | None]] = []

    async def _no_sleep(_seconds: float):
        return None

    monkeypatch.setattr(llm_retry, 'report_llm_success', lambda llm: calls.append(('ok', None)))
    monkeypatch.setattr(llm_retry, 'report_llm_failure', lambda llm, error=None: calls.append(('fail', str(error))))
    monkeypatch.setattr(llm_retry.asyncio, 'sleep', _no_sleep)

    class _FakeLLM:
        def __init__(self):
            self.n = 0

        async def ainvoke(self, messages):
            self.n += 1
            if self.n == 1:
                raise RuntimeError('429 too many requests')
            return {'ok': True}

    result = asyncio.run(
        llm_retry.ainvoke_with_rate_limit_retry(
            _FakeLLM(),
            messages=[{'role': 'user', 'content': 'hello'}],
            max_attempts=3,
            sleep_seconds=0,
            jitter_seconds=0,
            acquire_token=False,
        )
    )

    assert result == {'ok': True}
    assert calls[0][0] == 'fail'
    assert calls[-1][0] == 'ok'


def test_retry_helper_all_failures_raise_explainable_error(monkeypatch):
    import backend.services.llm_retry as llm_retry

    calls: list[tuple[str, str | None]] = []

    async def _no_sleep(_seconds: float):
        return None

    monkeypatch.setattr(llm_retry, 'report_llm_success', lambda llm: calls.append(('ok', None)))
    monkeypatch.setattr(llm_retry, 'report_llm_failure', lambda llm, error=None: calls.append(('fail', str(error))))
    monkeypatch.setattr(llm_retry.asyncio, 'sleep', _no_sleep)

    class _FakeLLM:
        async def ainvoke(self, messages):
            raise RuntimeError('429 all endpoints cooling down')

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            llm_retry.ainvoke_with_rate_limit_retry(
                _FakeLLM(),
                messages=[{'role': 'user', 'content': 'hello'}],
                max_attempts=2,
                sleep_seconds=0,
                jitter_seconds=0,
                acquire_token=False,
            )
        )

    assert '429' in str(exc.value)
    assert all(item[0] == 'fail' for item in calls)
    assert len(calls) == 2

def test_weighted_round_robin_distribution_under_concurrency():
    llm_config = _reload_llm_config()

    ep_primary = llm_config.EndpointConfig(
        name='primary',
        provider='openai_compatible',
        api_base='https://primary.example.com/v1',
        api_key='sk-primary-1234567890',
        model='m-primary',
        weight=3,
        enabled=True,
        cooldown_sec=30,
    )
    ep_backup = llm_config.EndpointConfig(
        name='backup',
        provider='openai_compatible',
        api_base='https://backup.example.com/v1',
        api_key='sk-backup-1234567890',
        model='m-backup',
        weight=1,
        enabled=True,
        cooldown_sec=30,
    )
    _reset_manager(llm_config, [ep_primary, ep_backup])

    total_calls = 400
    worker_count = 8
    calls_per_worker = total_calls // worker_count

    def _select_batch(batch: int) -> Counter[str]:
        counter: Counter[str] = Counter()
        for _ in range(batch):
            selected = llm_config._ENDPOINT_MANAGER.select().name  # type: ignore[attr-defined]
            counter[selected] += 1
        return counter

    total_counter: Counter[str] = Counter()
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_select_batch, calls_per_worker) for _ in range(worker_count)]
        for future in futures:
            total_counter.update(future.result())

    assert sum(total_counter.values()) == total_calls

    # Expected ratio is 3:1; allow small drift for concurrent scheduling.
    primary_ratio = total_counter['primary'] / total_calls
    backup_ratio = total_counter['backup'] / total_calls
    assert 0.70 <= primary_ratio <= 0.80
    assert 0.20 <= backup_ratio <= 0.30


def test_retry_rotates_endpoint_on_429(monkeypatch):
    """When llm_factory is provided, retry should create a new LLM on 429."""
    import backend.services.llm_retry as llm_retry

    async def _no_sleep(_seconds: float):
        return None

    monkeypatch.setattr(llm_retry, 'report_llm_success', lambda llm: None)
    monkeypatch.setattr(llm_retry, 'report_llm_failure', lambda llm, error=None: None)
    monkeypatch.setattr(llm_retry.asyncio, 'sleep', _no_sleep)

    factory_calls: list[int] = []

    class _FakeLLM:
        def __init__(self, name: str):
            self.name = name
            self.call_count = 0

        async def ainvoke(self, messages):
            self.call_count += 1
            if self.name == 'llm-1':
                raise RuntimeError('429 rate limit exceeded')
            return {'ok': True, 'from': self.name}

    llm_initial = _FakeLLM('llm-1')

    def _factory():
        factory_calls.append(1)
        return _FakeLLM('llm-2')

    result = asyncio.run(
        llm_retry.ainvoke_with_rate_limit_retry(
            llm_initial,
            messages=[{'role': 'user', 'content': 'hello'}],
            llm_factory=_factory,
            max_attempts=3,
            sleep_seconds=0,
            jitter_seconds=0,
            acquire_token=False,
        )
    )

    assert result == {'ok': True, 'from': 'llm-2'}
    assert len(factory_calls) == 1
    assert llm_initial.call_count == 1


def test_retry_rotates_endpoint_on_401_with_factory(monkeypatch):
    """With llm_factory, auth/provider errors should also rotate endpoints."""
    import backend.services.llm_retry as llm_retry

    sleep_calls: list[float] = []

    async def _sleep_recorder(seconds: float):
        sleep_calls.append(seconds)
        return None

    monkeypatch.setattr(llm_retry, 'report_llm_success', lambda llm: None)
    monkeypatch.setattr(llm_retry, 'report_llm_failure', lambda llm, error=None: None)
    monkeypatch.setattr(llm_retry.asyncio, 'sleep', _sleep_recorder)

    factory_calls: list[int] = []

    class _FakeLLM:
        def __init__(self, name: str):
            self.name = name
            self.call_count = 0

        async def ainvoke(self, messages):
            self.call_count += 1
            if self.name == 'llm-1':
                raise RuntimeError("Error code: 401 - {'error': {'message': '无效的令牌'}}")
            return {'ok': True, 'from': self.name}

    llm_initial = _FakeLLM('llm-1')

    def _factory():
        factory_calls.append(1)
        return _FakeLLM('llm-2')

    result = asyncio.run(
        llm_retry.ainvoke_with_rate_limit_retry(
            llm_initial,
            messages=[{'role': 'user', 'content': 'hello'}],
            llm_factory=_factory,
            max_attempts=3,
            sleep_seconds=5,
            jitter_seconds=1,
            acquire_token=False,
        )
    )

    assert result == {'ok': True, 'from': 'llm-2'}
    assert len(factory_calls) == 1
    assert llm_initial.call_count == 1
    assert sleep_calls == []


def test_retry_rotates_non_429_until_attempts_exhausted(monkeypatch):
    """With llm_factory, non-429 endpoint failures should still rotate and retry."""
    import backend.services.llm_retry as llm_retry

    async def _no_sleep(_seconds: float):
        return None

    monkeypatch.setattr(llm_retry, 'report_llm_success', lambda llm: None)
    monkeypatch.setattr(llm_retry, 'report_llm_failure', lambda llm, error=None: None)
    monkeypatch.setattr(llm_retry.asyncio, 'sleep', _no_sleep)

    factory_calls: list[int] = []

    class _AlwaysFailLLM:
        async def ainvoke(self, messages):
            raise RuntimeError('503 Service Unavailable: no available channel')

    def _factory():
        factory_calls.append(1)
        return _AlwaysFailLLM()

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(
            llm_retry.ainvoke_with_rate_limit_retry(
                _AlwaysFailLLM(),
                messages=[{'role': 'user', 'content': 'hello'}],
                llm_factory=_factory,
                max_attempts=3,
                sleep_seconds=0,
                jitter_seconds=0,
                acquire_token=False,
            )
        )

    assert '503' in str(exc.value)
    assert len(factory_calls) == 2


def test_retry_fallback_without_factory(monkeypatch):
    """When llm_factory is None, retry should reuse the same LLM (backward compat)."""
    import backend.services.llm_retry as llm_retry

    async def _no_sleep(_seconds: float):
        return None

    monkeypatch.setattr(llm_retry, 'report_llm_success', lambda llm: None)
    monkeypatch.setattr(llm_retry, 'report_llm_failure', lambda llm, error=None: None)
    monkeypatch.setattr(llm_retry.asyncio, 'sleep', _no_sleep)

    class _FakeLLM:
        def __init__(self):
            self.call_count = 0

        async def ainvoke(self, messages):
            self.call_count += 1
            if self.call_count < 3:
                raise RuntimeError('429 quota exceeded')
            return {'ok': True}

    llm = _FakeLLM()

    result = asyncio.run(
        llm_retry.ainvoke_with_rate_limit_retry(
            llm,
            messages=[{'role': 'user', 'content': 'hello'}],
            llm_factory=None,
            max_attempts=5,
            sleep_seconds=0,
            jitter_seconds=0,
            acquire_token=False,
        )
    )

    assert result == {'ok': True}
    assert llm.call_count == 3


def test_raw_url_preserved():
    """raw_url=True should preserve the full URL without stripping /chat/completions."""
    llm_config = _reload_llm_config()

    full_url = 'https://x666.me/v1/chat/completions'
    result = llm_config._normalize_api_base(full_url, raw=True)
    assert result == full_url

    result_default = llm_config._normalize_api_base(full_url, raw=False)
    assert result_default != full_url
    assert result_default.endswith('/v1')
    assert '/chat/completions' not in result_default
