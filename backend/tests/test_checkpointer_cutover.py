from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services import checkpointer_cutover


def test_run_checkpointer_cutover_drill_success(monkeypatch):
    calls: list[str] = []

    def fake_probe_backend(*, backend: str, sqlite_path: str, postgres_dsn: str, pipeline: bool, allow_fallback: bool):
        calls.append(backend)
        return {
            'backend': backend,
            'persistent': backend in {'sqlite', 'postgres'},
            'fallback_used': False,
            'fallback_reason': None,
            'location': sqlite_path if backend == 'sqlite' else 'postgresql://***@localhost:5432/finsight',
        }

    monkeypatch.setattr(checkpointer_cutover, '_probe_backend', fake_probe_backend)

    result = checkpointer_cutover.run_checkpointer_cutover_drill(
        sqlite_path='data/langgraph/checkpoints.sqlite',
        postgres_dsn='postgresql://user:pass@localhost:5432/finsight',
        pipeline=True,
        allow_fallback=False,
    )

    assert result['ok'] is True
    assert calls == ['sqlite', 'postgres', 'sqlite']
    assert [step['status'] for step in result['steps']] == ['pass', 'pass', 'pass']
    assert result['config']['postgres_dsn'].startswith('postgresql://***@')


def test_run_checkpointer_cutover_drill_postgres_failure(monkeypatch):
    calls: list[str] = []

    def fake_probe_backend(*, backend: str, sqlite_path: str, postgres_dsn: str, pipeline: bool, allow_fallback: bool):
        calls.append(backend)
        if backend == 'postgres':
            raise RuntimeError('postgres unavailable')
        return {
            'backend': backend,
            'persistent': True,
            'fallback_used': False,
            'fallback_reason': None,
            'location': sqlite_path,
        }

    monkeypatch.setattr(checkpointer_cutover, '_probe_backend', fake_probe_backend)

    result = checkpointer_cutover.run_checkpointer_cutover_drill(
        sqlite_path='data/langgraph/checkpoints.sqlite',
        postgres_dsn='postgresql://user:pass@localhost:5432/finsight',
    )

    assert result['ok'] is False
    assert calls == ['sqlite', 'postgres', 'sqlite']
    assert result['steps'][1]['step'] == 'postgres_cutover'
    assert result['steps'][1]['status'] == 'failed'
    assert 'postgres unavailable' in result['steps'][1]['error']


def test_write_checkpointer_drill_evidence(tmp_path: Path):
    payload = {
        'ok': True,
        'steps': [{'step': 'sqlite_precheck', 'status': 'pass'}],
    }
    out = tmp_path / 'evidence' / 'checkpointer_switch_drill.json'

    actual = checkpointer_cutover.write_checkpointer_drill_evidence(payload, out)

    assert actual == out.resolve()
    loaded = json.loads(actual.read_text(encoding='utf-8'))
    assert loaded['ok'] is True
    assert loaded['steps'][0]['step'] == 'sqlite_precheck'
