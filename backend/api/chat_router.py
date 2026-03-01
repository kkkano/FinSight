from __future__ import annotations

import logging
import traceback
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from backend.api.schemas import ChatRequest, ChartDataResponse
from backend.graph.confirmation_policy import parse_confirmation_mode
from backend.report.quality_engine import apply_quality_to_report, record_quality_metrics


@dataclass(frozen=True)
class ChatRouterDeps:
    get_graph_runner: Callable[[], Awaitable[Any]]
    resolve_thread_id: Callable[[Optional[str]], str]
    build_ui_context: Callable[[ChatRequest], dict[str, Any]]
    resolve_query_reference: Callable[[str, str], str]
    schedule_report_index: Callable[..., None]
    update_session_context: Callable[..., None]
    contract_info: Callable[[], dict[str, str]]
    resolve_trace_raw_enabled: Callable[[ChatRequest], bool]
    is_raw_trace_event: Callable[[dict[str, Any]], bool]
    redact_sensitive_payload: Callable[[Any], Any]
    get_session_context: Callable[[str], Any]
    chat_response_schema_version: str
    sse_event_schema_version: str


def create_chat_router(deps: ChatRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Chat"])
    _logger = logging.getLogger("chat_router")

    @router.post("/chat/supervisor")
    async def chat_supervisor_endpoint(request: ChatRequest):
        _t0 = _time.perf_counter()
        try:
            runner = await deps.get_graph_runner()
            try:
                thread_id = deps.resolve_thread_id(request.session_id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            ui_context = deps.build_ui_context(request)

            output_mode = None
            strict_selection = None
            confirmation_mode = None
            if getattr(request, "options", None):
                output_mode = request.options.output_mode
                strict_selection = request.options.strict_selection
                confirmation_mode = parse_confirmation_mode(request.options.confirmation_mode)

            resolved_query = deps.resolve_query_reference(request.query, thread_id)

            from backend.graph.runner import run_graph_traced
            state = await run_graph_traced(
                runner,
                thread_id=thread_id,
                query=resolved_query,
                ui_context=ui_context,
                output_mode=output_mode,
                strict_selection=strict_selection,
                confirmation_mode=confirmation_mode,
            )
            markdown = ((state.get("artifacts") or {}).get("draft_markdown")) or ""

            report = None
            try:
                from backend.graph.report_builder import build_report_payload

                report = build_report_payload(state=state, query=resolved_query, thread_id=thread_id)
            except Exception as _report_exc:
                _logger.warning("[chat/supervisor] report build failed: %s", _report_exc, exc_info=True)
                report = None

            report_quality, quality_blocked = apply_quality_to_report(report)
            record_quality_metrics(report_quality, source="chat_sync")

            if isinstance(report, dict) and not quality_blocked:
                deps.schedule_report_index(session_id=thread_id, report=report, state=state)

            deps.update_session_context(
                thread_id=thread_id,
                original_query=request.query,
                response_markdown=markdown,
                subject=state.get("subject"),
                skip_context=bool(state.get("skip_session_context")),
            )

            _elapsed_ms = int((_time.perf_counter() - _t0) * 1000)
            return {
                "success": True,
                "schema_version": deps.chat_response_schema_version,
                "contracts": deps.contract_info(),
                "response": markdown,
                "report": report,
                "quality": report_quality,
                "quality_blocked": quality_blocked,
                "publishable": not quality_blocked,
                "intent": "chat",
                "classification": {"method": "langgraph", "confidence": 1.0},
                "session_id": thread_id,
                "response_time_ms": _elapsed_ms,
                "graph": {
                    "subject": state.get("subject"),
                    "output_mode": state.get("output_mode"),
                    "trace": state.get("trace"),
                },
            }
        except HTTPException:
            raise
        except Exception as exc:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    @router.post("/chat/supervisor/stream")
    async def chat_supervisor_stream_endpoint(request: ChatRequest):
        import json as _json

        from backend.services.execution_service import ExecutionDeps, run_graph_pipeline

        try:
            thread_id = deps.resolve_thread_id(request.session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        trace_raw_enabled = deps.resolve_trace_raw_enabled(request)
        ui_context = deps.build_ui_context(request)

        output_mode = None
        strict_selection = None
        confirmation_mode = None
        if getattr(request, "options", None):
            output_mode = request.options.output_mode
            strict_selection = request.options.strict_selection
            confirmation_mode = parse_confirmation_mode(request.options.confirmation_mode)

        resolved_query = deps.resolve_query_reference(request.query, thread_id)

        exec_deps = ExecutionDeps(
            get_graph_runner=deps.get_graph_runner,
            schedule_report_index=deps.schedule_report_index,
            update_session_context=deps.update_session_context,
            redact_sensitive_payload=deps.redact_sensitive_payload,
            is_raw_trace_event=deps.is_raw_trace_event,
            contract_info=deps.contract_info,
            sse_event_schema_version=deps.sse_event_schema_version,
        )

        pipeline = run_graph_pipeline(
            deps=exec_deps,
            query=resolved_query,
            thread_id=thread_id,
            ui_context=ui_context,
            output_mode=output_mode,
            strict_selection=strict_selection,
            confirmation_mode=confirmation_mode,
            original_query=request.query,
            source="chat",
            trace_raw_enabled=trace_raw_enabled,
        )

        def _serialize_sse_item(item: object) -> str:
            def _fallback(value: object):
                if isinstance(value, (datetime, date, dt_time)):
                    return value.isoformat()
                return str(value)

            return _json.dumps(jsonable_encoder(item), ensure_ascii=False, default=_fallback)

        async def _stream():
            async for event in pipeline:
                if isinstance(event, dict) and event.get("type") == "keep-alive":
                    yield ": keep-alive\n\n"
                else:
                    yield f"data: {_serialize_sse_item(event)}\n\n"

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    @router.post("/api/chat/add-chart-data", response_model=ChartDataResponse)
    async def add_chart_data(request: dict):
        try:
            ticker = request.get("ticker")
            summary = request.get("summary", "")
            try:
                session_id = deps.resolve_thread_id(request.get("session_id"))
            except ValueError as exc:
                return {"success": False, "error": str(exc)}

            if not ticker or not summary:
                return {"success": False, "error": "Missing ticker or summary"}

            chart_message = f"[Chart Data] {summary}"
            deps.get_session_context(session_id).add_turn(
                query=f"View chart data for {ticker}",
                intent="chat",
                response=chart_message,
                metadata={"ticker": ticker, "tickers": [ticker], "chart_data": True},
            )

            return {"success": True, "message": "Chart data added to context", "session_id": session_id}
        except Exception as exc:
            traceback.print_exc()
            return {"success": False, "error": str(exc)}

    return router
