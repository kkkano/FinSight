from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict
import os

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import Response


@dataclass(frozen=True)
class SystemRouterDeps:
    metrics_enabled: bool
    metrics_payload: Callable[[], tuple[str, str]]
    graph_runner_ready: Callable[[], bool]
    get_graph_checkpointer_info: Callable[[], Dict[str, Any]]
    get_orchestrator_safe: Callable[[], Any]
    get_planner_ab_metrics: Callable[[], Dict[str, Any]]
    get_rag_observability_store: Callable[[], Any]
    require_rag_read_access: Callable[[Request], Dict[str, Any]]
    require_rag_mutation_access: Callable[[Request], Dict[str, Any]]
    memory_service: Any
    logger: Any


def create_system_router(deps: SystemRouterDeps) -> APIRouter:
    router = APIRouter(tags=["System"])

    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _rag_store() -> Any:
        return deps.get_rag_observability_store()

    def _require_rag_read_access(request: Request) -> Dict[str, Any]:
        return deps.require_rag_read_access(request)

    def _require_rag_mutation_access(request: Request) -> Dict[str, Any]:
        return deps.require_rag_mutation_access(request)

    @router.get("/")
    def read_root():
        return {"status": "healthy", "message": "FinSight API is running", "timestamp": _now()}

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
            components["cache"] = {"status": "ok" if hasattr(orchestrator, "cache") and orchestrator.cache is not None else "unavailable"}
            components["tools_module"] = {"status": "ok" if hasattr(orchestrator, "tools_module") and orchestrator.tools_module is not None else "unavailable"}
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
            rag_component: Dict[str, Any] = {"status": "ok", "backend": rag_service.backend_name, "embedding_model": getattr(rag_service, "embedding_model", "unknown"), "vector_dim": int(getattr(rag_service, "vector_dim", 0) or 0), "doc_count": int(rag_service.count_documents())}
            if getattr(rag_service, "fallback_reason", None):
                rag_component["fallback_reason"] = str(rag_service.fallback_reason)
            expected_backend = str(os.getenv("RAG_V2_BACKEND", "auto")).strip().lower()
            if expected_backend == "postgres" and rag_service.backend_name != "postgres":
                rag_component["status"] = "degraded"
                status = "degraded"
            try:
                rag_obs = _rag_store().health_summary(recent_limit=3, fallback_limit=3)
                rag_component["recent_runs"] = rag_obs.get("recent_runs") or []
                rag_component["fallback_summary"] = rag_obs.get("fallback_summary") or []
                components["rag_observability"] = {"status": rag_obs.get("status") or ("ok" if rag_obs.get("enabled") else "disabled"), **rag_obs}
            except Exception as exc:
                components["rag_observability"] = {"status": "error", "error": str(exc)}
            components["rag"] = rag_component
        except Exception as exc:
            status = "degraded"
            components["rag"] = {"status": "error", "error": str(exc)}

        return {"status": status, "components": components, "timestamp": _now()}

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
            return {"status": "ok", "data": orchestrator.get_stats(), "timestamp": _now()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"orchestrator diagnostics failed: {exc}") from exc

    @router.get("/diagnostics/planner-ab")
    @router.get("/diagnostics/planner_ab")
    def diagnostics_planner_ab():
        try:
            return {"status": "ok", "data": deps.get_planner_ab_metrics(), "timestamp": _now()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"planner-ab diagnostics failed: {exc}") from exc

    @router.get("/diagnostics/rag/status")
    def diagnostics_rag_status(request: Request):
        _require_rag_read_access(request)
        from backend.rag.hybrid_service import get_rag_service

        rag_service = get_rag_service()
        observability = _rag_store().health_summary(recent_limit=5, fallback_limit=5)
        payload = {
            "backend_requested": str(os.getenv("RAG_V2_BACKEND", "auto") or "auto").strip().lower() or "auto",
            "backend_actual": str(getattr(rag_service, "backend_name", "unknown") or "unknown"),
            "doc_count": int(rag_service.count_documents()),
            "vector_dim": int(getattr(rag_service, "vector_dim", 0) or 0),
            "embedding_model": str(getattr(rag_service, "embedding_model", "unknown") or "unknown"),
            "fallback_reason": str(getattr(rag_service, "fallback_reason", "") or "") or None,
            "enabled": bool(observability.get("enabled")),
            "backend": str(observability.get("backend") or observability.get("status") or "unknown"),
            "recent_run_count_24h": int(observability.get("recent_run_count_24h") or 0),
            "recent_fallback_count_24h": int(observability.get("recent_fallback_count_24h") or 0),
            "recent_empty_hits_rate_24h": observability.get("recent_empty_hits_rate_24h"),
            "last_run_at": observability.get("last_run_at"),
            "last_fallback_at": observability.get("last_fallback_at"),
            "observability": observability,
        }
        return {"status": "ok", "data": payload, "timestamp": _now()}

    @router.get("/diagnostics/rag/runs")
    def diagnostics_rag_runs(request: Request, limit: int = Query(default=20, ge=1, le=200), cursor: str | None = None, q: str | None = None, fallback_only: bool = False):
        _require_rag_read_access(request)
        return {"status": "ok", "data": _rag_store().list_runs(limit=limit, cursor=cursor, q=q, fallback_only=fallback_only), "timestamp": _now()}

    @router.get("/diagnostics/rag/runs/{run_id}")
    def diagnostics_rag_run_detail(run_id: str, request: Request):
        _require_rag_read_access(request)
        item = _rag_store().get_run_detail(run_id)
        if not item:
            raise HTTPException(status_code=404, detail="run not found")
        return {"status": "ok", "data": item, "timestamp": _now()}

    @router.get("/diagnostics/rag/runs/{run_id}/events")
    def diagnostics_rag_run_events(run_id: str, request: Request, limit: int = Query(default=500, ge=1, le=2000)):
        _require_rag_read_access(request)
        return {"status": "ok", "data": _rag_store().list_events(run_id=run_id, limit=limit), "timestamp": _now()}

    @router.get("/diagnostics/rag/documents")
    def diagnostics_rag_documents(request: Request, run_id: str | None = None, collection: str | None = None, include_deleted: bool = False, limit: int = Query(default=200, ge=1, le=1000)):
        _require_rag_read_access(request)
        return {"status": "ok", "data": _rag_store().list_documents(run_id=run_id, collection=collection, include_deleted=include_deleted, limit=limit), "timestamp": _now()}

    @router.get("/diagnostics/rag/chunks")
    def diagnostics_rag_chunks(request: Request, run_id: str | None = None, collection: str | None = None, source_doc_id: str | None = None, include_deleted: bool = False, limit: int = Query(default=500, ge=1, le=2000)):
        _require_rag_read_access(request)
        return {"status": "ok", "data": _rag_store().list_chunks(run_id=run_id, collection=collection, source_doc_id=source_doc_id, include_deleted=include_deleted, limit=limit), "timestamp": _now()}

    @router.get("/diagnostics/rag/hits")
    def diagnostics_rag_hits(request: Request, run_id: str | None = None, collection: str | None = None, include_deleted: bool = False, limit: int = Query(default=500, ge=1, le=2000)):
        _require_rag_read_access(request)
        return {"status": "ok", "data": _rag_store().list_hits(run_id=run_id, collection=collection, include_deleted=include_deleted, limit=limit), "timestamp": _now()}

    @router.get("/diagnostics/rag/collections")
    def diagnostics_rag_collections(request: Request, limit: int = Query(default=200, ge=1, le=1000)):
        _require_rag_read_access(request)
        return {"status": "ok", "data": _rag_store().list_collections(limit=limit), "timestamp": _now()}

    @router.get("/diagnostics/rag/collections/{collection}/documents")
    def diagnostics_rag_collection_documents(collection: str, request: Request, include_deleted: bool = False, limit: int = Query(default=200, ge=1, le=1000)):
        _require_rag_read_access(request)
        return {"status": "ok", "data": _rag_store().list_documents(collection=collection, include_deleted=include_deleted, limit=limit), "timestamp": _now()}

    @router.get("/diagnostics/rag/collections/{collection}/chunks")
    def diagnostics_rag_collection_chunks(collection: str, request: Request, include_deleted: bool = False, limit: int = Query(default=500, ge=1, le=2000)):
        _require_rag_read_access(request)
        return {"status": "ok", "data": _rag_store().list_chunks(collection=collection, include_deleted=include_deleted, limit=limit), "timestamp": _now()}

    @router.get("/diagnostics/rag/db-browser/{table_name}")
    def diagnostics_rag_db_browser(table_name: str, request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0, le=100000), q: str | None = None, collection: str | None = None, run_id: str | None = None, source_doc_id: str | None = None):
        _require_rag_read_access(request)
        try:
            payload = _rag_store().browse_db_table(table_name=table_name, limit=limit, offset=offset, q=q, collection=collection, run_id=run_id, source_doc_id=source_doc_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"status": "ok", "data": payload, "timestamp": _now()}

    @router.post("/diagnostics/rag/search-preview")
    def diagnostics_rag_search_preview(request: Request, payload: Dict[str, Any] = Body(default_factory=dict)):
        _require_rag_read_access(request)
        try:
            return {"status": "ok", "data": _rag_store().search_preview(query=str(payload.get('query') or ''), collection=str(payload.get('collection') or ''), top_k=int(payload.get('top_k') or 10)), "timestamp": _now()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/diagnostics/rag/runs/{run_id}/soft-delete")
    def diagnostics_rag_soft_delete_run(run_id: str, request: Request, payload: Dict[str, Any] = Body(default_factory=dict)):
        _require_rag_mutation_access(request)
        item = _rag_store().soft_delete_run(run_id, deleted_by=str(payload.get('deleted_by') or 'system'), reason=str(payload.get('reason') or '') or None)
        if not item:
            raise HTTPException(status_code=404, detail='run not found')
        return {'status': 'ok', 'data': item, 'timestamp': _now()}

    @router.post("/diagnostics/rag/documents/{source_doc_id}/soft-delete")
    def diagnostics_rag_soft_delete_source_doc(source_doc_id: str, request: Request, payload: Dict[str, Any] = Body(default_factory=dict)):
        _require_rag_mutation_access(request)
        item = _rag_store().soft_delete_source_doc(source_doc_id, deleted_by=str(payload.get('deleted_by') or 'system'), reason=str(payload.get('reason') or '') or None)
        if not item:
            raise HTTPException(status_code=404, detail='source document not found')
        return {'status': 'ok', 'data': item, 'timestamp': _now()}

    return router
