import importlib
from types import SimpleNamespace

import pytest

from backend.services.model_selection import SelectedModel, STEP_BASE_URL, model_selection_scope


@pytest.mark.asyncio
@pytest.mark.parametrize("content,finish,error,expected", [
    ("", "length", None, "llm_output_truncated"), ("", "stop", None, "llm_empty_output"),
    ("{invalid", "stop", None, "llm_output_invalid"), (None, None, TimeoutError("fixture timeout"), "provider_timeout"),
])
async def test_synthesis_classifies_completion_separately_from_transport(monkeypatch, content, finish, error, expected):
    module = importlib.import_module("backend.graph.nodes.synthesize")
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")
    monkeypatch.setenv("FINSIGHT_STRUCTURED_SYNTHESIS", "off")
    monkeypatch.setattr("backend.llm_config.get_endpoint_manager", lambda *args, **kwargs: object())

    async def call(_messages, **kwargs):
        if error:
            raise error
        return SimpleNamespace(content=content, response_metadata={"finish_reason": finish, "model_name": "step-5-preview"})

    monkeypatch.setattr(module, "ainvoke_configured_llm", call)
    result = await module.synthesize({"query": "INTC 最新基本面分析", "output_mode": "chat",
        "operation": {"name": "analysis", "params": {}}, "subject": {"subject_type": "company", "tickers": ["INTC"]},
        "artifacts": {"step_results": {}, "evidence_pool": []}, "trace": {}})
    runtime = result["trace"]["synthesize_runtime"]
    assert runtime["reason"] == expected
    assert runtime["fallback"] is True


@pytest.mark.asyncio
async def test_step_synthesis_preserves_large_budget_json_mode_and_final_text(monkeypatch):
    module = importlib.import_module("backend.graph.nodes.synthesize")
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")
    monkeypatch.setenv("FINSIGHT_STRUCTURED_SYNTHESIS", "off")
    monkeypatch.delenv("LANGGRAPH_SYNTHESIZE_MAX_TOKENS", raising=False)
    monkeypatch.setattr("backend.llm_config.get_endpoint_manager", lambda *args, **kwargs: object())
    captured = {}

    async def call(_messages, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content=[{"type": "thinking", "thinking": "hidden"}, {"type": "text",
            "text": '{"conclusion":"存在公开数据缺口，需要核验。","impact_analysis":"已按证据分析。","risks":"数据有限"}'}],
            response_metadata={"finish_reason": "stop", "model_name": "step-5-preview"})

    monkeypatch.setattr(module, "ainvoke_configured_llm", call)
    selected = SelectedModel("system", "step-5-preview", STEP_BASE_URL, "private-fixture-key", effort="medium")
    with model_selection_scope(selected):
        result = await module.synthesize({"query": "INTC 分析", "output_mode": "chat", "operation": {"name": "analysis", "params": {}},
            "subject": {"subject_type": "company", "tickers": ["INTC"]}, "artifacts": {"step_results": {}, "evidence_pool": []}, "trace": {}})
    assert captured["max_tokens"] == 65536
    assert captured["request_timeout"] == 1200
    class Client:
        def bind(self, **params):
            return params
    assert captured["client_transform"](Client()) == {"response_format": {"type": "json_object"}}
    assert result["trace"]["synthesize_runtime"]["fallback"] is False
    assert "hidden" not in str(result["artifacts"]["render_vars"])
