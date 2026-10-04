"""故障诊断保留可归因字段，不归档服务商错误消息中的敏感内容。"""
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
from backend.graph.nodes.analyze import analyze
from backend.graph.synthesis.contracts import StrictContract
from backend.services import llm_retry, model_selection, rate_limiter
from backend.services.llm_response import LLMCompletionError


_FIELDS = {"exception_type", "cause_types", "http_status", "provider_error_code", "duration_ms", "request_timeout", "max_tokens", "max_retries"}
_PRIVATE = "fixture-sensitive-credential-and-request-content"
_PRIVATE_URL = "https://private.invalid/path?api_key=fixture-sensitive-credential"


def test_diagnostic_whitelist_uses_structured_status_and_codes_without_messages():
    context = llm_retry.LLMCallContext.create(stage="report_task_synthesize")
    context.call_parameters.update(request_timeout=1200, max_tokens=65536, max_retries=0, api_key=_PRIVATE)
    cause = TypeError(f"{_PRIVATE} {_PRIVATE_URL}")
    error = RuntimeError(f"request headers and body {_PRIVATE}")
    error.__cause__ = cause
    error.body = {"error": {"code": "request_timeout", "message": _PRIVATE, "url": _PRIVATE_URL}, "request_body": _PRIVATE}
    error.response = SimpleNamespace(status_code=504, headers={"Authorization": _PRIVATE}, url=_PRIVATE_URL)
    diagnostic = llm_retry.record_failure_diagnostic(context, error, duration_ms=600775)
    assert set(diagnostic) == _FIELDS
    assert diagnostic["exception_type"] == "RuntimeError" and diagnostic["cause_types"] == ["TypeError"]
    assert diagnostic["http_status"] == 504 and diagnostic["provider_error_code"] == "request_timeout"
    assert diagnostic["duration_ms"] == 600775 and diagnostic["request_timeout"] == 1200
    assert diagnostic["max_tokens"] == 65536 and diagnostic["max_retries"] == 0
    assert _PRIVATE not in json.dumps(context.failure_diagnostics)
    assert "http" not in json.dumps(diagnostic).replace("http_status", "")


def test_unknown_provider_code_and_status_inside_sensitive_message_are_not_persisted_or_inferred():
    context = llm_retry.LLMCallContext.create(stage="synthesize")
    context.call_parameters.update(request_timeout={"connect": 30.0, "read": 1200.0, "write": 1200.0, "pool": 1200.0, "header": _PRIVATE}, max_tokens=65536, max_retries=0)
    error = RuntimeError(f"HTTP 504 { _PRIVATE } { _PRIVATE_URL }")
    error.code = _PRIVATE
    error.body = {"error": {"code": _PRIVATE, "message": _PRIVATE}}
    diagnostic = llm_retry.record_failure_diagnostic(context, error, duration_ms=15)
    assert diagnostic["http_status"] is None and diagnostic["provider_error_code"] is None
    assert diagnostic["request_timeout"] == {"connect": 30.0, "read": 1200.0, "write": 1200.0, "pool": 1200.0}
    assert _PRIVATE not in json.dumps(diagnostic) and _PRIVATE_URL not in json.dumps(diagnostic)


@pytest.mark.asyncio
async def test_structured_parser_failure_keeps_only_exception_classes(monkeypatch):
    module = importlib.import_module("backend.graph.synthesis.research_synthesis")

    class Answer(StrictContract):
        conclusion: str

    context = llm_retry.LLMCallContext.create(stage="synthesize", max_provider_attempts=1)

    async def response(_messages, **kwargs):
        kwargs["context"].budget.reserve_provider_attempt()
        return {"raw": AIMessage(content="provider response body " + _PRIVATE), "parsed": None, "parsing_error": ValueError(_PRIVATE + _PRIVATE_URL)}

    monkeypatch.setattr(module, "ainvoke_configured_llm", response)
    with pytest.raises(LLMCompletionError):
        await module._invoke_structured(prompt="用户要求", context=context, schema=Answer, stage="task_synthesis")
    assert len(context.failure_diagnostics) == 1
    diagnostic = context.failure_diagnostics[0]
    assert diagnostic["exception_type"] == "LLMCompletionError" and diagnostic["cause_types"] == ["ValueError"]
    assert _PRIVATE not in json.dumps(diagnostic) and _PRIVATE_URL not in json.dumps(diagnostic)


