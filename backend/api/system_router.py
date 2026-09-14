from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response


@dataclass(frozen=True)
class SystemRouterDeps:
    metrics_enabled: bool
    metrics_payload: Callable[[], tuple[str, str]]
    graph_runner_ready: Callable[[], bool]
    get_graph_checkpointer_info: Callable[[], dict[str, Any]]
    get_startup_result: Callable[[], Any]
    get_authentication_health: Callable[[], dict[str, str]]
    get_database_health: Callable[[], dict[str, str]]
    get_market_data_health: Callable[[], dict[str, str]]
    # Optional so small isolated routers/tests can keep using the original
    # dependency contract. The production app injects the RAG probe.
    get_rag_health: Callable[[], dict[str, Any]] | None = None


def _read_component(check: Callable[[], dict[str, str]], *, failure_code: str) -> dict[str, str]:
    try:
        raw = check()
    except Exception:
        return {"status": "error", "error_code": failure_code}
    if not isinstance(raw, dict):
        return {"status": "error", "error_code": failure_code}
    component_status = str(raw.get("status") or "error")
    if component_status not in {"ok", "disabled", "initializing", "degraded", "error"}:
        return {"status": "error", "error_code": failure_code}
    result = {"status": component_status}
    error_code = str(raw.get("error_code") or "").strip()
    if error_code and component_status not in {"ok", "disabled"}:
        result["error_code"] = error_code
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _runtime_profile() -> str:
    """Return a stable, non-secret profile label for readiness diagnostics."""
    configured = (
        str(os.getenv("FINSIGHT_RUNTIME_PROFILE") or "").strip().lower(),
        str(os.getenv("APP_MODE") or "").strip().lower(),
    )
    if any(value in {"prod", "production"} for value in configured):
        return "production"
    raw = configured[0] or configured[1] or "development"
    if raw in {"prod", "production"}:
        return "production"
    if raw in {"test", "testing", "ci"} or _env_truthy("FINSIGHT_TEST_PROFILE"):
        return "test"
    # A deterministic graph is useful without an LLM in local/stub runs. Do
    # not apply this shortcut to production, even if someone sets stub flags.
    synth_mode = str(os.getenv("LANGGRAPH_SYNTHESIZE_MODE") or "").strip().lower()
    if synth_mode in {"stub", "dry_run", "off"} and not _env_truthy("LANGGRAPH_EXECUTE_LIVE_TOOLS"):
        return "stub"
    return raw or "development"


def _is_production_profile() -> bool:
    return _runtime_profile() == "production"


def _component_ready(
    component: dict[str, Any],
    *,
    required: bool,
    allow_degraded: bool,
    default_error_code: str,
) -> tuple[bool, dict[str, Any]]:
    """Normalize a readiness component and return (is_ready, payload)."""
    status = str(component.get("status") or "error").strip().lower()
    if status not in {"ok", "disabled", "initializing", "degraded", "error"}:
        status = "error"
    normalized: dict[str, Any] = {"status": status}
    for key in ("error_code", "reason", "backend", "backend_requested", "embedding", "reranker"):
        value = component.get(key)
        if value not in (None, ""):
            if key == "reason":
                # Reasons originate in database/model exceptions. Never echo
                # URLs, DSNs, credentials, or stack-like text from a public
                # infrastructure probe.
                reason = str(value)
                lowered = reason.lower()
                if (
                    "://" in reason
                    or "password" in lowered
                    or "secret" in lowered
                    or "token" in lowered
                    or "api_key" in lowered
                    or "apikey" in lowered
                ):
                    normalized[key] = "dependency degraded"
                else:
                    normalized[key] = re.sub(r"\s+", " ", reason)[:160]
            else:
                normalized[key] = value
    if status == "ok":
        return True, normalized
    if status == "disabled" and not required:
        return True, normalized
    if status == "degraded" and allow_degraded and not required:
        return True, normalized
    if not required and _runtime_profile() in {"test", "stub"}:
        # Deterministic CI/stub profiles intentionally omit external services.
        # Keep their diagnostics visible while allowing the probe to be used as
        # a process/readiness signal for local test orchestration.
        return True, normalized
    normalized.setdefault("error_code", default_error_code)
    return False, normalized


