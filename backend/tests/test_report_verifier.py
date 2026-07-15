# -*- coding: utf-8 -*-
import asyncio
from types import SimpleNamespace


def test_deep_report_verifier_owns_provider_limits(monkeypatch):
    import backend.report.verifier as verifier

    captured = {}

    async def _fake_invoke(_messages, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content='{"unsupported_claims": []}')

    synth_helpers = SimpleNamespace(
        _env_bool=lambda _name, default: default,
        _env_int=lambda _name, default: default,
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
    assert captured["request_timeout"] == 45
    assert captured["acquire_timeout_seconds"] == 20.0
    assert captured["context"].budget.max_provider_attempts == 1
