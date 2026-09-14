from __future__ import annotations

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


def create_system_router(deps: SystemRouterDeps) -> APIRouter:
    """运行健康与 Prometheus 指标；交互式运维诊断不属于公共 API。"""
    router = APIRouter(tags=["System"])

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
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