def _safe_rag_health(deps: SystemRouterDeps) -> dict[str, Any]:
    if deps.get_rag_health is None:
        # Keep hand-built test routers usable while making production failure
        # explicit. The application factory always injects a real probe.
        if _is_production_profile():
            return {"status": "error", "error_code": "rag_probe_unconfigured"}
        return {"status": "disabled", "reason": "rag_probe_unconfigured"}
    try:
        value = deps.get_rag_health()
    except Exception:
        return {"status": "error", "error_code": "rag_health_failed"}
    if not isinstance(value, dict):
        return {"status": "error", "error_code": "rag_health_invalid"}
    return value


def _readiness_components(deps: SystemRouterDeps) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Collect the minimal dependencies needed to serve a real request."""
    production = _is_production_profile()
    profile = _runtime_profile()
    allow_degraded = not production
    components: dict[str, dict[str, Any]] = {}
    failures: list[str] = []

    checks = (
        ("authentication", deps.get_authentication_health, "authentication_health_failed", production),
        ("database", deps.get_database_health, "database_health_failed", production),
        ("market_data", deps.get_market_data_health, "market_data_health_failed", production),
    )
    for name, check, error_code, required in checks:
        component = _read_component(check, failure_code=error_code)
        ready, normalized = _component_ready(
            component,
            required=required,
            allow_degraded=allow_degraded,
            default_error_code=error_code,
        )
        components[name] = normalized
        if not ready:
            failures.append(name)

    try:
        runner_ready = bool(deps.graph_runner_ready())
        component = {"status": "ok" if runner_ready else "initializing"}
    except Exception:
        runner_ready = False
        component = {"status": "error", "error_code": "graph_unavailable"}
    components["langgraph_runner"] = component
    if not runner_ready:
        failures.append("langgraph_runner")

    try:
        raw_info = deps.get_graph_checkpointer_info() or {}
        checkpointer = dict(raw_info)
        backend = str(checkpointer.get("backend") or "unknown").strip().lower()
        persistent = bool(checkpointer.get("persistent"))
        fallback_used = bool(checkpointer.get("fallback_used"))
        fallback_reason = str(checkpointer.get("fallback_reason") or "").strip()
        if backend == "unknown":
            component = {"status": "initializing"}
        elif production and backend != "postgres":
            component = {"status": "error", "error_code": "checkpointer_not_postgres", "backend": backend}
        elif production and not persistent:
            component = {"status": "error", "error_code": "checkpointer_not_persistent", "backend": backend}
        elif production and (fallback_used or fallback_reason):
            component = {"status": "error", "error_code": "checkpointer_memory_fallback", "backend": backend}
        elif fallback_used or fallback_reason:
            component = {
                "status": "degraded",
                "reason": fallback_reason or "checkpointer_fallback",
                "backend": backend,
            }
        else:
            component = {"status": "ok", "backend": backend, "persistent": persistent}
    except Exception:
        component = {"status": "error", "error_code": "checkpointer_health_failed"}
    components["checkpointer"] = component
    allowed_statuses = {"ok", "disabled"}
    if allow_degraded:
        allowed_statuses.add("degraded")
    if component["status"] not in allowed_statuses:
        failures.append("checkpointer")

    startup = deps.get_startup_result()
    llm_required = production
    if not production and startup is not None and hasattr(startup, "llm_required"):
        llm_required = bool(getattr(startup, "llm_required"))
    if startup is None:
        initial_status = "disabled" if profile in {"test", "stub"} and not llm_required else "initializing"
        llm_component: dict[str, Any] = {"status": initial_status, "required": llm_required}
    elif bool(getattr(startup, "llm_available", False)):
        llm_component = {"status": "ok", "required": llm_required}
    elif llm_required:
        llm_component = {"status": "error", "error_code": "llm_unavailable", "required": True}
    else:
        llm_component = {
            "status": "disabled",
            "reason": "llm_optional_for_stub_profile",
            "required": False,
        }
    components["llm"] = llm_component
    if llm_component["status"] not in {"ok", "disabled"}:
        failures.append("llm")

    rag_raw = _safe_rag_health(deps)
    rag_required = production
    rag_ready, rag_component = _component_ready(
        rag_raw,
        required=rag_required,
        allow_degraded=allow_degraded,
        default_error_code="rag_unavailable",
    )
    rag_component["required"] = rag_required
    components["rag"] = rag_component
    if not rag_ready:
        failures.append("rag")

    # Profile is intentionally included in the component map for operators,
    # while the top-level field remains easy for probes to parse.
    components["runtime"] = {"status": "ok", "profile": profile, "production": production}
    return components, failures


def create_system_router(deps: SystemRouterDeps) -> APIRouter:
    """运行健康与 Prometheus 指标；交互式运维诊断不属于公共 API。"""
    router = APIRouter(tags=["System"])

    @router.get("/livez")
    def liveness_check():
        """Process liveness probe; never touches external dependencies."""
        return {"status": "alive", "live": True, "timestamp": _now()}

    @router.get("/readyz")
    def readiness_check():
        """Dependency readiness probe used by orchestrators and Docker."""
        components, failures = _readiness_components(deps)
        ready = not failures
        payload = {
            "status": "ready" if ready else "not_ready",
            "ready": ready,
            "failed_components": failures,
            "components": components,
            "profile": _runtime_profile(),
            "timestamp": _now(),
        }
        if not ready:
            return JSONResponse(status_code=503, content=payload)
        return payload

    @router.get("/health")
    def health_check():
        status = "healthy"
        components: dict[str, dict[str, Any]] = {}

        readiness_checks = (
            ("authentication", deps.get_authentication_health, "authentication_health_failed"),
            ("database", deps.get_database_health, "database_health_failed"),
            ("market_data", deps.get_market_data_health, "market_data_health_failed"),
        )
        for name, check, failure_code in readiness_checks:
            component = _read_component(check, failure_code=failure_code)
            components[name] = component
            if component["status"] not in {"ok", "disabled"}:
                status = "degraded"

        try:
            runner_ready = bool(deps.graph_runner_ready())
            components["langgraph_runner"] = {"status": "ok" if runner_ready else "initializing"}
            if not runner_ready:
                status = "degraded"
        except Exception:
            components["langgraph_runner"] = {"status": "error", "error_code": "graph_unavailable"}
            status = "degraded"

        try:
            checkpointer = deps.get_graph_checkpointer_info()
            backend = str(checkpointer.get("backend") or "unknown")
            components["checkpointer"] = {
                "status": "ok" if backend != "unknown" else "initializing",
            }
            if backend == "unknown":
                status = "degraded"
        except Exception:
            components["checkpointer"] = {"status": "error", "error_code": "store_unavailable"}
            status = "degraded"

        startup = deps.get_startup_result()
        if startup is None:
            components["llm"] = {"status": "initializing"}
            status = "degraded"
        elif bool(getattr(startup, "llm_available", False)):
            components["llm"] = {"status": "ok"}
        else:
            components["llm"] = {"status": "error", "error_code": "llm_unavailable"}
            status = "degraded"

        payload = {
            "status": status,
            "components": components,
            "timestamp": _now(),
        }
        if status != "healthy":
            return JSONResponse(status_code=503, content=payload)
        return payload

    @router.get("/metrics")
    def metrics_endpoint():
        if not deps.metrics_enabled:
            raise HTTPException(status_code=404, detail="metrics disabled")
        payload, content_type = deps.metrics_payload()
        return Response(content=payload, media_type=content_type)

    return router
