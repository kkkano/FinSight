from backend.services.execution_service import _llm_degradation
from backend.services.execution_service import _degradation_message
import pytest


@pytest.mark.parametrize("code,word", [("llm_output_truncated", "截断"), ("llm_empty_output", "空正文"),
    ("llm_output_invalid", "格式"), ("provider_timeout", "超时"), ("quota_exhausted", "额度")])
def test_completion_failures_are_not_misreported_as_unavailable(code, word):
    result = _llm_degradation({"trace": {"synthesize_runtime": {"fallback": True, "reason": code}}})
    assert result["reason"] == code
    assert word in _degradation_message(result)
    assert "LLM 暂时不可用" not in _degradation_message(result)


def test_llm_degradation_reads_conversation_failure():
    result = _llm_degradation(
        {
            "trace": {
                "conversation_degraded": {
                    "used": True,
                    "stage": "direct_reply",
                    "reason": "llm_unavailable",
                }
            }
        }
    )

    assert result == {
        "used": True,
        "stage": "direct_reply",
        "reason": "llm_unavailable",
    }


def test_llm_degradation_reads_synthesis_fallback():
    result = _llm_degradation(
        {
            "trace": {
                "synthesize_runtime": {
                    "fallback": True,
                    "reason": "provider_timeout",
                }
            }
        }
    )

    assert result == {
        "used": True,
        "stage": "synthesis",
        "reason": "provider_timeout",
    }


def test_llm_degradation_redacts_provider_exception_details():
    result = _llm_degradation(
        {
            "trace": {
                "conversation_degraded": {
                    "used": True,
                    "stage": "direct_reply",
                    "reason": "llm_unavailable: postgresql://user:password@db.example/v1",
                }
            }
        }
    )

    assert result["reason"] == "llm_unavailable"
    assert "postgresql://" not in str(result)
    assert "password" not in str(result).lower()


def test_llm_degradation_marks_all_runtime_attempts_failed():
    result = _llm_degradation(
        {"trace": {}},
        {"llm_token_calls": 2, "failed_llm_calls": 2},
    )

    assert result == {
        "used": True,
        "stage": "runtime",
        "reason": "all_llm_attempts_failed",
    }


def test_llm_degradation_does_not_mark_recovered_retry():
    assert _llm_degradation(
        {"trace": {}},
        {"llm_token_calls": 2, "failed_llm_calls": 1},
    ) is None