@pytest.mark.asyncio
@pytest.mark.parametrize("output_mode", ["chat", "investment_report"])
async def test_unknown_provider_failure_reaches_context_task_and_trace_without_secret_payload(monkeypatch, output_mode):
    orchestration = importlib.import_module("backend.graph.synthesis.structured_orchestration")
    contexts, attempts = [], []
    clock = {"now": 0.0}
    original_create = llm_retry.LLMCallContext.create

    def capture_context(**kwargs):
        context = original_create(**kwargs)
        contexts.append(context)
        return context

    class ProviderParseFailure(TypeError):
        pass

    class Client:
        model_name = "step-5-preview"
        root_async_client = SimpleNamespace(timeout=1200.0, max_retries=0)
        max_tokens = 65536

        def with_structured_output(self, _schema, **_kwargs):
            return self

        async def ainvoke(self, _messages):
            attempts.append(1)
            clock["now"] = 600.775
            error = ProviderParseFailure(_PRIVATE + _PRIVATE_URL)
            error.__cause__ = ValueError("private response content " + _PRIVATE)
            error.body = {"error": {"code": _PRIVATE, "message": _PRIVATE}}
            error.response = SimpleNamespace(status_code=200, headers={"Authorization": _PRIVATE}, url=_PRIVATE_URL)
            raise error

    async def acquire(**_kwargs):
        return True

    monkeypatch.setattr(orchestration.LLMCallContext, "create", staticmethod(capture_context))
    monkeypatch.setattr(llm_retry, "create_llm_for_endpoint", lambda *_args, **_kwargs: Client())
    monkeypatch.setattr(llm_retry, "perf_counter", lambda: clock["now"])
    monkeypatch.setattr(rate_limiter, "acquire_llm_token", acquire)
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "llm")
    monkeypatch.setenv("LANGGRAPH_STRUCTURED_SYNTHESIS_MAX_TOKENS", "65536")
    monkeypatch.setenv("LANGGRAPH_STRUCTURED_SYNTHESIS_REQUEST_TIMEOUT_SECONDS", "1200")
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")
    task = {"id": "task", "title": "公司研究", "request_text": "解释公司业务。", "subject_type": "company", "subject_label": "CRM", "tickers": ["CRM"], "operation": {"name": "qa"}, "order_index": 0, "priority": 0, "request_frame_id": "frame", "render_kind": "single", "render_group_id": "frame", "required_evidence": ["company_profile"]}
    step = {"id": "step", "kind": "tool", "name": "get_company_info", "task_ids": ["task"], "inputs": {"ticker": "CRM"}, "evidence_kinds": ["company_profile"]}
    state = {"query": "解释公司业务。", "understanding": {"route": "research"}, "output_mode": output_mode, "operation": task["operation"], "tasks": [task], "subject": {"tickers": ["CRM"]}, "plan_ir": {"tasks": [task], "steps": [step]}, "artifacts": {"step_results": {"step": {"output": {"ticker": "CRM", "description": "公司提供企业订阅服务。"}}}}, "trace": {}}
    normalize_execution_evidence(state=state, plan_ir=state["plan_ir"], artifacts=state["artifacts"])
    with model_selection.model_selection_scope(model_selection.SelectedModel("stepfun", "step-5-preview", "https://api.example.com/v1", "fixture-key", effort="medium")):
        result = await analyze(state)
    task_result = result["artifacts"]["research_result"]["task_results"][0]
    diagnostic = task_result["synthesis_validation"]["failure_diagnostics"][0]
    assert attempts == [1] and len(contexts) == 1
    assert "llm_unknown_error" in task_result["error_codes"]
    assert set(diagnostic) == _FIELDS
    assert diagnostic == contexts[0].failure_diagnostics[0]
    assert diagnostic == result["trace"]["llm_failure_diagnostics"]["tasks"]["task"][0]
    assert diagnostic["exception_type"] == "ProviderParseFailure" and diagnostic["cause_types"] == ["ValueError"]
    assert diagnostic["http_status"] == 200 and diagnostic["provider_error_code"] is None
    assert diagnostic["duration_ms"] == 600775 and diagnostic["request_timeout"] == 1200.0
    assert diagnostic["max_tokens"] == 65536 and diagnostic["max_retries"] == 0
    archived = json.dumps({"validation": task_result["synthesis_validation"], "diagnostics": result["trace"]["llm_failure_diagnostics"]})
    assert _PRIVATE not in archived and _PRIVATE_URL not in archived
