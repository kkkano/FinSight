from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.model_router import router
from backend.services import model_selection as selection


def app_with_models():
    app = FastAPI()
    def authenticate(request):
        if request.headers.get("authorization") != "Bearer test-user-session":
            raise HTTPException(status_code=401, detail="Authentication required")
        return {"user_id": "test-user", "is_anonymous": False}
    app.state.require_model_access = authenticate
    app.add_middleware(selection.ModelSelectionMiddleware, authenticate=authenticate)
    app.include_router(router)

    @app.get("/api/execute")
    async def inspect():
        from backend.llm_config import get_llm_config
        await asyncio.sleep(0)
        cfg = get_llm_config()
        return {"model": cfg["model"], "endpoint": cfg["endpoint_name"], "effort": cfg.get("reasoning_effort")}

    @app.get("/api/execute/resume")
    async def stream():
        async def events():
            await asyncio.sleep(0)
            from backend.llm_config import get_llm_config
            yield get_llm_config()["model"]
        return StreamingResponse(events())

    @app.get("/api/watchlist")
    async def watchlist():
        return {"ok": True}

    return app


def custom(model="step-5-preview", **overrides):
    return {"source": "custom", "base_url": "https://api.stepfun.com/step_plan", "api_key": "custom-test-secret", "model": model, "context_acknowledged": True, **overrides}


def header(payload):
    return {"Authorization": "Bearer test-user-session", "X-FinSight-Model": base64.b64encode(json.dumps(payload).encode()).decode()}


@pytest.mark.asyncio
async def test_catalog_and_capabilities_never_expose_system_key(monkeypatch):
    monkeypatch.setenv("STEPFUN_API_KEY", "system-test-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_with_models()), base_url="http://test") as client:
        response = await client.get("/api/models")
        assert response.status_code == 200
        item = response.json()["models"][0]
        assert response.json()["default_model_id"] == selection.STEP_MODEL_ID
        assert item["available"] is True
        assert item["effort_options"] == ["low", "medium", "high"]
        assert "api_key" not in response.text and "system-test-secret" not in response.text
        unknown = await client.get("/api/models/capabilities", params={"model": "unknown-model"})
        assert unknown.json()["effort_options"] == []


@pytest.mark.asyncio
async def test_no_header_default_matches_step_catalog_despite_old_proxy_config(monkeypatch):
    monkeypatch.setenv("STEPFUN_API_KEY", "system-test-secret")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "legacy-private-key")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_BASE", "https://legacy.example/v1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "gpt-5.4-mini")
    from backend.llm_config import load_user_endpoints
    assert [cfg.model for cfg in load_user_endpoints()] == [selection.STEP_MODEL]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_with_models()), base_url="http://test") as client:
        response = await client.get("/api/execute")
    assert response.json() == {"model": selection.STEP_MODEL, "endpoint": "system-stepfun", "effort": "medium"}
    assert selection.current_model() is None


@pytest.mark.asyncio
async def test_personal_prediction_uses_same_selection_as_chat(monkeypatch):
    monkeypatch.setenv("STEPFUN_API_KEY", "system-test-secret")
    app = app_with_models()

    @app.post("/api/predictions/generate")
    async def prediction():
        from backend.llm_config import get_llm_config
        cfg = await asyncio.to_thread(get_llm_config, model="ignored-legacy-model")
        return {"model": cfg["model"], "effort": cfg.get("reasoning_effort")}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        chosen = header({"source": "system", "model_id": selection.STEP_MODEL_ID, "effort": "high"})
        response = await client.post("/api/predictions/generate", headers=chosen)
    assert response.json() == {"model": selection.STEP_MODEL, "effort": "high"}


def test_public_benchmark_does_not_inherit_custom_selection(monkeypatch):
    from backend.llm_config import get_llm_config
    monkeypatch.setenv("STEPFUN_API_KEY", "system-test-secret")
    selected = selection.SelectedModel("custom", "own-model", "https://example.com/v1", "private-user-key")
    with selection.model_selection_scope(selected):
        with selection.server_model_scope():
            assert get_llm_config()["model"] == selection.STEP_MODEL
        assert selection.current_model() is selected


