"""Request-local model selection. Server credentials never enter public metadata."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import re
import inspect
from contextvars import ContextVar
from contextlib import contextmanager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from backend.security.ssrf import is_safe_url

STEP_MODEL_ID = "stepfun:step-5-preview"
SERVER_DEFAULT_MODEL_ID = "system:server-default"
STEP_MODEL = "step-5-preview"
STEP_BASE_URL = "https://api.stepfun.com/step_plan/v1"
STEP_DOCS = "https://platform.stepfun.com/docs/zh/guides/models/step-5-preview"
MODEL_HEADER = b"x-finsight-model"
CUSTOM_REQUEST_TIMEOUT_SECONDS = 3600.0
_model_clients: ContextVar[list | None] = ContextVar("finsight_model_clients", default=None)


def is_model_generation_path(path: str) -> bool:
    path = path.split("?", 1)[0].rstrip("/")
    return path in {"/api/execute", "/api/execute/resume", "/api/predictions/generate"}


def require_model_access(request) -> dict:
    from fastapi import HTTPException
    from backend.api.security_gate import _is_internal_api_key_authorized
    from backend.security.supabase_auth import resolve_request_user
    if _is_internal_api_key_authorized(request):
        return {"user_id": "internal", "auth_type": "api_key"}
    user = resolve_request_user(request)
    if user is None or user.is_anonymous:
        raise HTTPException(status_code=401, detail="请登录后使用模型设置")
    return {"user_id": user.user_id, "is_anonymous": False}


async def require_model_user(request, authenticate=None) -> dict:
    from fastapi import HTTPException
    cached = getattr(request.state, "model_user", None)
    if cached is not None:
        return cached
    verify = authenticate or getattr(request.app.state, "require_model_access", None)
    if verify is None:
        raise HTTPException(status_code=401, detail="请登录后使用模型设置")
    identity = await verify(request) if inspect.iscoroutinefunction(verify) else await asyncio.to_thread(verify, request)
    if not isinstance(identity, dict) or not identity.get("user_id") or identity.get("is_anonymous"):
        raise HTTPException(status_code=401, detail="请登录后使用模型设置")
    request.state.model_user = identity
    return identity


def track_model_client(client) -> None:
    clients = _model_clients.get()
    if clients is not None:
        clients.append(client)


@asynccontextmanager
async def model_client_scope():
    """让可重连的后台生成任务独立持有并关闭其 HTTP 客户端。"""
    clients = []
    token = _model_clients.set(clients)
    try:
        yield
    finally:
        _model_clients.reset(token)
        for client in clients:
            if hasattr(client, "aclose"):
                await client.aclose()
            else:
                client.close()


class ModelSelectionError(ValueError):
    """Safe to show to the caller; never include supplied credentials."""


@dataclass(frozen=True)
class SelectedModel:
    source: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    endpoint_name: str = "user-custom"
    effort: str | None = None

    def runtime_config(self) -> dict[str, Any]:
        return {
            "provider": "openai_compatible",
            "model": self.model,
            "api_base": self.base_url,
            "api_key": self.api_key,
            "endpoint_name": self.endpoint_name,
            "reasoning_effort": self.effort,
            "request_selected": True,
        }


_selected_model: ContextVar[SelectedModel | None] = ContextVar("finsight_selected_model", default=None)


def current_model() -> SelectedModel | None:
    return _selected_model.get()


@contextmanager
def model_selection_scope(selected: SelectedModel | None):
    """后台任务只使用创建时选定的模型，退出后恢复调用方上下文。"""
    token = _selected_model.set(selected)
    try:
        yield
    finally:
        _selected_model.reset(token)


def default_model_id() -> str:
    return STEP_MODEL_ID if os.getenv("STEPFUN_API_KEY", "").strip() else SERVER_DEFAULT_MODEL_ID


def resolve_default_model() -> SelectedModel:
    if default_model_id() == STEP_MODEL_ID:
        return SelectedModel("system", STEP_MODEL, STEP_BASE_URL, os.environ["STEPFUN_API_KEY"].strip(),
                             "system-stepfun", model_capabilities(STEP_MODEL)["default_effort"])
    from backend.llm_config import load_user_endpoints
    cfg = load_user_endpoints()[0]
    return SelectedModel("system", cfg.model, cfg.api_base or "", cfg.api_key, cfg.name,
                         model_capabilities(cfg.model)["default_effort"])


@contextmanager
def server_model_scope():
    """Scheduled public benchmarks cannot inherit a browsing user's endpoint/key."""
    token = _selected_model.set(None)
    try:
        yield
    finally:
        _selected_model.reset(token)


