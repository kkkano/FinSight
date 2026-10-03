from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.services import model_preflight, model_selection


@pytest.mark.asyncio
async def test_probe_uses_exact_selection_and_closes_clients(monkeypatch):
    selected = model_selection.SelectedModel("custom", "step-5-preview", model_selection.STEP_BASE_URL,
                                              "fixture-private-key", "user-custom", "high")
    client = AsyncMock()
    calls = []

    def make_llm(cfg, **kwargs):
        calls.append((cfg, kwargs, model_selection.current_model()))
        model_selection.track_model_client(client)
        return SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="OK", response_metadata={"finish_reason": "stop"})))

    monkeypatch.setattr(model_preflight, "create_llm_for_endpoint", make_llm)
    with model_selection.model_selection_scope(selected):
        await model_preflight.ensure_model_available()
        assert model_selection.current_model() is selected
    cfg, kwargs, pinned = calls[0]
    assert cfg.model == selected.model and cfg.api_base == selected.base_url and cfg.api_key == selected.api_key
    assert pinned.effort == "high"
    assert kwargs["max_tokens"] == 65536 and kwargs["request_timeout"] == 60
    client.aclose.assert_awaited_once()
    assert model_selection.current_model() is None


@pytest.mark.parametrize("status", [401, 403, 429, 502, 503])
@pytest.mark.asyncio
async def test_probe_failure_does_not_retry_or_expose_provider_text(monkeypatch, status):
    class ProviderError(Exception):
        status_code = status

    invoke = AsyncMock(side_effect=ProviderError("fixture-private-key secret upstream response"))
    monkeypatch.setattr(model_preflight, "create_llm_for_endpoint", lambda *args, **kwargs: SimpleNamespace(ainvoke=invoke))
    selected = model_selection.SelectedModel("system", "step-5-preview", model_selection.STEP_BASE_URL, "fixture-private-key")
    with model_selection.model_selection_scope(selected), pytest.raises(HTTPException) as caught:
        await model_preflight.ensure_model_available()
    assert caught.value.status_code == 503
    assert caught.value.detail == {"code": "model_unavailable", "message": model_preflight.MODEL_UNAVAILABLE_MESSAGE}
    assert "fixture-private-key" not in str(caught.value.detail)
    invoke.assert_awaited_once()


@pytest.mark.parametrize("content,finish", [("", "stop"), ("   ", "stop"), ("OK", "length")])
@pytest.mark.asyncio
async def test_empty_or_truncated_probe_is_not_success(monkeypatch, content, finish):
    invoke = AsyncMock(return_value=SimpleNamespace(content=content, response_metadata={"finish_reason": finish}))
    monkeypatch.setattr(model_preflight, "create_llm_for_endpoint", lambda *args, **kwargs: SimpleNamespace(ainvoke=invoke))
    selected = model_selection.SelectedModel("custom", "own-model", "https://example.com/v1", "fixture-private-key")
    with model_selection.model_selection_scope(selected), pytest.raises(HTTPException) as caught:
        await model_preflight.ensure_model_available()
    assert caught.value.detail["code"] == "model_unavailable"


@pytest.mark.asyncio
async def test_probe_timeout_stops_and_closes_client(monkeypatch):
    client = AsyncMock()

    async def invoke(_message):
        await asyncio.sleep(10)

    def make_llm(*args, **kwargs):
        model_selection.track_model_client(client)
        return SimpleNamespace(ainvoke=invoke)

    monkeypatch.setattr(model_preflight, "PREFLIGHT_TIMEOUT_SECONDS", .01)
    monkeypatch.setattr(model_preflight, "create_llm_for_endpoint", make_llm)
    selected = model_selection.SelectedModel("system", "own-model", "https://example.com/v1", "fixture-private-key")
    with model_selection.model_selection_scope(selected), pytest.raises(HTTPException) as caught:
        await model_preflight.ensure_model_available()
    assert caught.value.status_code == 503
    client.aclose.assert_awaited_once()
