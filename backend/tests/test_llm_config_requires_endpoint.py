from __future__ import annotations

import pytest


_OPENAI_COMPATIBLE_ENV = (
    "OPENAI_COMPATIBLE_API_BASE",
    "OPENAI_COMPATIBLE_API_KEY",
    "OPENAI_COMPATIBLE_MODEL",
    "GEMINI_PROXY_API_BASE",
    "GEMINI_PROXY_API_KEY",
    "OPENAI_API_BASE",
    "OPENAI_API_KEY",
    "ANYSCALE_API_BASE",
    "ANYSCALE_API_KEY",
    "ANTHROPIC_API_BASE",
    "ANTHROPIC_API_KEY",
)


def _clear_endpoint_sources(monkeypatch, llm_config) -> None:
    for key in _OPENAI_COMPATIBLE_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(llm_config, "_load_user_config", lambda: {})


def test_create_llm_fails_loudly_without_endpoint(monkeypatch):
    from backend import llm_config

    _clear_endpoint_sources(monkeypatch, llm_config)

    with pytest.raises(RuntimeError, match="OPENAI_COMPATIBLE_API_BASE"):
        llm_config.create_llm()


def test_openai_compatible_key_does_not_enable_implicit_base_or_model(monkeypatch):
    from backend import llm_config

    _clear_endpoint_sources(monkeypatch, llm_config)
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="OPENAI_COMPATIBLE_MODEL"):
        llm_config.get_llm_config(provider="openai_compatible")