@pytest.mark.asyncio
async def test_request_selection_is_isolated_and_stream_safe(monkeypatch):
    monkeypatch.setenv("STEPFUN_API_KEY", "system-test-secret")
    monkeypatch.setattr(selection, "is_safe_url", lambda _: True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_with_models()), base_url="http://test") as client:
        system, own, stream = await asyncio.gather(
            client.get("/api/execute", headers=header({"source": "system", "model_id": selection.STEP_MODEL_ID, "effort": "high"})),
            client.get("/api/execute", headers=header(custom("my-own-model"))),
            client.get("/api/execute/resume", headers=header(custom("stream-model"))),
        )
        assert system.json() == {"model": "step-5-preview", "endpoint": "system-stepfun", "effort": "high"}
        assert own.json() == {"model": "my-own-model", "endpoint": "user-custom", "effort": None}
        assert stream.text == "stream-model"
        assert selection.current_model() is None


@pytest.mark.asyncio
async def test_no_system_key_can_be_forwarded_to_custom_url(monkeypatch):
    monkeypatch.setenv("STEPFUN_API_KEY", "system-test-secret")
    with pytest.raises(selection.ModelSelectionError, match="系统模型不接受"):
        await selection.resolve_selection({"source": "system", "model_id": selection.STEP_MODEL_ID, "base_url": "https://evil.example"})
    with pytest.raises(selection.ModelSelectionError, match="API Key"):
        await selection.resolve_selection(custom(api_key=""))


@pytest.mark.asyncio
async def test_invalid_effort_and_private_urls_rejected(monkeypatch):
    monkeypatch.setattr(selection, "is_safe_url", lambda _: False)
    with pytest.raises(selection.ModelSelectionError, match="公共网络"):
        await selection.resolve_selection(custom(base_url="https://127.0.0.1"))
    monkeypatch.setattr(selection, "is_safe_url", lambda _: True)
    with pytest.raises(selection.ModelSelectionError, match="effort"):
        await selection.resolve_selection(custom(effort="xhigh"))
    with pytest.raises(selection.ModelSelectionError, match="effort"):
        await selection.resolve_selection(custom("unknown-model", effort="high"))
    with pytest.raises(selection.ModelSelectionError, match="API Key"):
        await selection.resolve_selection(custom(api_key="non-ascii-密钥"))


def test_provider_error_redaction_for_non_prefixed_keys(monkeypatch):
    monkeypatch.setenv("STEPFUN_API_KEY", "plain-system-secret")
    assert selection.redact_model_secrets("invalid key: plain-system-secret") == "invalid key: [redacted]"


def test_custom_model_can_run_without_a_configured_server_default(monkeypatch):
    import backend.llm_config as config
    monkeypatch.setattr(config, '_resolve_endpoints', lambda *args: (_ for _ in ()).throw(RuntimeError('no server model')))
    token = selection._selected_model.set(selection.SelectedModel('custom', 'own-model', 'https://api.example.com/v1', 'fixture-secret'))
    try:
        assert config.get_llm_config()['model'] == 'own-model'
        manager = config.get_endpoint_manager()
        assert manager.select().model == 'own-model'
        assert manager is not config._ENDPOINT_MANAGER
    finally:
        selection._selected_model.reset(token)


@pytest.mark.asyncio
async def test_connection_test_redacts_provider_errors(monkeypatch):
    monkeypatch.setenv("STEPFUN_API_KEY", "system-test-secret")
    original = httpx.AsyncClient

    async def provider(request):
        assert request.url.path == "/step_plan/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer system-test-secret"
        body = json.loads(request.content)
        assert body["reasoning_effort"] == "medium"
        return httpx.Response(401, json={"error": {"message": "system-test-secret"}})

    async with original(transport=httpx.ASGITransport(app=app_with_models()), base_url="http://test") as client:
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(provider), **kwargs))
        response = await client.post("/api/models/test", headers={"Authorization": "Bearer test-user-session"}, json={"source": "system", "model_id": selection.STEP_MODEL_ID})
        assert response.json()["success"] is False
        assert "system-test-secret" not in response.text


@pytest.mark.asyncio
async def test_anonymous_selection_and_test_are_rejected_before_provider_access(monkeypatch):
    app = app_with_models()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/models/test", json=custom())).status_code == 401
        anonymous_headers = header(custom())
        anonymous_headers.pop("Authorization")
        assert (await client.get("/api/execute", headers=anonymous_headers)).status_code == 401
        assert (await client.get("/api/models")).status_code == 200
        response = await client.get("/api/watchlist", headers={"X-FinSight-Model": "malformed"})
        assert response.status_code == 200 and response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_custom_context_confirmation_required():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_with_models()), base_url="http://test") as client:
        response = await client.get("/api/execute", headers=header(custom(context_acknowledged=False)))
        assert response.status_code == 400


