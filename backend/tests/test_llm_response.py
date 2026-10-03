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
