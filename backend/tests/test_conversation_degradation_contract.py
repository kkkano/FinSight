from backend.services.execution_service import _llm_degradation


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
