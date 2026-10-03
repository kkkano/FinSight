"""内部服务凭据的统一验证；不依赖 API 装配或用户模型配置。"""
from backend.config.settings import security_settings


def configured_api_keys() -> set[str]:
    settings = security_settings()
    raw = settings.api_auth_keys or settings.api_auth_key
    return {value.strip() for value in raw.split(",") if value.strip()}


def request_api_key(request) -> str | None:
    direct = request.headers.get("x-api-key")
    if direct:
        return direct.strip()
    bearer = request.headers.get("authorization", "")
    return bearer.split(" ", 1)[1].strip() if bearer.lower().startswith("bearer ") else None


def is_internal_api_key_authorized(request) -> bool:
    key = request_api_key(request)
    return bool(key and key in configured_api_keys())
