"""启动用户研究前验证同一个模型，失败时不进入工具与研究图。"""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from backend.services.llm_retry import LLMCallContext, ainvoke_configured_llm
from backend.services.run_context import remaining_timeout
from backend.services.model_selection import (
    current_model, model_client_scope, model_selection_scope, resolve_default_model,
)

logger = logging.getLogger(__name__)
PREFLIGHT_TIMEOUT_SECONDS = 60.0
MODEL_UNAVAILABLE_MESSAGE = "当前模型暂时不可用，尚未启动研究。请稍后重试或在设置中切换模型。"


def _unavailable_detail(exc: Exception) -> dict[str, str]:
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    kind = (error.get("code") or error.get("type")) if isinstance(error, dict) else None
    if kind == "real_name_required":
        return {"code": "model_account_verification_required",
                "message": "当前模型服务商要求账号完成人脸实名，尚未启动研究。请在服务商平台完成认证后重试。"}
    if kind == "model_not_found":
        return {"code": "model_not_available", "message": "所选模型不在当前连接的可用模型中，尚未启动研究。请选择该连接支持的模型。"}
    return {"code": "model_unavailable", "message": MODEL_UNAVAILABLE_MESSAGE}


async def ensure_model_available() -> None:
    try:
        selected = current_model() or resolve_default_model()
        async with asyncio.timeout(remaining_timeout(PREFLIGHT_TIMEOUT_SECONDS)), model_client_scope():
            with model_selection_scope(selected):
                response = await ainvoke_configured_llm(
                    "连接检查。仅回复 OK，不需要解释。",
                    context=LLMCallContext.create(stage="model_preflight", agent="model_preflight",
                                                  layer="preflight", max_provider_attempts=1),
                    temperature=None, max_tokens=65536,
                    request_timeout=PREFLIGHT_TIMEOUT_SECONDS,
                )
        content = response.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty_model_completion")
        if (response.response_metadata or {}).get("finish_reason") == "length":
            raise ValueError("incomplete_model_completion")
    except Exception as exc:
        logger.warning("模型前置检查失败 kind=%s status=%s", type(exc).__name__, getattr(exc, "status_code", None))
        raise HTTPException(status_code=503, detail=_unavailable_detail(exc)) from None
