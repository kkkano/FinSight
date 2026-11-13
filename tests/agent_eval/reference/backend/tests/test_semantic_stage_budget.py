"""理解阶段包含排队和一次修复，不能耗尽整轮执行预算。"""
import asyncio

import pytest
from langchain_core.messages import AIMessage

from backend.llm_config import EndpointConfig, EndpointManager, EndpointRuntime
from backend.graph.semantic_requirements import extract_semantic_requirements
from backend.services.run_context import RunContext, remaining_timeout, run_context_scope
from pydantic import TypeAdapter, ValidationError
from backend.graph.semantic_requirements import RequirementQualifier


@pytest.mark.asyncio
async def test_understanding_queue_and_schema_repair_share_one_stage_window(monkeypatch):
    from backend.services import llm_retry, rate_limiter
    calls, sdk_timeouts, token_acquisitions = [], [], []
    raw = {"route": "research", "subjects": [{"id": "stock", "type": "company", "label": "EXM", "tickers": ["EXM"]}],
           "requirements": [{"source_text": "EXM营收", "description": "EXM营收", "kind": "fact_attribute", "metric": "revenue", "subject_refs": ["stock"]}]}

    async def acquire(**_kwargs):
        token_acquisitions.append(True)
        await asyncio.sleep(.05)
        return True

    class Client:
        model_name = "fixture"
        max_tokens = 65536
        max_retries = 0

        def with_structured_output(self, *_args, **_kwargs):
            return self

        async def ainvoke(self, _messages):
            calls.append(True)
            if len(calls) == 1:
                await asyncio.sleep(.05)
                return {"raw": AIMessage(content="{}"), "parsed": {**raw, "route": "invalid"}}
            await asyncio.sleep(1)

    def factory(_endpoint, **kwargs):
        sdk_timeouts.append(kwargs["request_timeout"])
        assert kwargs["max_tokens"] == 65536
        client = Client()
        client.request_timeout = kwargs["request_timeout"]
        return client

    manager = EndpointManager(endpoints=[EndpointRuntime(cfg=EndpointConfig(
        "fixture", "openai_compatible", "https://fixture.test/v1", "fixture-key", "fixture"))], fingerprint="phase")
    monkeypatch.setattr(rate_limiter, "acquire_llm_token", acquire)
    monkeypatch.setattr(llm_retry, "get_endpoint_manager", lambda **_kwargs: manager)
    monkeypatch.setattr(llm_retry, "create_llm_for_endpoint", factory)
    run = RunContext.create(owner="public", entry="chat", budget_seconds=.6)
    with run_context_scope(run):
        result, diagnostics = await extract_semantic_requirements({"query": "EXM营收"}, {})
        assert result is None and diagnostics["cause_code"] == "llm_timeout"
        assert run.status == "running" and run.remaining_seconds > .2
        assert remaining_timeout(60) > .2
    assert len(calls) == 2 and len(token_acquisitions) == 1
    assert sdk_timeouts[1] < sdk_timeouts[0] < .2
    assert diagnostics["provider_attempts"] == 2


@pytest.mark.asyncio
async def test_understanding_respects_smaller_explicit_timeout(monkeypatch):
    from backend.graph import semantic_requirements
    monkeypatch.setenv("LANGGRAPH_REQUEST_TIMEOUT_SEC", "0.08")
    async def slow(*_args, **_kwargs):
        await asyncio.sleep(1)
    monkeypatch.setattr(semantic_requirements, "ainvoke_configured_llm", slow)
    run = RunContext.create(owner="public", entry="investment_report", budget_seconds=3)
    with run_context_scope(run):
        result, diagnostics = await extract_semantic_requirements({"query": "EXM营收"}, {})
    assert result is None and diagnostics["stage_budget_seconds"] == .08
    assert diagnostics["validation_code"] == "request_understanding_timeout"
    assert run.remaining_seconds > 2.5


@pytest.mark.parametrize("value", ["annual_report", "price_return"])
def test_reporting_basis_decoder_rejects_other_categories(value):
    adapter = TypeAdapter(RequirementQualifier)
    with pytest.raises(ValidationError):
        adapter.validate_python({"name": "reporting_basis", "value": value, "source_text": "原始口径"})
    unknown = adapter.validate_python({"name": "unknown", "value": value, "source_text": "原始口径"})
    assert unknown.value == value and unknown.name == "unknown"
    assert adapter.validate_python({"name": "reporting_basis", "value": "consolidated", "source_text": "合并报表"}).value == "consolidated"
