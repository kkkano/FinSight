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
        except Exception as exc:
            traceback.print_exc()
            return {"success": False, "error": str(exc)}

    return router
