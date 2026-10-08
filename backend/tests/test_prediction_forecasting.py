"""Prospective forecasts use a single real call path with controlled model responses."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.agents.risk_agent import RiskAgent
from backend.agents.technical_agent import TechnicalAgent
from backend.research import forecasting
from backend.research.prediction_contract import ForecastContext, ForecastResult
from backend.utils.llm_json import _extract_json


class FakeLLM:
    def __init__(self, payload=None, *, content=None, metadata=None, usage=None, error=None,
                 endpoint="endpoint-a", configured_model="configured-a", max_tokens=4096):
        self.response = SimpleNamespace(
            content=content if content is not None else json.dumps(payload),
            response_metadata=metadata or {}, usage_metadata=usage or {},
        )
        self.error = error
        self.calls = []
        self.max_retries = 0
        self.model_name = configured_model
        self._finsight_call_metadata = {
            "endpoint_alias": endpoint,
            "configured_model": configured_model,
            "request_parameters": {"temperature": None, "max_tokens": max_tokens, "max_retries": 0,
                                   "request_timeout": 60, "reasoning_effort": "high"},
            "submitted_parameters": {"max_completion_tokens": max_tokens, "reasoning_effort": "high"},
        }

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def context():
    return ForecastContext(
        ticker="AAPL", batch_date="2026-10-02", knowledge_cutoff="2026-10-01T20:00:00Z",
        deadline_at="2026-10-02T13:20:00Z", window_start="2026-10-02T13:30:00Z",
        window_end="2026-10-08T20:00:00Z",
    )


@pytest.fixture
def snapshot():
    return {
        "as_of": "2026-10-01T20:00:00Z", "source": "yahoo/yfinance-0.2.66",
        "features": {"last_close": 220.0, "return_5d": .06, "return_20d": .1,
                     "ma20": 210.0, "ma50": 208.0, "rsi": 69.0, "macd": 1.7,
                     "signal": 1.5, "hist": .2, "volume_ratio20": 1.1,
                     "realized_vol20": .25, "max_drawdown60": .09, "unavailable": None},
        "bars": [{"time": "2026-10-01", "close": 220, "hidden_marker": "do-not-send-raw-bars"}] * 250,
    }


@pytest.fixture(autouse=True)
def isolate_attempt(monkeypatch):
    import backend.services.rate_limiter as limiter

    async def acquire(**_kwargs):
        return True

    monkeypatch.setattr(limiter, "acquire_llm_token", acquire)
    monkeypatch.setattr(forecasting, "_utc_now", lambda: datetime(2026, 10, 2, 12, 50, tzinfo=timezone.utc))


def direction_payload(**overrides):
    return {"status": "predicted", "direction": "down", "reason": "短期上涨后动量接近超买，预计未来五日回落。",
            "evidence_refs": ["rsi", "ma20"], **overrides}


def drawdown_payload(**overrides):
    return {"status": "predicted", "event_occurs": False, "reason": "现有波动率和回撤特征不支持未来五日触及5%回撤。",
            "evidence_refs": ["realized_vol20", "max_drawdown60"], **overrides}


@pytest.mark.asyncio
async def test_technical_forecast_calls_model_and_predicts_forward(context, snapshot, monkeypatch):
    llm = FakeLLM(direction_payload(), metadata={"finish_reason": "stop", "model_name": "actual-a"})
    agent = TechnicalAgent(llm, None, None)
    monkeypatch.setattr(agent, "_deterministic_summary", lambda *_: pytest.fail("must not reuse research"))

    result = await agent.forecast(context, snapshot)

    assert result.status == "predicted" and result.direction == "down"
    assert snapshot["features"]["return_5d"] > 0  # Historical momentum is not the forecast label.
    assert result.event_occurs is None and not result.retryable
    assert result.prompt_version == "technical-direction-v1"
    assert len(llm.calls) == 1
    prompt = llm.calls[0][0].content
    assert "P5/P0-1" in prompt and "-0.005<=R<=0.005" in prompt
    assert "do-not-send-raw-bars" not in prompt and '"bars"' not in prompt
    assert '"window_start":"2026-10-02T13:30:00Z"' in prompt
    assert '"unavailable"' not in prompt
    assert result.metadata["input_token_upper_bound"] <= 4000
    assert result.metadata["missing_features"] == ["unavailable"]
    assert result.metadata["actual_model"] == "actual-a"
    assert result.model_dump(mode="json")["issued_at"] == "2026-10-02T12:50:00Z"


@pytest.mark.asyncio
@pytest.mark.parametrize("event_occurs", [False, True])
async def test_risk_forecast_preserves_both_event_judgments(context, snapshot, event_occurs):
    llm = FakeLLM(drawdown_payload(event_occurs=event_occurs))

    result = await RiskAgent(llm, None, None).forecast(context, snapshot)

    assert result.status == "predicted" and result.event_occurs is event_occurs
    assert result.direction is None and result.prediction_type == "drawdown"
    assert result.prompt_version == "risk-drawdown-v1"
    assert "prior running maximum" in llm.calls[0][0].content
    assert "largest drawdown>=0.05" in llm.calls[0][0].content
    assert len(llm.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_type,payload", [
    (TechnicalAgent, direction_payload(status="abstained", direction=None, evidence_refs=[])),
    (RiskAgent, drawdown_payload(status="abstained", event_occurs=None, evidence_refs=[])),
])
async def test_deliberate_abstention_is_retained_without_retry(context, snapshot, agent_type, payload):
    llm = FakeLLM(payload)
    result = await agent_type(llm, None, None).forecast(context, snapshot)
    assert result.status == "abstained" and not result.retryable and result.error_code is None
    assert result.direction is None and result.event_occurs is None and len(llm.calls) == 1


@pytest.mark.asyncio
async def test_closed_think_and_json_fences_use_shared_parser(context, snapshot):
    text = '<think>private reasoning {"direction":"up"}</think>\n```json\n' + json.dumps(direction_payload()) + '\n```'
    llm = FakeLLM(content=text)
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert _extract_json(text) == direction_payload()
    assert result.status == "predicted" and result.direction == "down"
    assert "private reasoning" not in result.model_dump_json()
    assert len(result.metadata["output_sha256"]) == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("content,metadata,error_code", [
    ("not JSON", {}, "invalid_json"),
    ('{"status":"predicted","direction":"up",', {}, "invalid_json"),
    ('<think>unfinished ' + json.dumps(direction_payload()), {}, "incomplete_thinking"),
    (json.dumps(direction_payload()) + '<think>unfinished', {}, "incomplete_thinking"),
    (json.dumps(direction_payload()), {"finish_reason": "length"}, "output_truncated"),
    (json.dumps(direction_payload()), {"stop_reason": "max_tokens"}, "output_truncated"),
])
async def test_bad_or_truncated_response_cannot_become_prediction(context, snapshot, content, metadata, error_code):
    llm = FakeLLM(content=content, metadata=metadata)
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert result.status == "failed" and result.error_code == error_code and result.retryable
    assert result.direction is None and len(llm.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"ticker": "MSFT"}, {"agent": "risk"}, {"horizon_sessions": 20},
    {"direction_threshold": .1}, {"window_start": "2020-01-01T00:00:00Z"},
    {"prediction_type": "drawdown"}, {"confidence": .8}, {"status": "failed"},
    {"direction": "bullish"}, {"direction": None}, {"evidence_refs": []},
    {"reason": "  "}, {"status": "abstained", "direction": "up"},
])
async def test_model_cannot_change_identity_or_judgment_contract(context, snapshot, overrides):
    llm = FakeLLM(direction_payload(**overrides))
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert result.status == "failed" and result.error_code == "invalid_forecast_contract"
    assert result.direction is None and len(llm.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["false", 0, 1, None])
async def test_drawdown_requires_real_json_boolean(context, snapshot, value):
    result = await RiskAgent(FakeLLM(drawdown_payload(event_occurs=value)), None, None).forecast(context, snapshot)
    assert result.error_code == "invalid_forecast_contract"


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["invented", "unavailable", "features.rsi", "bars"])
async def test_evidence_must_name_available_sent_feature(context, snapshot, reference):
    llm = FakeLLM(direction_payload(evidence_refs=[reference]))
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert result.status == "failed" and result.error_code == "invalid_evidence_reference"


@pytest.mark.asyncio
async def test_actual_models_and_parameters_follow_each_instance(context, snapshot, monkeypatch):
    import backend.llm_config as config
    monkeypatch.setattr(config, "get_llm_config", lambda **_: pytest.fail("metadata must not rotate endpoints"))
    first = FakeLLM(direction_payload(), endpoint="endpoint-a", configured_model="alias-a", metadata={
        "model_name": "model-a", "finish_reason": "stop", "temperature": .7,
        "token_usage": {"prompt_tokens": 700, "completion_tokens": 900,
                        "completion_tokens_details": {"reasoning_tokens": 800}, "api_key": "secret"},
    })
    second = FakeLLM(direction_payload(), endpoint="endpoint-b", configured_model="alias-b", metadata={"model": "model-b"})
    unknown = FakeLLM(direction_payload(), endpoint="endpoint-c", configured_model="alias-c")

    results = [await TechnicalAgent(llm, None, None).forecast(context, snapshot) for llm in (first, second, unknown)]

    assert [r.metadata["endpoint_alias"] for r in results] == ["endpoint-a", "endpoint-b", "endpoint-c"]
    assert [r.metadata["actual_model"] for r in results] == ["model-a", "model-b", "unknown"]
    assert [r.metadata["model_confirmed"] for r in results] == [True, True, False]
    assert results[0].metadata["provider_parameters"]["temperature"] == .7
    assert results[1].metadata["provider_parameters"]["temperature"] == "unknown"
    assert results[1].metadata["request_parameters"]["temperature"] is None
    assert "temperature" not in results[1].metadata["submitted_parameters"]
    assert results[1].metadata["submitted_parameters"]["reasoning_effort"] == "high"
    assert results[0].metadata["usage"]["completion_tokens_details"]["reasoning_tokens"] == 800
    assert "secret" not in results[0].model_dump_json()


@pytest.mark.asyncio
async def test_content_blocks_and_usage_metadata_keep_only_final_text(context, snapshot):
    llm = FakeLLM(content=[{"type": "thinking", "thinking": "PRIVATE"},
                           {"type": "text", "text": json.dumps(direction_payload())}],
                  usage={"input_tokens": 700, "output_tokens": 900, "total_tokens": 1600,
                         "output_token_details": {"reasoning": 800}})
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert result.status == "predicted"
    assert result.metadata["usage"]["output_token_details"]["reasoning"] == 800
    assert "PRIVATE" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code,retryable,code", [
    (401, False, "llm_authentication"), (400, False, "llm_configuration"),
    (429, True, "llm_service_unavailable"), (503, True, "llm_service_unavailable"),
])
async def test_failure_classification_never_retries_or_leaks_provider_exception(context, snapshot, status_code, retryable, code):
    error = RuntimeError("https://private-provider.invalid api_key=SECRET raw reasoning")
    error.status_code = status_code
    llm = FakeLLM(error=error)
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert result.status == "failed" and result.error_code == code and result.retryable is retryable
    assert len(llm.calls) == 1
    assert "SECRET" not in result.model_dump_json() and "private-provider" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_sdk_budget_and_retries_validated_before_request(context, snapshot):
    small = FakeLLM(direction_payload(), max_tokens=2047)
    retries = FakeLLM(direction_payload())
    retries.max_retries = 2
    for llm in (small, retries):
        result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
        assert result.error_code == "llm_configuration" and not result.retryable and not llm.calls
    accepted = await TechnicalAgent(FakeLLM(direction_payload(), max_tokens=2048), None, None).forecast(context, snapshot)
    assert accepted.status == "predicted"


@pytest.mark.asyncio
async def test_outer_helper_explicitly_has_one_attempt(context, snapshot, monkeypatch):
    import backend.services.llm_retry as helper
    original = helper.ainvoke_frozen_llm
    settings = []

    async def inspect(*args, **kwargs):
        settings.append(kwargs)
        return await original(*args, **kwargs)

    monkeypatch.setattr(helper, "ainvoke_frozen_llm", inspect)
    llm = FakeLLM(direction_payload())
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert result.status == "predicted" and len(llm.calls) == 1
    assert settings[0]["context"].budget.max_provider_attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["token", "model"])
async def test_one_hard_timeout_covers_token_wait_and_request(context, snapshot, monkeypatch, stage):
    import backend.services.rate_limiter as limiter
    monkeypatch.setattr(forecasting, "FORECAST_TIMEOUT_SECONDS", .01)
    llm = FakeLLM(direction_payload())

    async def blocked(*args, **kwargs):
        if stage == "model":
            llm.calls.append(args)
        await asyncio.sleep(1)

    if stage == "token":
        monkeypatch.setattr(limiter, "acquire_llm_token", blocked)
    else:
        monkeypatch.setattr(llm, "ainvoke", blocked)
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert result.error_code == "llm_timeout" and result.retryable
    assert len(llm.calls) == (0 if stage == "token" else 1)


@pytest.mark.asyncio
async def test_deadline_prevents_call_or_acceptance(context, snapshot, monkeypatch):
    llm = FakeLLM(direction_payload())
    late = datetime(2026, 10, 2, 13, 21, tzinfo=timezone.utc)
    monkeypatch.setattr(forecasting, "_utc_now", lambda: late)
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert result.error_code == "issuance_deadline" and not llm.calls

    monkeypatch.setattr(forecasting, "_utc_now", lambda: datetime(2026, 10, 2, 13, 19, tzinfo=timezone.utc))
    original = llm.ainvoke

    async def complete_late(messages):
        response = await original(messages)
        monkeypatch.setattr(forecasting, "_utc_now", lambda: late)
        return response

    monkeypatch.setattr(llm, "ainvoke", complete_late)
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert result.error_code == "issuance_deadline" and result.direction is None and len(llm.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change,code", [
    ({"features": {}}, "missing_market_data"),
    ({"as_of": "2026-10-02T20:00:00Z"}, "snapshot_after_cutoff"),
    ({"as_of": "2026-10-01T20:00:00"}, "invalid_snapshot_time"),
])
async def test_bad_snapshot_fails_without_llm(context, snapshot, change, code):
    snapshot.update(change)
    llm = FakeLLM(direction_payload())
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert result.error_code == code and not result.retryable and not llm.calls


@pytest.mark.asyncio
async def test_missing_llm_and_risk_data_are_failures_not_predictions(context, snapshot):
    missing_llm = await TechnicalAgent(None, None, None).forecast(context, snapshot)
    assert missing_llm.error_code == "llm_unavailable" and not missing_llm.retryable
    snapshot["features"]["realized_vol20"] = None
    llm = FakeLLM(drawdown_payload())
    result = await RiskAgent(llm, None, None).forecast(context, snapshot)
    assert result.error_code == "missing_market_data" and not llm.calls


@pytest.mark.asyncio
async def test_input_budget_does_not_silently_drop_features(context, snapshot):
    snapshot["features"].update({f"feature_{i}": "x" * 150 for i in range(40)})
    llm = FakeLLM(direction_payload())
    result = await TechnicalAgent(llm, None, None).forecast(context, snapshot)
    assert result.error_code == "input_budget_exceeded" and not llm.calls


@pytest.mark.parametrize("field,value", [
    ("horizon_sessions", 20), ("direction_threshold", .1), ("drawdown_threshold", .2),
    ("scorer_version", "other"), ("batch_date", "20261002"),
    ("knowledge_cutoff", "2026-10-01T20:00:00"), ("deadline_at", "2026-10-02T13:31:00Z"),
])
def test_context_rejects_mutated_scoring_rules(context, field, value):
    with pytest.raises(ValidationError):
        ForecastContext(**{**context.model_dump(), field: value})


def test_result_cannot_mix_judgments_or_retry_an_accepted_prediction():
    payload = dict(status="predicted", prediction_type="direction", direction="up",
                   evidence_refs=["rsi"], reason="test", prompt_version="test", issued_at="2026-10-02T12:00:00Z")
    with pytest.raises(ValidationError):
        ForecastResult(**payload, event_occurs=False)
    with pytest.raises(ValidationError):
        ForecastResult(**payload, retryable=True)
