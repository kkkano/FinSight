from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response


@dataclass(frozen=True)
class SystemRouterDeps:
    metrics_enabled: bool
    metrics_payload: Callable[[], tuple[str, str]]
    graph_runner_ready: Callable[[], bool]
    get_graph_checkpointer_info: Callable[[], Dict[str, Any]]
    get_orchestrator_safe: Callable[[], Any]
    get_planner_ab_metrics: Callable[[], Dict[str, Any]]
    memory_service: Any
    logger: Any


def create_system_router(deps: SystemRouterDeps) -> APIRouter:
    router = APIRouter(tags=["System"])

    @router.get("/")
    def read_root():
        return {
            "status": "healthy",
            "message": "FinSight API is running",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    @router.get("/health")
    def health_check():
        status = "healthy"
        components: Dict[str, Dict[str, Any]] = {}

        components["langgraph_runner"] = {"status": "ok" if deps.graph_runner_ready() else "initializing"}
        checkpointer_info = deps.get_graph_checkpointer_info()
        checkpointer_status = "ok" if checkpointer_info.get("backend") != "unknown" else "initializing"
        components["checkpointer"] = {"status": checkpointer_status, **checkpointer_info}

        orchestrator = deps.get_orchestrator_safe()
        if orchestrator:
            components["orchestrator"] = {"status": "ok"}
            has_cache = hasattr(orchestrator, "cache") and orchestrator.cache is not None
            has_tools = hasattr(orchestrator, "tools_module") and orchestrator.tools_module is not None
            components["cache"] = {"status": "ok" if has_cache else "unavailable"}
            components["tools_module"] = {"status": "ok" if has_tools else "unavailable"}
        else:
            status = "degraded"
            components["orchestrator"] = {"status": "error", "available": False}
            components["cache"] = {"status": "unavailable"}
            components["tools_module"] = {"status": "unavailable"}

        components["memory"] = {"status": "ok" if deps.memory_service else "unavailable"}

        live_tools = os.getenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false").lower() in ("true", "1", "yes", "on")
        components["live_tools"] = {"status": "active" if live_tools else "dry_run"}

        try:
            from backend.rag.hybrid_service import get_rag_service

            rag_service = get_rag_service()
            rag_component: Dict[str, Any] = {
                "status": "ok",
                "backend": rag_service.backend_name,
                "embedding_model": getattr(rag_service, "embedding_model", "unknown"),
                "vector_dim": int(getattr(rag_service, "vector_dim", 0) or 0),
                "doc_count": int(rag_service.count_documents()),
            }
            fallback_reason = getattr(rag_service, "fallback_reason", None)
            if fallback_reason:
                rag_component["fallback_reason"] = str(fallback_reason)

            expected_backend = str(os.getenv("RAG_V2_BACKEND", "auto")).strip().lower()
            if expected_backend == "postgres" and rag_service.backend_name != "postgres":
                rag_component["status"] = "degraded"
                status = "degraded"

            components["rag"] = rag_component
        except Exception as exc:
            status = "degraded"
            components["rag"] = {
                "status": "error",
                "error": str(exc),
            }

        return {
            "status": status,
            "components": components,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    @router.get("/metrics")
    def metrics_endpoint():
        if not deps.metrics_enabled:
            raise HTTPException(status_code=404, detail="metrics disabled")
        payload, content_type = deps.metrics_payload()
        return Response(content=payload, media_type=content_type)

    @router.get("/diagnostics/orchestrator")
    def diagnostics_orchestrator():
        orchestrator = deps.get_orchestrator_safe()
        if not orchestrator:
            raise HTTPException(status_code=500, detail="Orchestrator not initialized")

        try:
            stats = orchestrator.get_stats()
            return {
                "status": "ok",
                "data": stats,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"orchestrator diagnostics failed: {exc}") from exc

    @router.get("/diagnostics/planner-ab")
    @router.get("/diagnostics/planner_ab")
    def diagnostics_planner_ab():
        try:
            return {
                "status": "ok",
                "data": deps.get_planner_ab_metrics(),
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"planner-ab diagnostics failed: {exc}") from exc

    return router