@pytest.mark.parametrize("provider_status", [401, 403, 429, 500])
@pytest.mark.asyncio
async def test_provider_failures_have_one_public_message(monkeypatch, provider_status):
    from backend.api.model_router import PROVIDER_FAILURE_MESSAGE
    original = httpx.AsyncClient
    async def provider(request):
        return httpx.Response(provider_status, json={"error": {"message": "provider-specific-secret"}})
    async with original(transport=httpx.ASGITransport(app=app_with_models()), base_url="http://test") as client:
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(provider), **kwargs))
        result = await client.post("/api/models/test", headers={"Authorization": "Bearer test-user-session"}, json=custom())
        assert result.status_code == 200
        assert result.json()["message"] == PROVIDER_FAILURE_MESSAGE
        assert "provider-specific-secret" not in result.text


@pytest.mark.asyncio
async def test_malformed_provider_message_has_safe_failure_response(monkeypatch):
    from backend.api.model_router import PROVIDER_FAILURE_MESSAGE
    original = httpx.AsyncClient

    async def provider(request):
        return httpx.Response(200, json={"choices": [{"message": "provider-specific-secret"}]})

    async with original(transport=httpx.ASGITransport(app=app_with_models()), base_url="http://test") as client:
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(provider), **kwargs))
        result = await client.post("/api/models/test", headers={"Authorization": "Bearer test-user-session"}, json=custom())
    assert result.status_code == 200
    assert result.json()["success"] is False
    assert result.json()["message"] == PROVIDER_FAILURE_MESSAGE
    assert "provider-specific-secret" not in result.text


@pytest.mark.parametrize("api_auth", ["false", "true"])
@pytest.mark.parametrize("identity,expected", [
    ({"user_id": "verified-user", "is_anonymous": False}, 400),
    ({"user_id": "anonymous-user", "is_anonymous": True}, 401),
    (None, 401),
])
@pytest.mark.asyncio
async def test_application_model_access_uses_verified_identity(monkeypatch, api_auth, identity, expected):
    from backend.api import main, security_gate
    from backend.security import supabase_auth
    from backend.config.settings import clear_settings_caches
    monkeypatch.setenv('API_AUTH_ENABLED', api_auth)
    monkeypatch.setenv('API_AUTH_KEYS', 'internal-fixture-key')
    clear_settings_caches()
    user = supabase_auth.AuthenticatedUser(identity['user_id'], is_anonymous=identity['is_anonymous']) if identity else None
    monkeypatch.setattr(supabase_auth, 'resolve_request_user', lambda request: user)
    monkeypatch.setattr(security_gate, '_rate_limiter', security_gate.SimpleRateLimiter(100, 60, enabled=False))
    monkeypatch.setattr(main.app.state, 'model_test_limiter', None, raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        result = await client.post('/api/models/test', headers={'Authorization':'Bearer fixture-session'}, json={})
    assert result.status_code == expected


@pytest.mark.asyncio
async def test_model_tests_have_a_separate_user_rate_limit(monkeypatch):
    original = httpx.AsyncClient
    calls = []
    async def provider(request):
        calls.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})
    async with original(transport=httpx.ASGITransport(app=app_with_models()), base_url="http://test") as client:
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(provider), **kwargs))
        statuses = [(await client.post("/api/models/test", headers={"Authorization": "Bearer test-user-session"}, json=custom())).status_code for _ in range(4)]
        assert statuses == [200, 200, 200, 429]
        assert len(calls) == 3


