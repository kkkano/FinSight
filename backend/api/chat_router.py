from __future__ import annotations

import asyncio
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


def _session_history_for_context(manager: Any, *, limit: int = 6) -> list[dict[str, str]]:
    """Return compact same-session turns for graph-level contextual routing."""
    try:
        turns = manager.get_last_n_turns(limit)
    except Exception:
        return []
    history: list[dict[str, str]] = []
    for turn in turns or []:
        query = str(getattr(turn, "query", "") or "").strip()
        response = str(getattr(turn, "response", "") or "").strip()
        metadata = getattr(turn, "metadata", None)
        if query:
            row: dict[str, str] = {"role": "user", "content": query[:600]}
            if isinstance(metadata, dict) and metadata.get("tickers"):
                row["tickers"] = ", ".join(str(t).upper() for t in metadata.get("tickers") or [])[:120]
            history.append(row)
        if response:
            history.append({"role": "assistant", "content": " ".join(response.split())[:900]})
    return history[-(limit * 2):]


def _attach_session_history(ui_context: dict[str, Any], manager: Any) -> dict[str, Any]:
    history = _session_history_for_context(manager)
    if not history:
        return ui_context
    enriched = dict(ui_context or {})
    enriched["session_history"] = history
    return enriched


def _ensure_deliverable_markdown(state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    markdown = str(artifacts.get("draft_markdown") or "")
    if markdown.strip():
        return markdown, state
    try:
        from backend.graph.nodes.render_stub import render_stub

        rendered = render_stub(state)
        rendered_artifacts = rendered.get("artifacts") if isinstance(rendered, dict) else None
        if isinstance(rendered_artifacts, dict):
            state = {**state, "artifacts": rendered_artifacts}
            markdown = str(rendered_artifacts.get("draft_markdown") or "")
            if markdown.strip():
                return markdown, state
    except Exception as exc:
        logging.getLogger("chat_router").warning("[chat/supervisor] final render fallback failed: %s", exc)
    query = str(state.get("query") or "这个问题").strip()
    markdown = f"这轮没有合成出可用文字，但我已经保留了上下文。你可以直接重试：{query}\n"
    state = {**state, "artifacts": {**artifacts, "draft_markdown": markdown}}
    return markdown, state


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
            ui_context = _attach_session_history(ui_context, deps.get_session_context(thread_id))

            output_mode = None
            strict_selection = None
            confirmation_mode = None
            if getattr(request, "options", None):
                output_mode = request.options.output_mode
                strict_selection = request.options.strict_selection
                confirmation_mode = parse_confirmation_mode(request.options.confirmation_mode)
                if isinstance(request.options.agent_preferences, dict):
                    ui_context["agent_preferences"] = request.options.agent_preferences

            # Chat entry point defaults to skip — Chat UI has no InterruptCard.
            # Exception: investment_report mode always requires confirmation (auto).
            if confirmation_mode is None:
                if str(output_mode or "").strip().lower() == "investment_report":
                    confirmation_mode = "auto"
                else:
                    confirmation_mode = "skip"

            # Keep the original user turn intact for LangGraph. Context binding
            # now happens inside conversation_router using thread messages,
            # UI anchors, report context, and portfolio context. Pre-rewriting
            # "it/that/second point" here caused cross-session focus leakage
            # because the legacy ContextManager is user-memory scoped.
            resolved_query = request.query

            from backend.graph.runner import run_graph_traced
            from backend.services.execution_service import _execution_timeout_seconds

            timeout_seconds = _execution_timeout_seconds(output_mode, ui_context=ui_context)
            try:
                state = await asyncio.wait_for(
                    run_graph_traced(
                        runner,
                        thread_id=thread_id,
                        query=resolved_query,
                        ui_context=ui_context,
                        output_mode=output_mode,
                        strict_selection=strict_selection,
                        confirmation_mode=confirmation_mode,
                    ),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                _logger.error(
                    "[chat/supervisor] graph timeout thread_id=%s timeout=%ss query=%s",
                    thread_id,
                    timeout_seconds,
                    (resolved_query or "")[:120],
                )
                raise HTTPException(
                    status_code=504,
                    detail=f"Execution timed out after {int(timeout_seconds)}s; increase the timeout preference or reduce the request scope.",
                ) from exc
            markdown, state = _ensure_deliverable_markdown(state)

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

            if not quality_blocked:
                try:
                    from backend.graph.store import persist_memory_snapshot

                    persist_memory_snapshot(
                        thread_id=thread_id,
                        state=state,
                        report=report,
                    )
                except Exception as exc:
                    _logger.warning("[chat/supervisor] persist memory snapshot failed: %s", exc)

            if not str(markdown or "").strip():
                query_preview = str(resolved_query or "这个问题").strip()
                markdown = f"这轮没有合成出可用文字，但我已经保留了上下文。你可以直接重试：{query_preview}\n"

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
        ui_context = _attach_session_history(ui_context, deps.get_session_context(thread_id))

        output_mode = None
        strict_selection = None
        confirmation_mode = None
        if getattr(request, "options", None):
            output_mode = request.options.output_mode
            strict_selection = request.options.strict_selection
            confirmation_mode = parse_confirmation_mode(request.options.confirmation_mode)
            if isinstance(request.options.agent_preferences, dict):
                ui_context["agent_preferences"] = request.options.agent_preferences

        # Chat entry point defaults to skip — Chat UI has no InterruptCard.
        # Exception: investment_report mode always requires confirmation (auto).
        if confirmation_mode is None:
            if str(output_mode or "").strip().lower() == "investment_report":
                confirmation_mode = "auto"
            else:
                confirmation_mode = "skip"

        # Keep the original user turn intact; see sync endpoint note above.
        resolved_query = request.query

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
                    yield f"data: {_serialize_sse_item(event)}\n\n"
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
