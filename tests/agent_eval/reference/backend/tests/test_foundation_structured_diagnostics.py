# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.graph.synthesis.research_synthesis import _TaskSynthesisSelection, _failure_code, _invoke_structured, _response_payload
from backend.services.llm_response import LLMCompletionError
from backend.services.llm_retry import LLMCallContext


def _selection():
    return _TaskSynthesisSelection(claim_ids=[], conclusion_claim_id=None, proposed_direction=None, direction_supporting_claim_ids=[], fact_ids=["source"])


@pytest.mark.parametrize("content,finish,code", [
    ('{"fact_ids":', "length", "llm_output_truncated"),
    ("", "stop", "llm_empty_output"),
    ("<think>只有思考内容。</think>", "stop", "llm_empty_output"),
])
def test_structured_raw_completion_keeps_terminal_failure_classification(content, finish, code):
    raw = SimpleNamespace(content=content, response_metadata={"finish_reason": finish}, tool_calls=[])
    with pytest.raises(LLMCompletionError) as error:
        _response_payload({"raw": raw, "parsed": None, "parsing_error": None})
    assert error.value.code == code and _failure_code(error.value) == code


def test_valid_parsed_tool_call_is_not_rejected_for_empty_message_content():
    raw = SimpleNamespace(content="", response_metadata={"finish_reason": "tool_calls"}, tool_calls=[{"name": "result", "args": {}}])
    parsed = _selection()
    assert _response_payload({"raw": raw, "parsed": parsed, "parsing_error": None}) is parsed


def test_length_always_rejects_even_when_sdk_supplies_a_parsed_tool_call():
    raw = SimpleNamespace(content="", response_metadata={"finish_reason": "length"}, tool_calls=[{"name": "result"}])
    with pytest.raises(LLMCompletionError, match="llm_output_truncated"):
        _response_payload({"raw": raw, "parsed": _selection(), "parsing_error": None})


def test_provider_5xx_and_timeout_are_not_collapsed_to_unavailable():
    class ProviderError(RuntimeError):
        status_code = 503
    assert _failure_code(ProviderError("upstream unavailable")) == "llm_provider_5xx"
    assert _failure_code(TimeoutError("timeout")) == "llm_timeout"


@pytest.mark.asyncio
async def test_structured_method_and_raw_envelope_are_explicit_without_resetting_budget(monkeypatch):
    module = __import__("backend.graph.synthesis.research_synthesis", fromlist=["unused"])
    observed = []
    context = LLMCallContext.create(stage="fixture", max_provider_attempts=1)

    class Client:
        def with_structured_output(self, schema, **kwargs):
            observed.append(kwargs)
            return self

    async def invoke(_messages, **kwargs):
        kwargs["context"].budget.reserve_provider_attempt()
        kwargs["client_transform"](Client())
        return {"raw": SimpleNamespace(content='{"fact_ids":["source"]}', response_metadata={"finish_reason": "stop"}, tool_calls=[]), "parsed": _selection(), "parsing_error": None}

    monkeypatch.setattr(module, "ainvoke_configured_llm", invoke)
    monkeypatch.setenv("LANGGRAPH_STRUCTURED_SYNTHESIS_METHOD", "json_schema")
    result = await _invoke_structured(prompt="已有事实", context=context, schema=_TaskSynthesisSelection, stage="fixture")
    assert result.fact_ids == ["source"]
    assert observed == [{"method": "json_schema", "include_raw": True}]
    assert context.budget.remaining == 0
