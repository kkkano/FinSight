from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas import ConfigResponse
from backend.llm_config import USER_CONFIG_PATH

_SENSITIVE_FRAGMENTS = ("api_key", "apikey", "token", "secret", "password")

# 公开可写字段：纯 UI 偏好，匿名用户改了也只影响自己的本地体验，不会劫持后端。
_CONFIG_PUBLIC_KEYS = frozenset({
    "layout_mode",
    "trace_raw_enabled",
    "trace_raw_show_raw_json",
    "theme",
    "language",
    "watchlist",
})

# 敏感可写字段：任何能改变 LLM 请求目标 URL / 凭据的字段。
# 匿名用户若能写这些 → 可把全站 LLM 流量劫持到攻击者端点（窃取 prompt + 真实付费 key）。
# 这些字段的写操作必须携带有效内部 token（即使 API_AUTH_ENABLED=false 也强制校验）。
_CONFIG_SENSITIVE_KEYS = frozenset({
    "llm_provider",
    "llm_model",
    "llm_api_key",
    "llm_api_base",
    "llm_endpoints",
})

# 完整可写白名单 = 公开 + 敏感（敏感字段写入前会先过 token 守卫）。
_CONFIG_ALLOWED_KEYS = _CONFIG_PUBLIC_KEYS | _CONFIG_SENSITIVE_KEYS


def _parse_internal_api_keys() -> set[str]:
    """读取内部 API token 集合（与全局 security_gate 共用同一份配置）。"""
    raw = os.getenv("API_AUTH_KEYS") or os.getenv("API_AUTH_KEY") or ""
    return {item.strip() for item in raw.split(",") if item.strip()}


def _extract_api_key(request: Request) -> Optional[str]:
    """从请求头提取内部 token（支持 X-API-Key 与 Authorization: Bearer）。"""
    header_key = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if header_key:
        return header_key.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _require_internal_token_for_sensitive(request: Request) -> None:
    """敏感字段写守卫：请求携带敏感字段时强制要求有效内部 token。

    与 API_AUTH_ENABLED 解耦——即便全局认证关闭（线上当前默认），
    改写 LLM 端点/凭据这类高危操作也必须出示内部 token，
    否则匿名用户可劫持全站 LLM 请求目标。
    """
    keys = _parse_internal_api_keys()
    if not keys:
        # 未配置任何内部 token → 无法安全放行敏感写操作，直接拒绝。
        raise HTTPException(
            status_code=403,
            detail="敏感配置写操作未启用：服务端未配置内部访问令牌",
        )
    provided = _extract_api_key(request)
    if not provided or provided not in keys:
        raise HTTPException(status_code=403, detail="敏感配置写操作需要有效的内部访问令牌")


