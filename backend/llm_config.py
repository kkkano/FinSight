"""Load and rotate LLM endpoint configs (hot-reload from user_config.json)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from dotenv import load_dotenv

from backend.services.langfuse_tracer import get_langfuse_callback

logger = logging.getLogger(__name__)


load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_CONFIG_PATH = os.path.join(PROJECT_ROOT, "user_config.json")

PROVIDER_ALIASES = {
    "gemini_proxy": "openai_compatible",
    "openai_compatible": "openai_compatible",
    "openai": "openai",
    "anyscale": "anyscale",
    "anthropic": "anthropic",
    "custom": "openai_compatible",
    "deepseek": "openai_compatible",
}


def _canonical_provider(provider: str | None) -> str:
    key = str(provider or "openai_compatible").strip().lower()
    return PROVIDER_ALIASES.get(key, key)


def _default_provider() -> str:
    return _canonical_provider(os.getenv("LLM_PROVIDER") or "openai_compatible")


def _looks_full_chat_completions_url(api_base: str | None) -> bool:
    if not api_base:
        return False
    normalized = str(api_base).strip().rstrip("/").lower()
    return normalized.endswith("/v1/chat/completions") or normalized.endswith("/chat/completions")


def _to_chatopenai_base(api_base: str | None) -> str | None:
    """Convert full chat-completions endpoint to ChatOpenAI-compatible base URL.

    ChatOpenAI expects a base URL (typically ending with /v1) and appends
    /chat/completions internally. If caller provides a full endpoint URL,
    we normalize it here to avoid duplicated path segments.
    """
    if not api_base:
        return api_base
    normalized = str(api_base).strip().rstrip("/")
    if normalized.endswith("/v1/chat/completions"):
        return normalized[: -len("/chat/completions")]
    if normalized.endswith("/chat/completions"):
        base = normalized[: -len("/chat/completions")]
        return base if base.endswith("/v1") else (base + "/v1")
    return normalized


def _normalize_api_base(api_base: str | None, *, raw: bool = False) -> str | None:
    if not api_base:
        return api_base
    normalized = str(api_base).strip().rstrip("/")
    if raw or _looks_full_chat_completions_url(normalized):
        return normalized
    if normalized and not normalized.endswith("/v1"):
        normalized = normalized + "/v1"
    return normalized


def _load_user_config() -> dict:
    if os.path.exists(USER_CONFIG_PATH):
        try:
            with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
                if isinstance(payload, dict):
                    return payload
        except Exception as exc:
            logger.info("[Config] Failed to load user_config.json: %s", exc)
    return {}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _mask(value: str | None) -> str:
    raw = str(value or "")
    if len(raw) <= 8:
        return "***"
    return f"{raw[:3]}***{raw[-3:]}"


# Compatibility map for modules that still import LLM_CONFIGS directly.
LLM_CONFIGS = {
    "openai_compatible": {
        "api_key": os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.getenv("GEMINI_PROXY_API_KEY"),
        "api_base": _normalize_api_base(os.getenv("OPENAI_COMPATIBLE_API_BASE") or os.getenv("GEMINI_PROXY_API_BASE")),
        "models": [
            os.getenv("OPENAI_COMPATIBLE_MODEL", "").strip() or "gpt-4o-mini",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ],
    },
    "gemini_proxy": {
        "api_key": os.getenv("GEMINI_PROXY_API_KEY"),
        "api_base": _normalize_api_base(os.getenv("GEMINI_PROXY_API_BASE")),
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-preview-05-20"],
    },
    "openai": {
        "api_key": os.getenv("OPENAI_API_KEY"),
        "api_base": _normalize_api_base(os.getenv("OPENAI_API_BASE")),
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
    },
    "anyscale": {
        "api_key": os.getenv("ANYSCALE_API_KEY"),
        "api_base": _normalize_api_base(os.getenv("ANYSCALE_API_BASE")),
        "models": ["meta-llama/Llama-3-8b-chat-hf", "meta-llama/Llama-3-70b-chat-hf"],
    },
    "anthropic": {
        "api_key": os.getenv("ANTHROPIC_API_KEY"),
        "api_base": _normalize_api_base(os.getenv("ANTHROPIC_API_BASE")),
        "models": ["claude-3-sonnet-20240229", "claude-3-opus-20240229"],
    },
}


@dataclass
class EndpointConfig:
    name: str
    provider: str
    api_base: str | None
    api_key: str
    model: str
    weight: int = 1
    enabled: bool = True
    cooldown_sec: int = 60
    raw_url: bool = False


@dataclass
class EndpointRuntime:
    cfg: EndpointConfig
    cooldown_until: float = 0.0
    current_weight: int = 0

    @property
    def is_available(self) -> bool:
        return self.cfg.enabled and time.time() >= self.cooldown_until


@dataclass
class EndpointManager:
    endpoints: list[EndpointRuntime] = field(default_factory=list)
    fingerprint: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _sync_if_changed(self, specs: list[EndpointConfig]) -> None:
        fingerprint = "|".join(
            f"{s.name}:{s.provider}:{s.api_base}:{s.model}:{s.weight}:{int(s.enabled)}:{s.cooldown_sec}:{int(s.raw_url)}"
            for s in specs
        )
        if fingerprint == self.fingerprint:
            return
        self.endpoints = [EndpointRuntime(cfg=s) for s in specs]
        self.fingerprint = fingerprint

    def select(self) -> EndpointConfig:
        with self.lock:
            available = [ep for ep in self.endpoints if ep.is_available]
            if not available:
                if not self.endpoints:
                    raise ValueError("No LLM endpoint available")
                # All cooling down: pick the one with earliest recovery.
                available = [min(self.endpoints, key=lambda ep: ep.cooldown_until)]

            total_weight = 0
            winner: EndpointRuntime | None = None
            for ep in available:
                weight = max(1, int(ep.cfg.weight))
                total_weight += weight
                ep.current_weight += weight
                if winner is None or ep.current_weight > winner.current_weight:
                    winner = ep

            if winner is None:
                raise ValueError("No LLM endpoint available")

            winner.current_weight -= max(1, total_weight)
            return winner.cfg

    def report_failure(self, endpoint_name: str, *, reason: str | None = None) -> None:
        with self.lock:
            for ep in self.endpoints:
                if ep.cfg.name != endpoint_name:
                    continue
                ep.cooldown_until = time.time() + max(1, int(ep.cfg.cooldown_sec))
                ep.current_weight = 0
                logger.warning(
                    "[LLM Rotation] endpoint cooling down: name=%s cooldown=%ss reason=%s",
                    endpoint_name,
                    ep.cfg.cooldown_sec,
                    (reason or "unknown")[:180],
                )
                return

    def report_success(self, endpoint_name: str) -> None:
        with self.lock:
            for ep in self.endpoints:
                if ep.cfg.name == endpoint_name and ep.cooldown_until > 0 and time.time() >= ep.cooldown_until:
                    ep.cooldown_until = 0.0
                    logger.info("[LLM Rotation] endpoint restored: name=%s", endpoint_name)
                    return


_ENDPOINT_MANAGER = EndpointManager()
_LLM_BINDINGS: dict[int, str] = {}
_LLM_BINDINGS_LOCK = threading.Lock()


def _safe_endpoint_name(value: Any, default_name: str) -> str:
    text = str(value or "").strip()
    return text or default_name


def _parse_user_endpoints(user_config: dict, provider: str, model: str | None) -> list[EndpointConfig]:
    endpoints: list[EndpointConfig] = []
    default_cooldown = _env_int("LLM_ENDPOINT_DEFAULT_COOLDOWN_SEC", 90)

    raw_list = user_config.get("llm_endpoints")
    if isinstance(raw_list, list):
        for idx, raw in enumerate(raw_list):
            if not isinstance(raw, dict):
                continue
            enabled = bool(raw.get("enabled", True))
            if not enabled:
                continue

            api_key = str(raw.get("api_key") or "").strip()
            raw_api_base = str(raw.get("api_base") or "").strip()
            is_raw_url = bool(raw.get("raw_url", False)) or _looks_full_chat_completions_url(raw_api_base)
            api_base = _normalize_api_base(raw_api_base, raw=is_raw_url)
            endpoint_model = str(raw.get("model") or model or "gpt-4o-mini").strip()
            if not api_key:
                continue
            endpoint_provider = _canonical_provider(raw.get("provider") or provider)

            endpoints.append(
                EndpointConfig(
                    name=_safe_endpoint_name(raw.get("name"), f"ep-{idx+1}"),
                    provider=endpoint_provider,
                    api_base=api_base,
                    api_key=api_key,
                    model=endpoint_model,
                    weight=max(1, int(raw.get("weight", 1) or 1)),
                    enabled=True,
                    cooldown_sec=max(1, int(raw.get("cooldown_sec", default_cooldown) or default_cooldown)),
                    raw_url=is_raw_url,
                )
            )

    if endpoints:
        return endpoints

    # Legacy single-endpoint compatibility (llm_api_key/base/model)
    legacy_key = str(user_config.get("llm_api_key") or "").strip()
    if legacy_key:
        legacy_api_base = str(user_config.get("llm_api_base") or "").strip()
        legacy_raw_url = _looks_full_chat_completions_url(legacy_api_base)
        endpoints.append(
            EndpointConfig(
                name="legacy-single",
                provider=_canonical_provider(user_config.get("llm_provider") or provider),
                api_base=_normalize_api_base(legacy_api_base, raw=legacy_raw_url),
                api_key=legacy_key,
                model=str(user_config.get("llm_model") or model or "gpt-4o-mini").strip(),
                weight=1,
                enabled=True,
                cooldown_sec=default_cooldown,
                raw_url=legacy_raw_url,
            )
        )
    return endpoints


def _parse_env_endpoints(provider: str, model: str | None) -> list[EndpointConfig]:
    endpoint_model = str(model or "").strip()
    endpoints: list[EndpointConfig] = []

    def _try_add(name: str, provider_name: str, key_env: str, base_env: str | None, fallback_model: str) -> None:
        api_key = str(os.getenv(key_env, "") or "").strip()
        if not api_key:
            return
        raw_api_base = str(os.getenv(base_env, "") or "").strip() if base_env else ""
        is_raw_url = _looks_full_chat_completions_url(raw_api_base)
        api_base = _normalize_api_base(raw_api_base, raw=is_raw_url) if base_env else None
        endpoints.append(
            EndpointConfig(
                name=name,
                provider=_canonical_provider(provider_name),
                api_base=api_base,
                api_key=api_key,
                model=endpoint_model or fallback_model,
                weight=1,
                enabled=True,
                cooldown_sec=_env_int("LLM_ENDPOINT_DEFAULT_COOLDOWN_SEC", 90),
                raw_url=is_raw_url,
            )
        )

    canonical = _canonical_provider(provider)
    if canonical == "openai_compatible":
        _try_add("openai-compatible-primary", "openai_compatible", "OPENAI_COMPATIBLE_API_KEY", "OPENAI_COMPATIBLE_API_BASE", "gpt-4o-mini")
        _try_add("gemini-proxy", "openai_compatible", "GEMINI_PROXY_API_KEY", "GEMINI_PROXY_API_BASE", "gemini-2.5-flash")
        _try_add("openai-primary", "openai", "OPENAI_API_KEY", "OPENAI_API_BASE", "gpt-4o")
    elif canonical == "openai":
        _try_add("openai-primary", "openai", "OPENAI_API_KEY", "OPENAI_API_BASE", "gpt-4o")
    elif canonical == "anyscale":
        _try_add("anyscale-primary", "anyscale", "ANYSCALE_API_KEY", "ANYSCALE_API_BASE", "meta-llama/Llama-3-8b-chat-hf")
    elif canonical == "anthropic":
        _try_add("anthropic-primary", "anthropic", "ANTHROPIC_API_KEY", "ANTHROPIC_API_BASE", "claude-3-sonnet-20240229")
    return endpoints


def _resolve_endpoints(provider: str, model: str | None) -> list[EndpointConfig]:
    user_config = _load_user_config()
    endpoints = _parse_user_endpoints(user_config, provider, model)
    if endpoints:
        return endpoints

    env_endpoints = _parse_env_endpoints(provider, model)
    if env_endpoints:
        return env_endpoints

    raise ValueError(
        "No LLM endpoint configured. Provide user_config.llm_endpoints[] or llm_api_key/llm_api_base, "
        "or set OPENAI_COMPATIBLE_API_KEY / GEMINI_PROXY_API_KEY."
    )


def load_user_endpoints(provider: str | None = None, model: str | None = None) -> list[EndpointConfig]:
    """Compatibility helper for diagnostics scripts.

    Returns resolved endpoint list from `user_config.json` or env fallback,
    without selecting/rotating any endpoint.
    """
    canonical = _canonical_provider(provider or _default_provider())
    return _resolve_endpoints(canonical, model)


def get_llm_config(provider: str | None = None, model: str | None = None) -> dict:
    canonical = _canonical_provider(provider or _default_provider())
    endpoints = _resolve_endpoints(canonical, model)
    _ENDPOINT_MANAGER._sync_if_changed(endpoints)
    selected = _ENDPOINT_MANAGER.select()

    logger.info(
        "[LLM Rotation] select endpoint name=%s provider=%s model=%s api_base=%s api_key=%s",
        selected.name,
        selected.provider,
        selected.model,
        selected.api_base,
        _mask(selected.api_key),
    )
    return {
        "provider": selected.provider,
        "api_key": selected.api_key,
        "api_base": selected.api_base,
        "model": selected.model,
        "temperature": 0.3,
        "endpoint_name": selected.name,
    }


def bind_llm_instance(llm: Any, endpoint_name: str) -> None:
    with _LLM_BINDINGS_LOCK:
        _LLM_BINDINGS[id(llm)] = endpoint_name


def report_llm_success(llm: Any) -> None:
    with _LLM_BINDINGS_LOCK:
        endpoint_name = _LLM_BINDINGS.get(id(llm))
    if endpoint_name:
        _ENDPOINT_MANAGER.report_success(endpoint_name)


def report_llm_failure(llm: Any, error: BaseException | str | None = None) -> None:
    with _LLM_BINDINGS_LOCK:
        endpoint_name = _LLM_BINDINGS.get(id(llm))
    if endpoint_name:
        _ENDPOINT_MANAGER.report_failure(endpoint_name, reason=str(error or "unknown"))


def create_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    request_timeout: int = 600,
):
    from langchain_openai import ChatOpenAI

    cfg = get_llm_config(provider=provider, model=model)
    api_key = cfg.get("api_key")
    api_base = cfg.get("api_base")
    sdk_api_base = _to_chatopenai_base(api_base)
    model_name = cfg.get("model")
    endpoint_name = str(cfg.get("endpoint_name") or "unknown")

    resolved_max_tokens = max_tokens
    if resolved_max_tokens is None:
        resolved_max_tokens = _env_int("LLM_MAX_TOKENS", 8192)
    resolved_max_tokens = max(256, int(resolved_max_tokens))

    if not api_key:
        resolved_provider = str(cfg.get("provider") or provider or _default_provider())
        raise ValueError(f"API key not found for provider '{resolved_provider}'")

    logger.info(
        "[LLM Factory] create endpoint=%s provider=%s model=%s api_base=%s sdk_api_base=%s timeout=%ss",
        endpoint_name,
        cfg.get("provider"),
        model_name,
        api_base,
        sdk_api_base,
        request_timeout,
    )

    callbacks = []
    langfuse_cb = get_langfuse_callback()
    if langfuse_cb is not None:
        callbacks.append(langfuse_cb)

    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=sdk_api_base,
        temperature=temperature,
        max_tokens=resolved_max_tokens,
        request_timeout=request_timeout,
        max_retries=3,
        callbacks=callbacks or None,
    )
    bind_llm_instance(llm, endpoint_name)
    return llm


LANGSMITH_CONFIG = {
    "api_key": os.getenv("LANGSMITH_API_KEY", ""),
    "project": os.getenv("LANGSMITH_PROJECT", "FinSight"),
    "endpoint": os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
    "enabled": os.getenv("ENABLE_LANGSMITH", "false").lower() in ("true", "1", "yes"),
}


__all__ = [
    "LLM_CONFIGS",
    "LANGSMITH_CONFIG",
    "load_user_endpoints",
    "get_llm_config",
    "create_llm",
    "report_llm_failure",
    "report_llm_success",
]
