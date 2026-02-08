from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from backend.api.schemas import ChatRequest, ChartDataResponse


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

    @router.post("/chat/supervisor")
    async def chat_supervisor_endpoint(request: ChatRequest):
        try:
            runner = await deps.get_graph_runner()
            try:
                thread_id = deps.resolve_thread_id(request.session_id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            ui_context = deps.build_ui_context(request)

            output_mode = None
            strict_selection = None
            if getattr(request, "options", None):
                output_mode = request.options.output_mode
                strict_selection = request.options.strict_selection

            resolved_query = deps.resolve_query_reference(request.query, thread_id)

            state = await runner.ainvoke(
                thread_id=thread_id,
                query=resolved_query,
                ui_context=ui_context,
                output_mode=output_mode,
                strict_selection=strict_selection,
            )
            markdown = ((state.get("artifacts") or {}).get("draft_markdown")) or ""

            report = None
            try:
                from backend.graph.report_builder import build_report_payload

                report = build_report_payload(state=state, query=resolved_query, thread_id=thread_id)
            except Exception:
                report = None

            deps.schedule_report_index(session_id=thread_id, report=report, state=state)

            deps.update_session_context(
                thread_id=thread_id,
                original_query=request.query,
                response_markdown=markdown,
                subject=state.get("subject"),
            )

            return {
                "success": True,
                "schema_version": deps.chat_response_schema_version,
                "contracts": deps.contract_info(),
                "response": markdown,
                "report": report,
                "intent": "chat",
                "classification": {"method": "langgraph", "confidence": 1.0},
                "session_id": thread_id,
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
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/chat/supervisor/stream")
    async def chat_supervisor_stream_endpoint(request: ChatRequest):
        import asyncio as _asyncio
        import json as _json

        from backend.graph.event_bus import reset_event_emitter, set_event_emitter

        runner = await deps.get_graph_runner()
        try:
            thread_id = deps.resolve_thread_id(request.session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        trace_raw_enabled = deps.resolve_trace_raw_enabled(request)
        ui_context = deps.build_ui_context(request)

        output_mode = None
        strict_selection = None
        if getattr(request, "options", None):
            output_mode = request.options.output_mode
            strict_selection = request.options.strict_selection

        resolved_query = deps.resolve_query_reference(request.query, thread_id)

        queue: "_asyncio.Queue[object]" = _asyncio.Queue()
        _END = object()

        async def _emit(payload: dict) -> None:
            if (not trace_raw_enabled) and deps.is_raw_trace_event(payload):
                return

            outgoing = deps.redact_sensitive_payload(dict(payload))
            original_schema = outgoing.get("schema_version")
            if (
                isinstance(original_schema, str)
                and original_schema
                and original_schema != deps.sse_event_schema_version
            ):
                outgoing["trace_schema_version"] = original_schema
            outgoing["schema_version"] = deps.sse_event_schema_version
            await queue.put(outgoing)

        async def _producer() -> None:
            token = set_event_emitter(_emit)
            try:
                await queue.put(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "thinking",
                        "stage": "langgraph_start",
                        "message": "LangGraph",
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )

                state = await runner.ainvoke(
                    thread_id=thread_id,
                    query=resolved_query,
                    ui_context=ui_context,
                    output_mode=output_mode,
                    strict_selection=strict_selection,
                )
                markdown = ((state.get("artifacts") or {}).get("draft_markdown")) or ""

                report = None
                try:
                    from backend.graph.report_builder import build_report_payload

                    report = build_report_payload(state=state, query=resolved_query, thread_id=thread_id)
                except Exception:
                    report = None

                deps.schedule_report_index(session_id=thread_id, report=report, state=state)

                deps.update_session_context(
                    thread_id=thread_id,
                    original_query=request.query,
                    response_markdown=markdown,
                    subject=state.get("subject"),
                )

                chunk_size = 60
                for idx in range(0, len(markdown), chunk_size):
                    chunk = markdown[idx : idx + chunk_size]
                    if chunk:
                        await queue.put(
                            {
                                "schema_version": deps.sse_event_schema_version,
                                "type": "token",
                                "content": chunk,
                            }
                        )
                    await _asyncio.sleep(0)

                await queue.put(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "done",
                        "contracts": deps.contract_info(),
                        "intent": "chat",
                        "session_id": thread_id,
                        "response": markdown,
                        "report": report,
                        "graph": {
                            "subject": state.get("subject"),
                            "output_mode": state.get("output_mode"),
                            "trace": state.get("trace"),
                        },
                    }
                )
            except Exception as exc:
                await queue.put(
                    deps.redact_sensitive_payload(
                        {
                            "schema_version": deps.sse_event_schema_version,
                            "type": "error",
                            "message": str(exc),
                        }
                    )
                )
            finally:
                reset_event_emitter(token)
                await queue.put(_END)

        producer_task = _asyncio.create_task(_producer())

        def _serialize_sse_item(item: object) -> str:
            def _fallback(value: object):
                if isinstance(value, (datetime, date, dt_time)):
                    return value.isoformat()
                return str(value)

            return _json.dumps(jsonable_encoder(item), ensure_ascii=False, default=_fallback)

        async def _stream():
            try:
                while True:
                    try:
                        item = await _asyncio.wait_for(queue.get(), timeout=5)
                    except _asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue

                    if item is _END:
                        break
                    yield f"data: {_serialize_sse_item(item)}\n\n"
            finally:
                if not producer_task.done():
                    producer_task.cancel()
                    try:
                        await producer_task
                    except Exception:
                        pass

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

