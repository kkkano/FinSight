"""研究 Step API 选择、凭据隔离及冻结服务端默认值的合同。"""
import base64
import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from starlette.responses import StreamingResponse

from backend.agent_runtime import model_options
from backend.api.model_router import router
from backend.config.settings import clear_settings_caches
from backend.services import model_selection as legacy


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_MODEL", "existing-research-model")
    monkeypatch.setenv("FINSIGHT_AGENT_API_BASE", "https://existing.invalid/v1")
    monkeypatch.setenv("FINSIGHT_AGENT_API_KEY", "existing-fixture-key")
    monkeypatch.setenv("FINSIGHT_AGENT_STEPFUN_API_KEY", "research-only-fixture-key")
    monkeypatch.setenv("FINSIGHT_AGENT_QWEN_API_KEY", "research-qwen-fixture-key")
    monkeypatch.delenv("STEPFUN_API_KEY", raising=False)
    clear_settings_caches()
    yield
    clear_settings_caches()


def model_header(**extra):
    value = {"source": "system", "model_id": model_options.STEP_API_MODEL_ID, **extra}
    return {"X-FinSight-Model": base64.b64encode(json.dumps(value).encode()).decode(),
            "Authorization": "Bearer fixture-session"}


def app():
    application = FastAPI()

    async def authenticate(request):
        if request.headers.get("authorization") != "Bearer fixture-session":
            raise HTTPException(status_code=401, detail="请登录后使用模型设置")
        return {"user_id": "fixture-user"}

    application.state.require_model_access = authenticate
    application.add_middleware(model_options.ResearchModelSelectionMiddleware, authenticate=authenticate)
    application.include_router(router)

    @application.get("/api/execute")
    async def execute(request: Request):
        async def body():
            selected = legacy.current_model()
            assert selected.api_key == {legacy.STEP_MODEL: "research-only-fixture-key",
                "qwen3.8-flash": "research-qwen-fixture-key"}.get(selected.model, "existing-fixture-key")
            yield json.dumps({"model": selected.model, "base_url": selected.base_url, "effort": selected.effort})
        return StreamingResponse(body(), media_type="application/json")

    return application


@pytest.mark.asyncio
async def test_research_step_option_is_available_without_exposing_key_or_changing_default():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        response = await client.get("/api/models")
        assert response.json()["default_model_id"] == legacy.SERVER_DEFAULT_MODEL_ID
        step = next(item for item in response.json()["models"] if item["id"] == model_options.STEP_API_MODEL_ID)
        assert step["available"] and step["vision"]
        assert "research-only-fixture-key" not in response.text and "api_key" not in response.text
        default = await client.get("/api/execute")
        assert default.json()["model"] == "existing-research-model"


@pytest.mark.asyncio
async def test_selected_step_uses_metered_api_during_stream_and_clears_request_scope():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        response = await client.get("/api/execute", headers=model_header(effort="low"))
        assert response.json() == {"model": "step-5-preview", "base_url": "https://api.stepfun.com/v1", "effort": "low"}
        assert "research-only-fixture-key" not in response.text
    assert legacy.current_model() is None


@pytest.mark.asyncio
async def test_research_step_requires_authentication_and_rejects_credential_overrides():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        headers = model_header()
        headers.pop("Authorization")
        assert (await client.get("/api/execute", headers=headers)).status_code == 401
        response = await client.get("/api/execute", headers=model_header(api_key="attacker-fixture-key"))
        assert response.status_code == 400 and "attacker-fixture-key" not in response.text
        assert (await client.get("/api/execute", headers=model_header(effort="unsupported"))).status_code == 400
        assert (await client.get("/api/execute", headers=model_header(effort={"unsupported": True}))).status_code == 400


@pytest.mark.asyncio
async def test_frozen_server_scope_cannot_inherit_the_research_step_credential(monkeypatch):
    selected = await model_options.resolve_selection({"source": "system", "model_id": model_options.STEP_API_MODEL_ID})
    with legacy.model_selection_scope(selected):
        with legacy.server_model_scope():
            assert legacy.current_model() is None
            default = legacy.resolve_default_model()
            assert default.model == "existing-research-model" and default.api_key == "existing-fixture-key"
        assert legacy.current_model() is selected
    from backend.config.settings import providers_settings
    assert providers_settings().stepfun_api_key == ""
    assert "research-only-fixture-key" not in repr(providers_settings())
    assert "research-only-fixture-key" not in providers_settings().model_dump_json()


@pytest.mark.asyncio
async def test_existing_step_plan_selection_is_preserved_when_research_api_is_unconfigured(monkeypatch):
    monkeypatch.delenv("FINSIGHT_AGENT_STEPFUN_API_KEY")
    monkeypatch.setenv("STEPFUN_API_KEY", "legacy-step-plan-fixture-key")
    clear_settings_caches()
    selected = await model_options.resolve_selection({"source": "system", "model_id": legacy.STEP_MODEL_ID})
    assert selected.base_url == legacy.STEP_BASE_URL and selected.api_key == "legacy-step-plan-fixture-key"


@pytest.mark.asyncio
async def test_qwen_option_uses_authorized_endpoint_and_keeps_default_and_secrets_isolated():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        catalogue = await client.get("/api/models")
        option = next(item for item in catalogue.json()["models"] if item["id"] == model_options.QWEN_API_MODEL_ID)
        assert option["model"] == option["label"] == "qwen3.8-flash" and option["available"]
        assert "research-qwen-fixture-key" not in catalogue.text and "api_key" not in catalogue.text
        assert catalogue.json()["default_model_id"] == legacy.SERVER_DEFAULT_MODEL_ID
        response = await client.get("/api/execute", headers=model_header(model_id=model_options.QWEN_API_MODEL_ID))
        assert response.json() == {"model": "qwen3.8-flash", "base_url": "https://api.kunyou.asia/v1", "effort": None}
    assert legacy.current_model() is None
    selected = await model_options.resolve_selection({"source": "system", "model_id": model_options.QWEN_API_MODEL_ID})
    with legacy.model_selection_scope(selected), legacy.server_model_scope():
        assert legacy.resolve_default_model().api_key == "existing-fixture-key"
    from backend.config.settings import providers_settings
    assert "research-qwen-fixture-key" not in repr(providers_settings())
    assert "research-qwen-fixture-key" not in providers_settings().model_dump_json()


@pytest.mark.asyncio
async def test_qwen_option_requires_auth_and_rejects_overrides_and_unsupported_effort(monkeypatch):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        headers = model_header(model_id=model_options.QWEN_API_MODEL_ID)
        headers.pop("Authorization")
        assert (await client.get("/api/execute", headers=headers)).status_code == 401
        for extra in ({"api_key": "untrusted-key"}, {"base_url": "https://other.invalid"}, {"effort": "low"}, {"effort": {}}):
            response = await client.get("/api/execute", headers=model_header(model_id=model_options.QWEN_API_MODEL_ID, **extra))
            assert response.status_code == 400
            assert "untrusted-key" not in response.text and "research-qwen-fixture-key" not in response.text
        monkeypatch.delenv("FINSIGHT_AGENT_QWEN_API_KEY")
        catalogue = (await client.get("/api/models")).json()
        assert not any(item["id"] == model_options.QWEN_API_MODEL_ID for item in catalogue["models"])


@pytest.mark.asyncio
async def test_step_empty_object_effort_is_rejected_instead_of_becoming_default():
    with pytest.raises(legacy.ModelSelectionError):
        await model_options.resolve_selection({"source": "system", "model_id": model_options.STEP_API_MODEL_ID, "effort": {}})
