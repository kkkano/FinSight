"""核心产品依赖的只读 readiness 检查。"""
from __future__ import annotations

import os
from typing import Any

from backend.config.settings import security_settings
from backend.security.supabase_auth import AuthConfigurationError, ensure_auth_verifier_ready
from backend.services.database import is_production_mode, schema_revision_status
from backend.services.market_data_gateway import get_market_data_gateway
from backend.utils.env import env_bool


def _prediction_enabled() -> bool:
    return env_bool("PREDICTION_GENERATION_ENABLED", True)


def authentication_health() -> dict[str, str]:
    settings = security_settings()
    auth_required = bool(settings.supabase_auth_required)
    if (is_production_mode() or _prediction_enabled()) and not auth_required:
        return {"status": "error", "error_code": "strong_auth_required"}

    if not auth_required:
        return {"status": "disabled"}

    jwt_secret = str(os.getenv("SUPABASE_JWT_SECRET") or "").strip()
    supabase_url = str(settings.supabase_url or "").strip()
    if not jwt_secret and not supabase_url:
        return {"status": "error", "error_code": "auth_verifier_unconfigured"}
    try:
        ensure_auth_verifier_ready()
    except AuthConfigurationError:
        return {"status": "error", "error_code": "auth_verifier_unavailable"}
    return {"status": "ok"}


def database_health() -> dict[str, str]:
    required = is_production_mode() or _prediction_enabled()
    try:
        revision = schema_revision_status()
    except Exception:
        return {"status": "error", "error_code": "database_schema_unavailable"}

    if not revision.configured:
        if required:
            return {"status": "error", "error_code": "database_unconfigured"}
        return {"status": "disabled"}
    if not revision.is_current:
        return {"status": "error", "error_code": "database_schema_outdated"}
    return {"status": "ok"}


def market_data_health() -> dict[str, str]:
    try:
        gateway = get_market_data_gateway()
        readiness: dict[str, Any] = gateway.trusted_provider_readiness(("kline", "quote"))
    except Exception:
        return {"status": "error", "error_code": "market_gateway_unavailable"}

    if not all(bool(readiness.get(capability)) for capability in ("kline", "quote")):
        return {"status": "error", "error_code": "trusted_market_provider_unconfigured"}
    return {"status": "ok"}


__all__ = ["authentication_health", "database_health", "market_data_health"]
