from __future__ import annotations


def test_preserve_secret_if_masked_keeps_existing_value():
    from backend.api.config_router import _preserve_secret_if_masked

    assert _preserve_secret_if_masked("sk-***abc", "sk-real-value") == "sk-real-value"
    assert _preserve_secret_if_masked("***", "sk-real-value") == "sk-real-value"
    assert _preserve_secret_if_masked("", "sk-real-value") == "sk-real-value"


def test_preserve_secret_if_masked_accepts_plain_new_value():
    from backend.api.config_router import _preserve_secret_if_masked

    assert _preserve_secret_if_masked("sk-new-value", "sk-old-value") == "sk-new-value"


def test_merge_llm_endpoints_preserves_masked_keys_by_name_and_index():
    from backend.api.config_router import _merge_llm_endpoints

    existing = [
        {"name": "ep-a", "api_key": "key-a", "api_base": "https://a.example.com/v1"},
        {"name": "ep-b", "api_key": "key-b", "api_base": "https://b.example.com/v1"},
    ]
    incoming = [
        {"name": "ep-a", "api_key": "sk-***aaa", "api_base": "https://a.example.com/v1"},
        {"name": "ep-b", "api_key": "", "api_base": "https://b.example.com/v1"},
    ]

    merged = _merge_llm_endpoints(existing, incoming)
    assert isinstance(merged, list)
    assert merged[0]["api_key"] == "key-a"
    assert merged[1]["api_key"] == "key-b"


def test_merge_llm_endpoints_accepts_new_plain_api_key():
    from backend.api.config_router import _merge_llm_endpoints

    existing = [{"name": "ep-a", "api_key": "key-a"}]
    incoming = [{"name": "ep-a", "api_key": "key-new", "api_base": "https://a.example.com/v1"}]

    merged = _merge_llm_endpoints(existing, incoming)
    assert merged[0]["api_key"] == "key-new"

