"""研究模型选项的请求级适配；冻结预测的默认模型与实现保持不变。"""
from __future__ import annotations

import base64
import binascii
import json

from backend.services import model_selection as legacy
from .config import qwen_research_model, stepfun_research_model

STEP_API_MODEL_ID = "stepfun-api:step-5-preview"
QWEN_API_MODEL_ID = "qwen-api:qwen3.8-flash"


def model_capabilities(model: str, base_url: str = "") -> dict:
    capabilities = legacy.model_capabilities(model, base_url)
    if model.strip() == legacy.STEP_MODEL and base_url.rstrip("/") in {"", "https://api.stepfun.com/v1"}:
        capabilities = {**capabilities, "vision": True}
    return capabilities


def system_models() -> list[dict]:
    models = legacy.system_models()
    configured = stepfun_research_model()
    if configured is not None:
        models.append({"id": STEP_API_MODEL_ID, "model": configured.model,
                       **model_capabilities(configured.model, configured.base_url),
                       "label": "Step 5 Preview（按量）", "available": True})
    configured = qwen_research_model()
    if configured is not None:
        models.append({"id": QWEN_API_MODEL_ID, "model": configured.model,
                       **model_capabilities(configured.model, configured.base_url),
                       "label": "qwen3.8-flash", "available": True})
    return models


def _research_model(payload):
    if not isinstance(payload, dict) or payload.get("source") != "system":
        return None
    if payload.get("model_id") == STEP_API_MODEL_ID:
        return stepfun_research_model()
    if payload.get("model_id") == QWEN_API_MODEL_ID:
        return qwen_research_model()
    return None


async def resolve_selection(payload) -> legacy.SelectedModel:
    configured = _research_model(payload)
    if configured is None:
        return await legacy.resolve_selection(payload)
    if set(payload) - {"source", "model_id", "effort"}:
        raise legacy.ModelSelectionError("系统模型不接受自定义地址或密钥")
    effort = payload.get("effort")
    if configured.model == legacy.STEP_MODEL:
        effort = "medium" if effort in (None, "") else effort
        if effort not in ("low", "medium", "high"):
            raise legacy.ModelSelectionError("该模型不支持所选 effort，请使用供应商默认设置")
        configured = stepfun_research_model(effort)
    elif effort not in (None, ""):
        raise legacy.ModelSelectionError("该模型不支持所选 effort，请使用供应商默认设置")
    return legacy.SelectedModel("system", configured.model, configured.base_url, configured.api_key,
                                configured.endpoint_name, configured.effort)


class ResearchModelSelectionMiddleware:
    """适配显式选择的研究模型；其他请求委托共享模型边界。"""

    def __init__(self, app, authenticate=None):
        self.app, self.authenticate = app, authenticate
        self.fallback = legacy.ModelSelectionMiddleware(app, authenticate=authenticate)

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope.get("method") == "OPTIONS"
                or not legacy.is_model_generation_path(scope.get("path", ""))):
            return await self.fallback(scope, receive, send)
        encoded = next((value for name, value in scope.get("headers", [])
                        if name.lower() == legacy.MODEL_HEADER), None)
        if encoded is None or len(encoded) > 16384:
            return await self.fallback(scope, receive, send)
        try:
            payload = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
        except (ValueError, TypeError, binascii.Error, UnicodeError):
            return await self.fallback(scope, receive, send)
        if _research_model(payload) is None:
            return await self.fallback(scope, receive, send)

        from fastapi import HTTPException
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        try:
            await legacy.require_model_user(Request(scope, receive), self.authenticate)
            selected = await resolve_selection(payload)
        except HTTPException as exc:
            return await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
        except legacy.ModelSelectionError as exc:
            return await JSONResponse({"detail": str(exc)}, status_code=400)(scope, receive, send)
        with legacy.model_selection_scope(selected):
            async with legacy.model_client_scope():
                await self.app(scope, receive, send)
