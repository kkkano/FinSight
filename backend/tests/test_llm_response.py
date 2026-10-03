from types import SimpleNamespace

import pytest

from backend.services.llm_response import LLMCompletionError, completion_metadata, final_completion_text


def response(content, finish="stop"):
    return SimpleNamespace(content=content, response_metadata={"finish_reason": finish, "model_name": "fixture-model",
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 3000, "completion_tokens_details": {"reasoning_tokens": 2900}},
        "api_key": "private-fixture-key"}, additional_kwargs={"reasoning_content": "private thinking"})


def test_only_final_text_blocks_are_answers():
    value = response([{"type": "thinking", "thinking": "hidden"}, {"type": "text", "text": '{"answer":"真实正文"}'}])
    assert final_completion_text(value) == '{"answer":"真实正文"}'


def test_structured_response_keeps_raw_usage_finish_and_final_content():
    from backend.services.llm_usage import extract_token_usage, has_reported_token_usage
    from backend.services.llm_retry import _usage_or_none
    value = {"raw": response('{"answer":"真实正文"}'), "parsed": {"answer": "真实正文"}, "parsing_error": None}
    assert final_completion_text(value) == '{"answer":"真实正文"}'
    assert completion_metadata(value)["actual_model"] == "fixture-model"
    assert extract_token_usage(value) == _usage_or_none(value) == (100, 3000)
    assert has_reported_token_usage(value)
    value["raw"] = response("", "length")
    assert completion_metadata(value)["finish_reason"] == "length"
    with pytest.raises(LLMCompletionError, match="llm_output_truncated"):
        final_completion_text(value)
    assert "private-fixture-key" not in str(completion_metadata(value))


def test_thinking_json_is_not_mistaken_for_final_json():
    value = response('<think>{"wrong":"internal"}</think>```json\n{"answer":"final"}\n```')
    assert "wrong" not in final_completion_text(value)
    assert '"answer":"final"' in final_completion_text(value)


@pytest.mark.parametrize("content,finish,code", [("", "length", "llm_output_truncated"),
    ('{"answer":"partial"}', "length", "llm_output_truncated"), ("", "stop", "llm_empty_output"),
    ("<think>unfinished", "stop", "llm_output_invalid"), ("<think>only thinking</think>", "stop", "llm_empty_output")])
def test_unusable_completions_have_distinct_causes(content, finish, code):
    with pytest.raises(LLMCompletionError) as caught:
        final_completion_text(response(content, finish))
    assert caught.value.code == code


def test_diagnostic_metadata_does_not_include_private_content():
    metadata = completion_metadata(response("final"))
    assert metadata["finish_reason"] == "stop"
    assert metadata["completion_tokens"] == 3000
    assert metadata["reasoning_tokens"] == 2900
    assert metadata["response_characters"] == 5
    assert "private" not in str(metadata) and "thinking" not in str(metadata)


@pytest.mark.asyncio
async def test_sdk_json_mode_truncation_preserves_classification_and_billed_usage(monkeypatch):
    import httpx
    from langchain_openai import ChatOpenAI
    from openai import LengthFinishReasonError
    from backend.services import llm_retry
    from backend.services.llm_usage import TokenUsageAccumulator, set_token_accumulator, reset_token_accumulator
    from backend.services.model_selection import SelectedModel, model_selection_scope

    attempts = []
    calls = []
    async def provider(request):
        import json
        body = json.loads(request.content)
        calls.append(body)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={
            "id": "fixture", "object": "chat.completion", "created": 1, "model": "step-5-preview",
            "choices": [{"index": 0, "finish_reason": "length", "message": {
                "role": "assistant", "content": "", "reasoning_content": "private-thinking"}}],
            "usage": {"prompt_tokens": 5000, "completion_tokens": 65536, "total_tokens": 70536},
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as http_client:
        client = ChatOpenAI(model="step-5-preview", api_key="fixture-key", base_url="https://fixture.example/v1",
                            max_tokens=65536, max_retries=0, http_async_client=http_client)
        monkeypatch.setattr(llm_retry, "create_llm_for_endpoint", lambda *_args, **_kwargs: client)
        selected = SelectedModel("system", "step-5-preview", "https://fixture.example/v1", "fixture-key")
        context = llm_retry.LLMCallContext.create(stage="synthesis", on_attempt=attempts.append)
        accumulator = TokenUsageAccumulator()
        token = set_token_accumulator(accumulator)
        try:
            with model_selection_scope(selected), pytest.raises(LengthFinishReasonError) as caught:
                await llm_retry.ainvoke_configured_llm(
                    ["Return JSON"], context=context, acquire_token=False,
                    client_transform=lambda model: model.bind(response_format={"type": "json_object"}),
                )
            classification = llm_retry.classify_llm_error(caught.value)
            assert classification.kind == "output_truncated" and classification.retryable is False
            assert classification.endpoint_failure is False
            metadata = completion_metadata(caught.value.completion)
            assert metadata["finish_reason"] == "length" and metadata["completion_tokens"] == 65536
            assert len(calls) == 1 and attempts[0]["usage_state"] == "reported"
            assert attempts[0]["error_code"] == "llm_output_truncated"
            assert attempts[0]["completion_tokens"] == accumulator.completion_tokens == 65536
            assert accumulator.prompt_tokens == 5000 and accumulator.call_count == 1
            assert accumulator.failed_call_count == 1
            assert "private-thinking" not in str(attempts) and "fixture-key" not in str(attempts)
        finally:
            reset_token_accumulator(token)
            client.root_client.close()
