"""选定模型的服务商错误不轮换，成功输出的合同纠正仍使用原共享预算。"""
from __future__ import annotations

import pytest

from backend.graph.synthesis.contracts import ClaimValidationResult, EvidenceNormalizationResult, NormalizedEvidence
from backend.graph.synthesis.research_synthesis import synthesize_task_results
from backend.graph.synthesis.task_outcomes import TaskOutcome
from backend.services import llm_retry, model_selection, rate_limiter


@pytest.mark.asyncio
async def test_selected_model_success_then_reference_repair_uses_same_model_and_remaining_budget(monkeypatch):
    calls, acquired, limits = [], [], []

    class Client:
        model_name = "selected-model"

        def with_structured_output(self, _schema, **_kwargs):
            return self

        async def ainvoke(self, _messages):
            calls.append(self.model_name)
            return {"claim_ids": [], "direction_supporting_claim_ids": [], "explanations": [{"text": "企业订阅续约有助于收入稳定。", "evidence_ids": ["E404" if len(calls) == 1 else "E1"]}]}

    def make_client(endpoint, **kwargs):
        assert endpoint.model == "selected-model" and endpoint.name == "user-custom"
        limits.append(kwargs)
        return Client()

    async def acquire(**kwargs):
        acquired.append(kwargs)
        return True

    monkeypatch.setattr(llm_retry, "create_llm_for_endpoint", make_client)
    monkeypatch.setattr(rate_limiter, "acquire_llm_token", acquire)
    monkeypatch.setenv("LANGGRAPH_STRUCTURED_SYNTHESIS_MAX_TOKENS", "65536")
    monkeypatch.setenv("LANGGRAPH_STRUCTURED_SYNTHESIS_REQUEST_TIMEOUT_SECONDS", "1200")
    context = llm_retry.LLMCallContext.create(stage="synthesize", max_provider_attempts=2)
    outcome = TaskOutcome(task_id="task", title="业务解释", priority=0, order_index=0, operation="qa", subject_label="CRM", tickers=["CRM"], request_frame_id="frame", render_kind="single", render_group_id="frame", intent_status="ready", required_step_ids=["step"], required_evidence=["company_profile"], error_codes=[], status="answered", successful_step_ids=["step"], evidence_ids=["source"], missing_evidence=[])
    evidence = NormalizedEvidence(source_id="source", task_ids=["task"], kind="company_profile", usage="fact", text="企业订阅业务需要客户续约。", subject="CRM")
    with model_selection.model_selection_scope(model_selection.SelectedModel("custom", "selected-model", "https://api.example.com/v1", "fixture-key")):
        result = (await synthesize_task_results(task_outcomes=[outcome], findings=[],
            claim_validation=ClaimValidationResult(valid_claims={}, rejected_claims=[], conflicts=[], quality_block_reasons=[]),
            evidence_normalization=EvidenceNormalizationResult(evidence_by_task={"task": [evidence]}, evidence_index={"source": evidence}, rejected_evidence=[], quality_block_reasons=[]),
            llm_call_context_factory=lambda _: context))[0]
    assert calls == ["selected-model", "selected-model"] and len(acquired) == 1
    assert context.budget.max_provider_attempts == 2 and context.budget.provider_attempts_used == 2
    assert context.budget.remaining == 0
    assert result.conclusion == "企业订阅续约有助于收入稳定。" and not result.fallback_used
    assert result.synthesis_validation["repair_attempts"] == 1
    assert result.synthesis_validation["initial_errors"][0]["code"] == "task_synthesis_unknown_evidence_id"
    assert not result.synthesis_validation["remaining_errors"]
    assert all(limit["max_tokens"] == 65536 and limit["request_timeout"] == 1200 for limit in limits)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["authentication", "configuration", "provider"])
async def test_selected_model_provider_or_configuration_errors_never_rotate_or_retry(monkeypatch, failure):
    calls = []

    class ProviderFailure(Exception):
        status_code = 401 if failure == "authentication" else 503

    class Client:
        model_name = "selected-model"

        async def ainvoke(self, _messages):
            raise ProviderFailure("fixture provider failure")

    def make_client(endpoint, **_kwargs):
        calls.append((endpoint.name, endpoint.model))
        if failure == "configuration":
            raise ValueError("model configuration invalid")
        return Client()

    async def forbidden_sleep(_delay):
        raise AssertionError("选定模型的服务商错误不能暗中轮换或重试")

    monkeypatch.setattr(llm_retry, "create_llm_for_endpoint", make_client)
    context = llm_retry.LLMCallContext.create(stage="synthesize", max_provider_attempts=2)
    with model_selection.model_selection_scope(model_selection.SelectedModel("custom", "selected-model", "https://api.example.com/v1", "fixture-key")):
        with pytest.raises(ValueError if failure == "configuration" else ProviderFailure):
            await llm_retry.ainvoke_configured_llm([], context=context, acquire_token=False, endpoint_names=["server-pool-only"], sleeper=forbidden_sleep)
    assert calls == [("user-custom", "selected-model")]
    assert context.budget.max_provider_attempts == 2
    assert context.budget.provider_attempts_used == (0 if failure == "configuration" else 1)
