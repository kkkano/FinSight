"""Load and rotate LLM endpoint configs (hot-reload from user_config.json)."""

from __future__ import annotations

from backend.utils.env import env_int as _env_int

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

from backend.services.langfuse_tracer import get_langfuse_callback

logger = logging.getLogger(__name__)


load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# In Docker, FINSIGHT_CONFIG_DIR=/app/data (mounted as named volume → persists across restarts).
# Locally, falls back to PROJECT_ROOT for backward compatibility.
_USER_CONFIG_DIR = os.getenv("FINSIGHT_CONFIG_DIR") or PROJECT_ROOT
USER_CONFIG_PATH = os.path.join(_USER_CONFIG_DIR, "user_config.json")

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


def _mask(value: str | None) -> str:
    raw = str(value or "")
    if len(raw) <= 8:
        return "***"
    return f"{raw[:3]}***{raw[-3:]}"


# Compatibility map for modules that still import LLM_CONFIGS directly.
LLM_CONFIGS = {
    "openai_compatible": {
        "api_key": os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.getenv("GEMINI_PROXY_API_KEY"),
        "api_base": _normalize_api_base(
            os.getenv("OPENAI_COMPATIBLE_API_BASE")
            or os.getenv("GEMINI_PROXY_API_BASE")
        ),
        "models": [
            item
            for item in (
                os.getenv("OPENAI_COMPATIBLE_MODEL", "").strip(),
                "gemini-2.5-flash",
                "gemini-2.5-pro",
            )
            if item
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
    failure_domain: str = ""


@dataclass(frozen=True)
class ConfiguredLLMHandle:
    """Non-network handle used by agents that historically stored a raw client."""

    temperature: float = 0.3
    model_name: str = "configured-at-invocation"


class AllEndpointsCoolingDown(RuntimeError):
    code = "all_endpoints_cooling_down"

    def __init__(self, *, retry_after_seconds: int, endpoint_names: tuple[str, ...]) -> None:
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        self.endpoint_names = endpoint_names
        super().__init__(self.code)


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

    def select(
        self,
        *,
        exclude_names: set[str] | None = None,
        prefer_different_failure_domain: str | None = None,
    ) -> EndpointConfig:
        with self.lock:
            enabled = [ep for ep in self.endpoints if ep.cfg.enabled]
            available = [ep for ep in enabled if ep.is_available and ep.cfg.name not in (exclude_names or set())]
            if not available:
                if not enabled:
                    raise ValueError("No LLM endpoint available")
                cooldowns = [ep.cooldown_until for ep in enabled]
                retry_after = max(1, int(__import__("math").ceil(min(cooldowns) - time.time())))
                raise AllEndpointsCoolingDown(
                    retry_after_seconds=retry_after,
                    endpoint_names=tuple(ep.cfg.name for ep in enabled),
                )

            if prefer_different_failure_domain:
                different = [ep for ep in available if ep.cfg.failure_domain != prefer_different_failure_domain]
                if different:
                    available = different

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

    def report_failure(
        self,
        endpoint_name: str,
        *,
        reason: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        with self.lock:
            for ep in self.endpoints:
                if ep.cfg.name != endpoint_name:
                    continue
                retry_after = min(300, max(0, int(retry_after_seconds or 0)))
                cooldown_seconds = max(1, int(ep.cfg.cooldown_sec), retry_after)
                ep.cooldown_until = time.time() + cooldown_seconds
                ep.current_weight = 0
                logger.warning(
                    "[LLM Rotation] endpoint cooling down: name=%s cooldown=%ss reason=%s",
                    endpoint_name,
                    cooldown_seconds,
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


def _failure_domain(value: Any, api_base: str | None, fallback: str) -> str:
    configured = str(value or "").strip().lower()
    if configured:
        return configured
    try:
        hostname = (urlparse(str(api_base or "")).hostname or "").strip().lower()
    except ValueError:
        hostname = ""
    return hostname or fallback


def _endpoint_config_error() -> RuntimeError:
    return RuntimeError(
        "LLM endpoint not configured: set OPENAI_COMPATIBLE_API_BASE / "
        "OPENAI_COMPATIBLE_MODEL (and OPENAI_COMPATIBLE_API_KEY) in .env.server "
        "- see .env.server.example"
    )


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

            endpoint_provider = _canonical_provider(raw.get("provider") or provider)
            api_key = str(raw.get("api_key") or "").strip()
            if not api_key:
                continue
            raw_api_base = str(raw.get("api_base") or "").strip()
            is_raw_url = bool(raw.get("raw_url", False)) or _looks_full_chat_completions_url(raw_api_base)
            api_base = _normalize_api_base(raw_api_base, raw=is_raw_url)
            raw_model = str(raw.get("model") or "").strip()
            if raw_model:
                endpoint_model = raw_model
            elif model:
                endpoint_model = str(model).strip()
            else:
                raise _endpoint_config_error()
            if endpoint_provider == "openai_compatible" and not raw_api_base:
                raise _endpoint_config_error()
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
                    failure_domain=_failure_domain(raw.get("failure_domain"), api_base, _safe_endpoint_name(raw.get("name"), f"ep-{idx+1}")),
                )
            )

    if endpoints:
        return endpoints

    # Legacy single-endpoint compatibility (llm_api_key/base/model)
    legacy_key = str(user_config.get("llm_api_key") or "").strip()
    if legacy_key:
        legacy_api_base = str(user_config.get("llm_api_base") or "").strip()
        legacy_provider = _canonical_provider(user_config.get("llm_provider") or provider)
        legacy_raw_url = _looks_full_chat_completions_url(legacy_api_base)
        legacy_model = str(user_config.get("llm_model") or "").strip() or (str(model).strip() if model else "")
        if not legacy_model or (legacy_provider == "openai_compatible" and not legacy_api_base):
            raise _endpoint_config_error()
        endpoints.append(
            EndpointConfig(
                name="legacy-single",
                provider=legacy_provider,
                api_base=_normalize_api_base(legacy_api_base, raw=legacy_raw_url),
                api_key=legacy_key,
                model=legacy_model,
                weight=1,
                enabled=True,
                cooldown_sec=default_cooldown,
                raw_url=legacy_raw_url,
                failure_domain=_failure_domain(None, _normalize_api_base(legacy_api_base, raw=legacy_raw_url), "legacy-single"),
            )
        )
    return endpoints


def _parse_env_endpoints(provider: str, model: str | None) -> list[EndpointConfig]:
    endpoint_model = str(model or "").strip()
    endpoints: list[EndpointConfig] = []

    def _try_add(
        name: str,
        provider_name: str,
        key_env: str,
        base_env: str | None,
        fallback_model: str,
        fallback_base: str | None = None,
    ) -> None:
        api_key = str(os.getenv(key_env, "") or "").strip()
        if not api_key:
            return
        raw_api_base = str(os.getenv(base_env, "") or "").strip() if base_env else ""
        if not raw_api_base and fallback_base:
            raw_api_base = fallback_base
        resolved_provider = _canonical_provider(provider_name)
        resolved_model = endpoint_model or fallback_model
        if resolved_provider == "openai_compatible" and (not raw_api_base or not resolved_model):
            return
        is_raw_url = _looks_full_chat_completions_url(raw_api_base)
        api_base = _normalize_api_base(raw_api_base, raw=is_raw_url) if base_env else None
        endpoints.append(
            EndpointConfig(
                name=name,
                provider=resolved_provider,
                api_base=api_base,
                api_key=api_key,
                model=resolved_model,
                weight=1,
                enabled=True,
                cooldown_sec=_env_int("LLM_ENDPOINT_DEFAULT_COOLDOWN_SEC", 90),
                raw_url=is_raw_url,
                failure_domain=_failure_domain(None, api_base, name),
            )
        )

    canonical = _canonical_provider(provider)
    if canonical == "openai_compatible":
        _oc_model = str(os.getenv("OPENAI_COMPATIBLE_MODEL", "") or "").strip()
        _try_add(
            "openai-compatible-primary",
            "openai_compatible",
            "OPENAI_COMPATIBLE_API_KEY",
            "OPENAI_COMPATIBLE_API_BASE",
            _oc_model,
        )
        _try_add(
            "gemini-proxy",
            "openai_compatible",
            "GEMINI_PROXY_API_KEY",
            "GEMINI_PROXY_API_BASE",
            str(os.getenv("GEMINI_PROXY_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash").strip(),
        )
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

    raise _endpoint_config_error()


def load_user_endpoints(provider: str | None = None, model: str | None = None) -> list[EndpointConfig]:
    """Compatibility helper for diagnostics scripts.

    Returns resolved endpoint list from `user_config.json` or env fallback,
    without selecting/rotating any endpoint.
    """
    canonical = _canonical_provider(provider or _default_provider())
    return _resolve_endpoints(canonical, model)


def get_endpoint_manager(provider: str | None = None, model: str | None = None) -> EndpointManager:
    """Resolve endpoint configuration without selecting or creating a client."""
    canonical = _canonical_provider(provider or _default_provider())
    endpoints = _resolve_endpoints(canonical, model)
    _ENDPOINT_MANAGER._sync_if_changed(endpoints)
    return _ENDPOINT_MANAGER


def get_llm_config(provider: str | None = None, model: str | None = None) -> dict:
    manager = get_endpoint_manager(provider=provider, model=model)
    selected = manager.select()

    logger.info(
        "[LLM] select endpoint name=%s provider=%s model=%s failure_domain=%s",
        selected.name,
        selected.provider,
        selected.model,
        selected.failure_domain,
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


def create_llm_for_endpoint(
    cfg: EndpointConfig,
    *,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    request_timeout: int = 600,
):
    """Build one client for an already selected endpoint without re-selecting."""
    from langchain_openai import ChatOpenAI

    api_key = cfg.api_key
    sdk_api_base = _to_chatopenai_base(cfg.api_base)
    if not api_key:
        raise ValueError(f"API key not found for provider '{cfg.provider}'")
    resolved_max_tokens = max(256, int(max_tokens if max_tokens is not None else _env_int("LLM_MAX_TOKENS", 8192)))
    callbacks = []
    langfuse_cb = get_langfuse_callback()
    if langfuse_cb is not None:
        callbacks.append(langfuse_cb)
    llm = ChatOpenAI(
        model=cfg.model,
        openai_api_key=api_key,
        openai_api_base=sdk_api_base,
        temperature=temperature,
        max_tokens=resolved_max_tokens,
        request_timeout=request_timeout,
        max_retries=0,
        callbacks=callbacks or None,
    )
    bind_llm_instance(llm, cfg.name)
    return llm


def create_llm(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    request_timeout: int = 600,
    max_retries: int | None = None,
):
    cfg = get_llm_config(provider=provider, model=model)
    endpoint = EndpointConfig(
        name=str(cfg.get("endpoint_name") or "unknown"), provider=str(cfg["provider"]),
        api_base=cfg.get("api_base"), api_key=str(cfg["api_key"]), model=str(cfg["model"]),
    )
    return create_llm_for_endpoint(endpoint, temperature=temperature, max_tokens=max_tokens, request_timeout=request_timeout)


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
    "get_endpoint_manager",
    "get_llm_config",
    "create_llm",
    "create_llm_for_endpoint",
    "AllEndpointsCoolingDown",
    "EndpointConfig",
    "ConfiguredLLMHandle",
    "EndpointManager",
    "report_llm_failure",
    "report_llm_success",
]
