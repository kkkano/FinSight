from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter

from backend.api.schemas import ConfigResponse

_SENSITIVE_FRAGMENTS = ("api_key", "apikey", "token", "secret", "password")

_CONFIG_ALLOWED_KEYS = frozenset({
    "llm_provider",
    "llm_model",
    "llm_api_key",
    "llm_api_base",
    "llm_endpoints",
    "layout_mode",
    "trace_raw_enabled",
    "trace_raw_show_raw_json",
    "theme",
    "language",
    "watchlist",
})


def _mask_value(value: str) -> str:
    raw = str(value or "")
    if len(raw) <= 8:
        return "***"
    return f"{raw[:3]}***{raw[-3:]}"


def _redact_config(obj: Any) -> Any:
    if isinstance(obj, dict):
        redacted: dict[str, Any] = {}
        for key, val in obj.items():
            key_lower = str(key).lower()
            if any(frag in key_lower for frag in _SENSITIVE_FRAGMENTS):
                redacted[key] = _mask_value(str(val)) if val else "***"
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


@dataclass(frozen=True)
class ConfigRouterDeps:
    project_root: str
    logger: Any


def create_config_router(deps: ConfigRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Config"])

    @router.get("/api/config", response_model=ConfigResponse)
    async def get_config():
        try:
            config_file = f"{deps.project_root}/user_config.json"

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
            return {"success": False, "error": str(exc)}

    @router.post("/api/config")
    async def save_config(request: dict):
        try:
            config_file = f"{deps.project_root}/user_config.json"

            # Load existing config to merge (preserve keys not in whitelist)
            existing: dict = {}
            try:
                with open(config_file, "r", encoding="utf-8") as file_obj:
                    existing = json.load(file_obj)
            except (FileNotFoundError, json.JSONDecodeError):
                pass

            # Only allow whitelisted keys from user input
            filtered = _filter_allowed_keys(request)
            merged = {**existing, **filtered}

            with open(config_file, "w", encoding="utf-8") as file_obj:
                json.dump(merged, file_obj, indent=2, ensure_ascii=False)

            deps.logger.info("[Config] saved to %s (filtered %d keys)", config_file, len(filtered))
            return {"success": True, "message": "配置已保存"}
        except Exception as exc:
            traceback.print_exc()
            return {"success": False, "error": str(exc)}

    return router
