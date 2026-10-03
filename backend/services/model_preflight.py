"""启动用户研究前验证同一个模型，失败时不进入工具与研究图。"""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException

from backend.llm_config import EndpointConfig, create_llm_for_endpoint
from backend.services.model_selection import (
    current_model, model_client_scope, model_selection_scope, resolve_default_model,
)

logger = logging.getLogger(__name__)
PREFLIGHT_TIMEOUT_SECONDS = 60.0
MODEL_UNAVAILABLE_MESSAGE = "当前模型暂时不可用，尚未启动研究。请稍后重试或在设置中切换模型。"


async def ensure_model_available() -> None:
    try:
        selected = current_model() or resolve_default_model()
        cfg = EndpointConfig(selected.endpoint_name, "openai_compatible", selected.base_url,
                             selected.api_key, selected.model)
        async with asyncio.timeout(PREFLIGHT_TIMEOUT_SECONDS), model_client_scope():
            with model_selection_scope(selected):
                llm = create_llm_for_endpoint(cfg, temperature=None, max_tokens=65536,
                                              request_timeout=PREFLIGHT_TIMEOUT_SECONDS)
                response = await llm.ainvoke("连接检查。仅回复 OK，不需要解释。")
        content = response.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty_model_completion")
        if (response.response_metadata or {}).get("finish_reason") == "length":
            raise ValueError("incomplete_model_completion")
    except Exception as exc:
        logger.warning("模型前置检查失败 kind=%s status=%s", type(exc).__name__, getattr(exc, "status_code", None))
        raise HTTPException(status_code=503, detail={"code": "model_unavailable", "message": MODEL_UNAVAILABLE_MESSAGE}) from None