@pytest.mark.asyncio
async def test_custom_request_has_wall_clock_limit_and_closes_owned_clients(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    app = app_with_models()
    sync_client, async_client = Mock(spec=["close"]), Mock(spec=["aclose"])
    async_client.aclose = AsyncMock()
    @app.post("/api/execute")
    async def slow():
        selection.track_model_client(sync_client)
        selection.track_model_client(async_client)
        await asyncio.sleep(1)
        return {"ok": True}
    monkeypatch.setattr(selection, "CUSTOM_REQUEST_TIMEOUT_SECONDS", .01)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/execute", headers=header(custom()))
    assert response.status_code == 504
    sync_client.close.assert_called_once()
    async_client.aclose.assert_awaited_once()


def test_shared_address_space_is_not_a_public_custom_target():
    from backend.security.ssrf import is_safe_url
    assert is_safe_url("https://100.64.0.1") is False


def test_short_key_does_not_redact_normal_prose(monkeypatch):
    monkeypatch.setenv("STEPFUN_API_KEY", "a")
    assert selection.redact_model_secrets("market data") == "market data"


def test_base_normalization_preserves_complete_step_path():
    assert selection.normalize_custom_base("https://api.stepfun.com/step_plan") == selection.STEP_BASE_URL
    assert selection.normalize_custom_base(selection.STEP_BASE_URL + "/chat/completions") == selection.STEP_BASE_URL
    assert selection.normalize_custom_base("https://proxy.example.com/v1beta/openai") == "https://proxy.example.com/v1beta/openai"
    assert selection.normalize_custom_base("https://api.example.com") == "https://api.example.com/v1"
    with pytest.raises(selection.ModelSelectionError):
        selection.normalize_custom_base("https://name:password@api.stepfun.com")


@pytest.mark.asyncio
async def test_official_origin_works_with_local_dns_proxy(monkeypatch):
    monkeypatch.setattr(selection, "is_safe_url", lambda _: False)
    chosen = await selection.resolve_selection(custom())
    assert chosen.base_url == selection.STEP_BASE_URL
    with pytest.raises(selection.ModelSelectionError):
        await selection.resolve_selection(custom(base_url="https://attacker.example"))


@pytest.mark.asyncio
async def test_create_llm_uses_selected_model_and_official_effort(monkeypatch):
    import langchain_openai
    from backend.llm_config import create_llm

    captured = {}
    def fake_llm(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", fake_llm)
    chosen = selection.SelectedModel("system", "step-5-preview", selection.STEP_BASE_URL, "private-test-key", "system-stepfun", "low")
    token = selection._selected_model.set(chosen)
    try:
        create_llm(model="ignored-global-model", max_tokens=512, max_retries=0)
        assert captured["model"] == "step-5-preview"
        assert captured["reasoning_effort"] == "low"
        assert captured["max_tokens"] == 65536
        assert captured["request_timeout"] == 1200
        assert captured["openai_api_key"] == "private-test-key"
        assert captured["http_client"].follow_redirects is False
        assert captured["http_async_client"].follow_redirects is False
    finally:
        selection._selected_model.reset(token)
        captured["http_client"].close()
        await captured["http_async_client"].aclose()


@pytest.mark.parametrize("frozen,expected_tokens,expected_timeout", [
    (False, 65536, 1200), (True, 4096, 60),
])
def test_background_step_budget_preserves_only_explicit_frozen_calls(monkeypatch, frozen, expected_tokens, expected_timeout):
    import langchain_openai
    from backend.llm_config import EndpointConfig, create_llm_for_endpoint

    captured = {}
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kwargs: captured.update(kwargs) or object())
    monkeypatch.setenv("LLM_FOREGROUND_MAX_TOKENS", "65536")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "1200")
    with selection.server_model_scope():
        create_llm_for_endpoint(
            EndpointConfig("system-stepfun", "openai", selection.STEP_BASE_URL, "fixture-key", selection.STEP_MODEL),
            max_tokens=4096, request_timeout=60, preserve_output_budget=frozen,
        )
    assert captured["max_tokens"] == expected_tokens
    assert captured["request_timeout"] == expected_timeout
    assert captured["max_retries"] == 0


def test_public_forecast_explicitly_freezes_its_budget(monkeypatch):
    import backend.llm_config as config
    from backend.services import prediction_runner

    captured = {}
    monkeypatch.setenv("PREDICTION_OUTPUT_TOKENS", "4096")
    monkeypatch.setattr(config, "create_llm", lambda **kwargs: captured.update(kwargs) or object())
    prediction_runner.create_forecast_llm()
    assert captured["max_tokens"] == 4096
    assert captured["request_timeout"] == 60
    assert captured["preserve_output_budget"] is True