def redact_model_secrets(text: str) -> str:
    """Also cover provider error messages for keys without an sk- prefix."""
    active = current_model()
    secrets = {os.getenv("STEPFUN_API_KEY", "").strip()}
    if active:
        secrets.add(active.api_key)
    for secret in secrets:
        if len(secret) >= 8:
            text = text.replace(secret, "[redacted]")
    return text


def model_capabilities(model: str, base_url: str = "") -> dict[str, Any]:
    # Model-specific official capability, never infer arbitrary effort levels.
    if model.strip() == STEP_MODEL:
        return {
            "provider": "stepfun", "label": "Step 5 Preview",
            "icon_url": "/model-icons/stepfun.png",
            "effort_options": ["low", "medium", "high"],
            "default_effort": "medium", "docs_url": STEP_DOCS,
        }
    return {
        "provider": "custom", "label": model.strip() or "自定义模型",
        "icon_url": None, "effort_options": [], "default_effort": None, "docs_url": None,
    }


def system_models() -> list[dict[str, Any]]:
    models = [{
        "id": STEP_MODEL_ID, "model": STEP_MODEL, **model_capabilities(STEP_MODEL),
        "available": bool(os.getenv("STEPFUN_API_KEY", "").strip()),
    }]
    if default_model_id() == SERVER_DEFAULT_MODEL_ID:
        try:
            configured = resolve_default_model()
        except RuntimeError:
            return models
        models.insert(0, {
            "id": SERVER_DEFAULT_MODEL_ID, "model": configured.model,
            **model_capabilities(configured.model), "label": configured.model,
            "provider": "system", "available": True,
        })
    return models


def normalize_custom_base(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ModelSelectionError("请输入有效的 HTTPS API 地址")
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        raise ModelSelectionError("API 地址格式不正确") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or port not in (None, 443)):
        raise ModelSelectionError("API 地址须为不含账号、查询参数的公共 HTTPS 地址")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[:-len("/chat/completions")]
    elif not path or (parsed.hostname.lower() == "api.stepfun.com" and path == "/step_plan"):
        path += "/v1"
    return urlunsplit(("https", parsed.netloc, path, "", ""))


async def resolve_selection(payload: Any) -> SelectedModel:
    if not isinstance(payload, dict):
        raise ModelSelectionError("模型配置必须是对象")
    source = payload.get("source")
    if source == "system":
        if set(payload) - {"source", "model_id", "effort"}:
            raise ModelSelectionError("系统模型不接受自定义地址或密钥")
        if payload.get("model_id") == SERVER_DEFAULT_MODEL_ID and default_model_id() == SERVER_DEFAULT_MODEL_ID:
            configured = resolve_default_model()
            key, base, model, endpoint = configured.api_key, configured.base_url, configured.model, configured.endpoint_name
        elif payload.get("model_id") == STEP_MODEL_ID:
            key = os.getenv("STEPFUN_API_KEY", "").strip()
            if not key:
                raise ModelSelectionError("此系统模型尚未配置，请选择其它模型或使用自定义接入")
            base = STEP_BASE_URL
            model = STEP_MODEL
            endpoint = "system-stepfun"
        else:
            raise ModelSelectionError("系统模型不存在")
    elif source == "custom":
        if set(payload) - {"source", "base_url", "api_key", "model", "effort", "context_acknowledged"}:
            raise ModelSelectionError("自定义模型配置包含不支持的字段")
        key = payload.get("api_key")
        model = payload.get("model")
        if (not isinstance(key, str) or not key.strip() or len(key) > 4096
                or any(ord(c) < 33 or ord(c) > 126 for c in key.strip())):
            raise ModelSelectionError("请输入有效的自定义 API Key")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}", model.strip()):
            raise ModelSelectionError("请输入有效的模型 ID")
        key, model = key.strip(), model.strip()
        base = normalize_custom_base(payload.get("base_url"))
        # These fixed official origins also work behind local DNS proxies that
        # return synthetic private addresses. Arbitrary user origins still go
        # through the SSRF guard, and HTTP redirects remain disabled.
        official_origin = base in {STEP_BASE_URL, "https://api.stepfun.com/v1"}
        if not official_origin and not await asyncio.to_thread(is_safe_url, base):
            raise ModelSelectionError("自定义 API 地址必须可解析到公共网络，不能访问内网地址")
        endpoint = "user-custom"
    else:
        raise ModelSelectionError("请选择系统模型或自定义模型")
    caps = model_capabilities(model, base)
    effort = payload.get("effort") or caps["default_effort"]
    if effort is not None and effort not in caps["effort_options"]:
        raise ModelSelectionError("该模型不支持所选 effort，请使用供应商默认设置")
    return SelectedModel(source, model, base, key, endpoint, effort)


