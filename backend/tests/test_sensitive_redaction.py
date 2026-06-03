# -*- coding: utf-8 -*-
"""SSE done 事件 metrics 脱敏修复回归测试。

背景：_redact_sensitive_payload() 对 dict key 做子串匹配，"token" 命中后
会把整个值替换成 ***，导致 metrics 里的 token 计数指标（total_tokens 等）
被误脱敏。本测试既验证修复后计数指标原样保留，也守住真正字符串凭据仍被脱敏。
"""
import importlib

import backend.api.main as main


def _load_main_module():
    """重新加载 main 模块，保证拿到最新实现。"""
    importlib.reload(main)
    return main


def test_total_tokens_int_not_redacted():
    """用例1：整数计数 total_tokens=12345 不应被脱敏。"""
    m = _load_main_module()
    redacted = m._redact_sensitive_payload({"total_tokens": 12345})
    assert redacted["total_tokens"] == 12345


def test_tokens_by_model_nested_structure_preserved():
    """用例2：tokens_by_model 嵌套结构和数值原样保留。"""
    m = _load_main_module()
    redacted = m._redact_sensitive_payload({"tokens_by_model": {"gpt-4": 999}})
    assert redacted["tokens_by_model"] == {"gpt-4": 999}


def test_digit_string_token_count_preserved():
    """用例3：纯数字字符串 "12345" 也是计数，不脱敏。"""
    m = _load_main_module()
    redacted = m._redact_sensitive_payload({"total_tokens": "12345"})
    assert redacted["total_tokens"] == "12345"


def test_api_key_string_still_redacted():
    """用例4：真正的字符串凭据 api_key 仍被脱敏（回归保护）。"""
    m = _load_main_module()
    redacted = m._redact_sensitive_payload({"api_key": "sk-abcdefgh12345"})
    # 原始密钥不得泄露，且保持 _mask_secret 的 前3***后3 格式
    assert "abcdefgh" not in redacted["api_key"]
    assert redacted["api_key"] == "sk-***345"


def test_authorization_bearer_string_still_redacted():
    """用例5：authorization Bearer token 字符串仍被脱敏（回归保护）。"""
    m = _load_main_module()
    redacted = m._redact_sensitive_payload(
        {"authorization": "Bearer abc123def456"}
    )
    assert "abc123def456" not in redacted["authorization"]
    assert redacted["authorization"] == "Bea***456"


def test_token_credential_string_still_redacted():
    """用例6：token 键对应的字符串凭据仍被脱敏（不回归）。"""
    m = _load_main_module()
    redacted = m._redact_sensitive_payload(
        {"token": "secret-credential-string"}
    )
    assert "secret-credential-string" not in redacted["token"]
    assert redacted["token"] == "sec***ing"


def test_full_metrics_payload_numbers_preserved():
    """用例7：完整 metrics 场景，所有数值/嵌套指标原样保留。"""
    m = _load_main_module()
    payload = {
        "metrics": {
            "total_prompt_tokens": 100,
            "total_completion_tokens": 50,
            "total_tokens": 150,
            "llm_token_calls": 3,
            "total_cost_usd": 0.01,
            "tokens_by_model": {"m": 150},
        }
    }
    redacted = m._redact_sensitive_payload(payload)
    metrics = redacted["metrics"]
    assert metrics["total_prompt_tokens"] == 100
    assert metrics["total_completion_tokens"] == 50
    assert metrics["total_tokens"] == 150
    assert metrics["llm_token_calls"] == 3
    assert metrics["total_cost_usd"] == 0.01
    assert metrics["tokens_by_model"] == {"m": 150}
