"""只提取最终回答与安全诊断，思考内容不能替代用户可见答案。"""
from __future__ import annotations

import re
from typing import Any


class LLMCompletionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def completion_metadata(response: Any) -> dict[str, Any]:
    metadata = getattr(response, "response_metadata", None) or {}
    choices = getattr(response, "choices", None) or []
    choice = choices[0] if choices else None
    usage = metadata.get("token_usage") or metadata.get("usage") or getattr(response, "usage", None) or {}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    standard_usage = getattr(response, "usage_metadata", None) or {}
    output_details = usage.get("completion_tokens_details") or standard_usage.get("output_token_details") or {}
    content = getattr(response, "content", getattr(getattr(choice, "message", None), "content", None))
    return {
        "finish_reason": str(metadata.get("finish_reason") or getattr(choice, "finish_reason", None) or "unknown"),
        "actual_model": str(metadata.get("model_name") or metadata.get("model") or getattr(response, "model", None) or "unknown"),
        "prompt_tokens": usage.get("prompt_tokens", standard_usage.get("input_tokens")),
        "completion_tokens": usage.get("completion_tokens", standard_usage.get("output_tokens")),
        "reasoning_tokens": output_details.get("reasoning_tokens", output_details.get("reasoning")),
        "response_characters": len(content) if isinstance(content, str) else None,
    }


def final_completion_text(response: Any) -> str:
    finish = completion_metadata(response)["finish_reason"].lower()
    if finish in {"length", "max_tokens", "max_output_tokens"}:
        raise LLMCompletionError("llm_output_truncated")
    content = getattr(response, "content", response if isinstance(response, str) else None)
    if content is None and getattr(response, "choices", None):
        content = getattr(response.choices[0].message, "content", None)
    if isinstance(content, list):
        content = "\n".join(block["text"] for block in content
                            if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
                            and isinstance(block.get("text"), str))
    if not isinstance(content, str):
        raise LLMCompletionError("llm_output_invalid")
    if content.count("<think>") != content.count("</think>"):
        raise LLMCompletionError("llm_output_invalid")
    content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
    if not content:
        raise LLMCompletionError("llm_empty_output")
    return content
