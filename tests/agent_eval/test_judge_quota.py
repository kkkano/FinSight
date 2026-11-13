"""评分transport配额合同：模拟网络，验证真实BudgetedModel预约/结算，不作为模型能力证明。"""
import asyncio
import importlib.util
from pathlib import Path
import sqlite3
import time

import pytest

spec = importlib.util.spec_from_file_location("quota_judge", Path(__file__).with_name("grade_apikl_budgeted.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NetworkFixture:
    calls = []
    reported_model = None

    def __init__(self, config, *, client=None):
        self.config = config

    async def stream(self, messages, tools, **kwargs):
        self.calls.append((messages, tools, kwargs))
        yield {"model": self.reported_model or self.config.model,
               "choices": [{"delta": {"content": "fixture"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}


def setup(monkeypatch):
    NetworkFixture.calls = []
    NetworkFixture.reported_model = None
    monkeypatch.setattr(module, "OriginalTransport", NetworkFixture)
    monkeypatch.setenv("FINSIGHT_AGENT_MODEL_CONCURRENCY", "2")
    monkeypatch.setenv("FINSIGHT_AGENT_RPM_LIMIT", "30")
    monkeypatch.setenv("FINSIGHT_AGENT_TPM_LIMIT", "1000")
    monkeypatch.setenv("FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("FINSIGHT_AGENT_TOKEN_BUDGET", "160000")


async def consume(transport, messages=None):
    return [chunk async for chunk in transport.stream(messages or [{"role": "user", "content": "fixture"}], [], timeout=1)]


def test_same_account_models_share_tpm_and_requests_settle_actual_usage(tmp_path, monkeypatch):
    setup(monkeypatch)
    events = []
    cls = module.quota_transport_class(tmp_path / "quota.sqlite", events)
    a = module.ModelConfig("subject", "https://provider.invalid/v1", "fixture-key", max_output=64)
    b = module.ModelConfig("judge", a.base_url, a.api_key, max_output=64)
    asyncio.run(consume(cls(a)))
    asyncio.run(consume(cls(b)))
    with sqlite3.connect(tmp_path / "quota.sqlite") as conn:
        rows = conn.execute("SELECT bucket,amount FROM runtime_windows WHERE bucket LIKE 'provider:%'").fetchall()
    assert len(rows) == 2 and rows[0][0] == rows[1][0]
    assert [amount for _, amount in rows] == [20, 20]
    assert all(event["events"][0]["reservation_succeeded"] for event in events)
    assert all(event["budget_spent"] == 20 and event["budget_reserved_remaining"] == 0 for event in events)


def test_unavailable_tpm_does_not_make_network_call_or_charge_unstarted_tokens(tmp_path, monkeypatch):
    setup(monkeypatch)
    original_context = module.RunContext
    def short_context(**kwargs):
        kwargs["deadline"] = time.monotonic() + .05
        return original_context(**kwargs)
    monkeypatch.setattr(module, "RunContext", short_context)
    config = module.ModelConfig("judge", "https://provider.invalid/v1", "fixture-key", max_output=64)
    limiter = module.LeaseLimiter(tmp_path / "quota.sqlite")
    limiter.reserve_window("provider:" + config.provider_identity(), 999, maximum=1000, requests=30)
    attempts = []
    cls = module.quota_transport_class(tmp_path / "quota.sqlite", attempts)
    with pytest.raises(module.ModelProtocolError, match="provider_local_quota_exhausted"):
        asyncio.run(consume(cls(config)))
    assert NetworkFixture.calls == []
    assert attempts[0]["budget_spent"] == 0 and attempts[0]["budget_reserved_remaining"] == 0


def test_wrapper_preserves_original_messages_tools_and_model_identity(tmp_path, monkeypatch):
    setup(monkeypatch)
    config = module.ModelConfig("judge", "https://provider.invalid/v1", "fixture-key", max_output=64)
    attempts = []
    cls = module.quota_transport_class(tmp_path / "quota.sqlite", attempts)
    messages = [{"role": "system", "content": "原始量表"}, {"role": "user", "content": "原始完整payload"}]
    asyncio.run(consume(cls(config), messages))
    assert NetworkFixture.calls[0][0] == messages
    assert attempts[0]["reported_models"] == ["judge"]
    assert attempts[0]["status"] == "completed"


def test_wrong_returned_model_is_not_silently_relabeled(tmp_path, monkeypatch):
    setup(monkeypatch)
    NetworkFixture.reported_model = "other-model"
    config = module.ModelConfig("judge", "https://provider.invalid/v1", "fixture-key", max_output=64)
    cls = module.quota_transport_class(tmp_path / "quota.sqlite", [])
    with pytest.raises(module.ModelProtocolError, match="judge_returned_model_mismatch"):
        asyncio.run(consume(cls(config)))
