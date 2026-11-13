# -*- coding: utf-8 -*-
import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("request_timeout,max_tokens", [(1200, 8192), (1800, 65536)])
def test_deep_report_verifier_respects_large_provider_budget(monkeypatch, request_timeout, max_tokens):
    import backend.report.verifier as verifier

    captured = {}
    monkeypatch.setenv("LANGGRAPH_DEEP_VERIFIER_REQUEST_TIMEOUT_SECONDS", str(request_timeout))
    monkeypatch.setenv("LANGGRAPH_DEEP_VERIFIER_ACQUIRE_TIMEOUT_SECONDS", "120")

    async def _fake_invoke(_messages, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content='{"unsupported_claims": []}')

    synth_helpers = SimpleNamespace(
        _env_bool=lambda _name, default: default,
        _env_int=lambda name, default: max_tokens if name == "LANGGRAPH_DEEP_VERIFIER_MAX_TOKENS" else default,
        _extract_json_object=lambda value: value,
        _is_deep_research_run=lambda _state: True,
    )
    monkeypatch.setattr(verifier, "_synth", lambda: synth_helpers)
    monkeypatch.setattr(verifier, "ainvoke_configured_llm", _fake_invoke)

    result = asyncio.run(
        verifier._run_deep_report_verifier(
            state={"output_mode": "investment_report"},
            generated_text="A supported report claim.",
            grounding_text="A supported report claim.",
        )
    )

    assert result["checked"] is True
    assert captured["request_timeout"] == request_timeout
    assert captured["max_tokens"] == max_tokens
    assert captured["acquire_timeout_seconds"] == 120.0
    assert captured["context"].budget.max_provider_attempts == 1