@pytest.mark.parametrize("requested_timeout,expected_timeout", [(600, 600), (15, 15), (2400, 1200)])
@pytest.mark.asyncio
async def test_custom_llm_bounds_sdk_timeout_and_disables_retries(monkeypatch, requested_timeout, expected_timeout):
    import langchain_openai
    from backend.llm_config import create_llm

    captured = {}
    def fake_llm(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", fake_llm)
    token = selection._selected_model.set(selection.SelectedModel("custom", "own-model", "https://api.example.com/v1", "fixture-key"))
    try:
        create_llm(request_timeout=requested_timeout, max_retries=5)
        assert captured["request_timeout"] == expected_timeout
        assert captured["max_retries"] == 0
    finally:
        selection._selected_model.reset(token)
        captured["http_client"].close()
        await captured["http_async_client"].aclose()


def test_selected_endpoint_does_not_change_server_rotation_pool():
    import backend.llm_config as config
    before = config._ENDPOINT_MANAGER.fingerprint
    token = selection._selected_model.set(selection.SelectedModel('custom', 'own-model', 'https://api.example.com/v1', 'fixture-secret'))
    try:
        manager = config.get_endpoint_manager()
        assert [ep.cfg.model for ep in manager.endpoints] == ['own-model']
        assert config._ENDPOINT_MANAGER.fingerprint == before
    finally:
        selection._selected_model.reset(token)


@pytest.mark.asyncio
async def test_public_ledger_routes_survive_reversed_registration(monkeypatch, tmp_path):
    from backend.api.main import app
    from backend.api import prediction_router
    from backend.services.prediction_store import PredictionStore
    from fastapi.routing import APIRoute

    monkeypatch.setattr(prediction_router, 'get_prediction_store', lambda: PredictionStore(tmp_path/'ledger.sqlite'))
    routes = {
        route.path: route for route in app.routes
        if isinstance(route, APIRoute) and route.path in {
            '/api/predictions/{prediction_id}', '/api/predictions/track-record',
            '/api/benchmarks/us20-v1/track-record',
        }
    }
    assert len(routes) == 3
    detail = routes['/api/predictions/{prediction_id}']
    alias = routes['/api/predictions/track-record']
    benchmark = routes['/api/benchmarks/us20-v1/track-record']
    assert list(app.routes).index(alias) < list(app.routes).index(detail)

    for ordering in ((alias, detail, benchmark), (benchmark, alias, detail)):
        isolated = FastAPI()
        isolated.router.routes.extend(ordering)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=isolated), base_url='http://test') as client:
            current = await client.get('/api/benchmarks/us20-v1/track-record')
            legacy = await client.get('/api/predictions/track-record')
            private = await client.get('/api/predictions/00000000-0000-4000-8000-000000000302')
        assert current.status_code == legacy.status_code == 200
        assert current.json() == legacy.json()
        assert current.json()['summary']['opportunities'] == 0
        assert private.status_code == 401 and private.json()['detail']['code'] == 'auth_required'

    openapi = app.openapi()['paths']
    assert '/api/benchmarks/us20-v1/track-record' in openapi
    assert '/api/predictions/track-record' not in openapi


@pytest.mark.asyncio
async def test_current_invocation_chain_keeps_selected_model_and_one_attempt(monkeypatch):
    from backend.services import llm_retry
    calls = []
    class ProviderFailure(Exception):
        status_code = 503
    class Client:
        model_name = "own-model"
        async def ainvoke(self, _messages):
            raise ProviderFailure("temporary provider failure")
    def make_client(endpoint, **_kwargs):
        calls.append((endpoint.name, endpoint.model, endpoint.api_key))
        return Client()
    monkeypatch.setattr(llm_retry, "create_llm_for_endpoint", make_client)
    context = llm_retry.LLMCallContext("fixture-call", "synthesis", "report", "L2", llm_retry.LLMAttemptBudget(3))
    token = selection._selected_model.set(selection.SelectedModel("custom", "own-model", "https://api.example.com/v1", "fixture-secret"))
    try:
        with pytest.raises(ProviderFailure):
            await llm_retry.ainvoke_configured_llm(
                messages=[], context=context, acquire_token=False,
                endpoint_names=["server-pool-only"],
            )
        assert calls == [("user-custom", "own-model", "fixture-secret")]
        assert context.budget.provider_attempts_used == 1
    finally:
        selection._selected_model.reset(token)


@pytest.mark.asyncio
async def test_detached_custom_stream_times_out_and_closes_its_clients(monkeypatch):
    from unittest.mock import AsyncMock
    from backend.api.execution_router import _buffered_sse_response
    client = AsyncMock()
    ended = []
    async def pipeline():
        selection.track_model_client(client)
        try:
            await asyncio.sleep(1)
            yield {"type": "done"}
        finally:
            ended.append(True)
    monkeypatch.setattr(selection, "CUSTOM_REQUEST_TIMEOUT_SECONDS", .01)
    token = selection._selected_model.set(selection.SelectedModel("custom", "own-model", "https://api.example.com/v1", "fixture-secret"))
    try:
        response = _buffered_sse_response(pipeline(), run_id="fixture-custom-timeout", thread_id="fixture-thread")
        chunks = [chunk async for chunk in response.body_iterator]
        assert "model_timeout" in "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)
        assert ended == [True]
        client.aclose.assert_awaited_once()
    finally:
        selection._selected_model.reset(token)