class ModelSelectionMiddleware:
    """Pure ASGI scope: also covers streaming bodies and child graph tasks."""

    def __init__(self, app, authenticate=None):
        self.app = app
        self.authenticate = authenticate

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") == "OPTIONS" or not is_model_generation_path(scope.get("path", "")):
            return await self.app(scope, receive, send)
        encoded = next((v for k, v in scope.get("headers", []) if k.lower() == MODEL_HEADER), None)
        from fastapi import HTTPException
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        if encoded is None:
            try:
                selected = resolve_default_model()
            except RuntimeError:
                return await JSONResponse({"detail": {"code": "model_unavailable", "message": "系统模型尚未配置，请联系管理员。"}}, status_code=503)(scope, receive, send)
        else:
            try:
                await require_model_user(Request(scope, receive), self.authenticate)
            except HTTPException as exc:
                return await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
            try:
                if len(encoded) > 16384:
                    raise ModelSelectionError("模型配置过长")
                payload = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
                if isinstance(payload, dict) and payload.get("source") == "custom" and payload.get("context_acknowledged") is not True:
                    raise ModelSelectionError("请先确认允许将研究上下文发送到自定义服务")
                selected = await asyncio.wait_for(resolve_selection(payload), timeout=10)
            except asyncio.TimeoutError:
                return await JSONResponse({"detail": "模型地址验证超时"}, status_code=400)(scope, receive, send)
            except (ValueError, TypeError, binascii.Error, UnicodeError) as exc:
                message = str(exc) if isinstance(exc, ModelSelectionError) else "模型配置无法解析"
                return await JSONResponse({"detail": message}, status_code=400)(scope, receive, send)
        token = _selected_model.set(selected)
        clients = []
        client_token = _model_clients.set(clients)
        response_started = False
        response_finished = False
        is_sse = False

        async def observe_send(message):
            nonlocal response_started, response_finished, is_sse
            if message["type"] == "http.response.start":
                response_started = True
                is_sse = any(k.lower() == b"content-type" and b"text/event-stream" in v for k, v in message.get("headers", []))
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                response_finished = True
            await send(message)

        try:
            if selected.source == "custom":
                await asyncio.wait_for(self.app(scope, receive, observe_send), timeout=CUSTOM_REQUEST_TIMEOUT_SECONDS)
            else:
                await self.app(scope, receive, observe_send)
        except asyncio.TimeoutError:
            if not response_started:
                await JSONResponse({"detail": "自定义模型请求超时，请稍后重试"}, status_code=504)(scope, receive, send)
            elif not response_finished:
                body = b'data: {"type":"error","message":"Custom model request timed out"}\n\n' if is_sse else b""
                await send({"type": "http.response.body", "body": body, "more_body": False})
        finally:
            _selected_model.reset(token)
            _model_clients.reset(client_token)
            for client in clients:
                if hasattr(client, "aclose"):
                    await client.aclose()
                else:
                    client.close()
