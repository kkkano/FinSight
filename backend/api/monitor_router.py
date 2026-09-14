# -*- coding: utf-8 -*-
"""页面 lease 与当前标的实时点评 API。"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.services.monitor_comment_store import get_monitor_comment_store
from backend.services.monitor_lease_store import get_monitor_lease_store

monitor_router = APIRouter(tags=["Monitor"])

SESSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
SYMBOL_PATTERN = r"^[A-Za-z0-9^][A-Za-z0-9._:^=-]{0,31}$"
SessionQuery = Annotated[str, Query(min_length=1, max_length=256, pattern=SESSION_PATTERN)]
SymbolQuery = Annotated[str, Query(min_length=1, max_length=32, pattern=SYMBOL_PATTERN)]


class AcquireLeaseRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=256, pattern=SESSION_PATTERN)
    symbol: str = Field(..., min_length=1, max_length=32, pattern=SYMBOL_PATTERN)


class LeaseTokenRequest(BaseModel):
    lease_token: str = Field(..., min_length=20, max_length=256)


def _authenticated_user_id(request: Request) -> str:
    user_id = str(getattr(request.state, "user_id", "public") or "public").strip()
    if user_id == "public":
        raise HTTPException(status_code=401, detail="登录后才能启用页面实时监控")
    return user_id


@monitor_router.post("/api/monitor/leases", status_code=201)
async def acquire_monitor_lease(payload: AcquireLeaseRequest, request: Request):
    user_id = _authenticated_user_id(request)
    try:
        lease = await asyncio.to_thread(
            get_monitor_lease_store().acquire,
            user_id=user_id,
            session_id=payload.session_id,
            symbol=payload.symbol,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="monitor lease store unavailable") from exc
    return {"lease": lease}


@monitor_router.put("/api/monitor/leases/{lease_id}")
async def renew_monitor_lease(lease_id: uuid.UUID, payload: LeaseTokenRequest, request: Request):
    user_id = _authenticated_user_id(request)
    try:
        expires_at = await asyncio.to_thread(
            get_monitor_lease_store().renew,
            str(lease_id),
            user_id=user_id,
            lease_token=payload.lease_token,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="monitor lease store unavailable") from exc
    if expires_at is None:
        raise HTTPException(status_code=404, detail="monitor lease not found")
    return {"success": True, "expires_at": expires_at}


@monitor_router.delete("/api/monitor/leases/{lease_id}")
async def release_monitor_lease(lease_id: uuid.UUID, payload: LeaseTokenRequest, request: Request):
    user_id = _authenticated_user_id(request)
    try:
        released = await asyncio.to_thread(
            get_monitor_lease_store().release,
            str(lease_id),
            user_id=user_id,
            lease_token=payload.lease_token,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="monitor lease store unavailable") from exc
    if not released:
        raise HTTPException(status_code=404, detail="monitor lease not found")
    return {"success": True}


def _public_comment(comment: Any) -> dict[str, Any]:
    payload = comment.model_dump(mode="json")
    prediction_id = payload.get("prediction_id")
    payload["chart_url"] = (
        f"/dashboard/{payload['symbol']}?analysis={prediction_id}" if prediction_id else None
    )
    return payload


@monitor_router.get("/api/monitor/comments")
async def list_monitor_comments(
    request: Request,
    session_id: SessionQuery,
    symbol: SymbolQuery,
    day: date | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
):
    user_id = _authenticated_user_id(request)
    try:
        items, next_cursor = await asyncio.to_thread(
            get_monitor_comment_store().list,
            user_id=user_id,
            session_id=session_id,
            symbol=symbol,
            day=day,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="monitor comment store unavailable") from exc
    return {"comments": [_public_comment(item) for item in items], "next_cursor": next_cursor}


@monitor_router.get("/api/monitor/comments/stream")
async def stream_monitor_comments(
    request: Request,
    session_id: SessionQuery,
    symbol: SymbolQuery,
    last_event_id: str | None = None,
):
    user_id = _authenticated_user_id(request)
    resume_id = last_event_id or request.headers.get("last-event-id")
    if resume_id:
        try:
            resume_id = str(uuid.UUID(resume_id))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="invalid monitor comment event id") from exc
    store = get_monitor_comment_store()

    try:
        if resume_id:
            initial_items = await asyncio.to_thread(
                store.list_after,
                user_id=user_id,
                session_id=session_id,
                symbol=symbol,
                last_event_id=resume_id,
            )
            initial_is_snapshot = False
        else:
            initial_items, _ = await asyncio.to_thread(
                store.list,
                user_id=user_id,
                session_id=session_id,
                symbol=symbol,
                day=datetime.now(timezone.utc).date(),
                limit=100,
            )
            initial_is_snapshot = True
    except Exception as exc:
        raise HTTPException(status_code=503, detail="monitor comment store unavailable") from exc

    async def events():
        current_id = resume_id
        try:
            if initial_is_snapshot:
                if initial_items:
                    current_id = initial_items[0].id
                yield "event: snapshot\ndata: " + json.dumps(
                    [_public_comment(item) for item in initial_items],
                    ensure_ascii=False,
                ) + "\n\n"
            else:
                for item in initial_items:
                    current_id = item.id
                    yield (
                        f"id: {item.id}\nevent: comment\ndata: "
                        f"{json.dumps(_public_comment(item), ensure_ascii=False)}\n\n"
                    )

            idle_seconds = 0
            while not await request.is_disconnected():
                await asyncio.sleep(2)
                if current_id:
                    fresh = await asyncio.to_thread(
                        store.list_after,
                        user_id=user_id,
                        session_id=session_id,
                        symbol=symbol,
                        last_event_id=current_id,
                    )
                else:
                    recent, _ = await asyncio.to_thread(
                        store.list,
                        user_id=user_id,
                        session_id=session_id,
                        symbol=symbol,
                        limit=100,
                    )
                    fresh = list(reversed(recent))
                for item in fresh:
                    current_id = item.id
                    yield (
                        f"id: {item.id}\nevent: comment\ndata: "
                        f"{json.dumps(_public_comment(item), ensure_ascii=False)}\n\n"
                    )
                idle_seconds += 2
                if idle_seconds >= 8:
                    idle_seconds = 0
                    yield "event: heartbeat\ndata: {}\n\n"
        except Exception:
            yield 'event: error\ndata: {"message":"monitor comment stream unavailable"}\n\n'

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["monitor_router"]