def _mask_value(value: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    return "*" * len(raw)


def _redact_config(obj: Any) -> Any:
    if isinstance(obj, dict):
        redacted: dict[str, Any] = {}
        for key, val in obj.items():
            key_lower = str(key).lower()
            if any(frag in key_lower for frag in _SENSITIVE_FRAGMENTS):
                redacted[key] = _mask_value(str(val))
            elif isinstance(val, (dict, list)):
                redacted[key] = _redact_config(val)
            else:
                redacted[key] = val
        return redacted
    if isinstance(obj, list):
        return [_redact_config(item) for item in obj]
    return obj


def _filter_allowed_keys(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k in _CONFIG_ALLOWED_KEYS}


def _split_public_sensitive(payload: dict) -> tuple[dict, dict]:
    """把请求体拆成（公开可写字段, 敏感可写字段），其余键直接丢弃。"""
    public = {k: v for k, v in payload.items() if k in _CONFIG_PUBLIC_KEYS}
    sensitive = {k: v for k, v in payload.items() if k in _CONFIG_SENSITIVE_KEYS}
    return public, sensitive


def _looks_masked_secret(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if not raw:
        return False
    return "***" in raw or bool(re.fullmatch(r"\*+", raw))


def _preserve_secret_if_masked(incoming_value: Any, existing_value: Any) -> Any:
    if incoming_value is None:
        return existing_value if existing_value else incoming_value

    incoming = str(incoming_value).strip()
    if not incoming and existing_value:
        return existing_value
    if _looks_masked_secret(incoming) and existing_value:
        return existing_value
    return incoming


def _merge_llm_endpoints(existing_value: Any, incoming_value: Any) -> Any:
    if not isinstance(incoming_value, list):
        return incoming_value

    existing_endpoints = [ep for ep in (existing_value or []) if isinstance(ep, dict)] if isinstance(existing_value, list) else []
    existing_by_name: dict[str, dict] = {}
    for ep in existing_endpoints:
        name = str(ep.get("name") or "").strip()
        if name and name not in existing_by_name:
            existing_by_name[name] = ep

    merged: list[dict] = []
    for idx, ep in enumerate(incoming_value):
        if not isinstance(ep, dict):
            continue
        row = dict(ep)
        name = str(row.get("name") or "").strip()
        existing_row = existing_by_name.get(name)
        if existing_row is None and idx < len(existing_endpoints):
            existing_row = existing_endpoints[idx]

        row["api_key"] = _preserve_secret_if_masked(
            row.get("api_key"),
            (existing_row or {}).get("api_key") if isinstance(existing_row, dict) else None,
        )
        merged.append(row)

    return merged


@dataclass(frozen=True)
class ConfigRouterDeps:
    project_root: str
    logger: Any


def create_config_router(deps: ConfigRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Config"])

    @router.get("/api/config", response_model=ConfigResponse)
    async def get_config():
        try:
            config_file = USER_CONFIG_PATH

            try:
                with open(config_file, "r", encoding="utf-8") as file_obj:
                    saved_config = json.load(file_obj)
                return {"success": True, "config": _redact_config(saved_config)}
            except FileNotFoundError:
                return {
                    "success": True,
                    "config": {
                        "llm_provider": None,
                        "llm_model": None,
                        "llm_api_key": None,
                        "llm_api_base": None,
                        "llm_endpoints": [],
                        "layout_mode": "centered",
                        "trace_raw_enabled": True,
                        "trace_raw_show_raw_json": True,
                    },
                }
        except Exception as exc:
            # 详细异常只进日志，对外返回通用消息。
            deps.logger.error("[Config] get_config 失败: %s", exc, exc_info=True)
            return {"success": False, "error": "配置读取失败，请稍后重试"}

    @router.post("/api/config")
    async def save_config(payload: dict, request: Request):
        try:
            config_file = USER_CONFIG_PATH

            # 拆分公开字段（UI 偏好，任意人可写）与敏感字段（LLM 端点/凭据）。
            public_fields, sensitive_fields = _split_public_sensitive(payload)

            # 关键防护：请求体一旦包含敏感字段，必须出示有效内部 token，
            # 否则匿名用户可改写全站 LLM 请求目标（劫持 + 窃取 prompt/付费 key）。
            # 守卫失败抛 403（即使 API_AUTH_ENABLED=false 也校验）。
            if sensitive_fields:
                _require_internal_token_for_sensitive(request)

            # Load existing config to merge (preserve keys not in whitelist)
            existing: dict = {}
            try:
                with open(config_file, "r", encoding="utf-8") as file_obj:
                    existing = json.load(file_obj)
            except (FileNotFoundError, json.JSONDecodeError):
                pass

            # 已通过守卫的敏感字段 + 公开字段合并为最终允许写入的集合。
            filtered = {**public_fields, **sensitive_fields}

            if "llm_api_key" in filtered:
                filtered["llm_api_key"] = _preserve_secret_if_masked(
                    filtered.get("llm_api_key"),
                    existing.get("llm_api_key"),
                )

            if "llm_endpoints" in filtered:
                filtered["llm_endpoints"] = _merge_llm_endpoints(
                    existing.get("llm_endpoints"),
                    filtered.get("llm_endpoints"),
                )

            merged = {**existing, **filtered}

            with open(config_file, "w", encoding="utf-8") as file_obj:
                json.dump(merged, file_obj, indent=2, ensure_ascii=False)

            deps.logger.info("[Config] saved to %s (filtered %d keys)", config_file, len(filtered))
            return {"success": True, "message": "配置已保存"}
        except HTTPException:
            # 守卫拒绝（403）原样抛出，由 FastAPI 转成标准错误响应。
            raise
        except Exception as exc:
            # 详细异常只进日志，对外返回通用消息，避免泄露内部路径/堆栈。
            deps.logger.error("[Config] save_config 失败: %s", exc, exc_info=True)
            return {"success": False, "error": "配置保存失败，请稍后重试"}

    return router
