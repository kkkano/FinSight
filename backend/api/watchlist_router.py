# -*- coding: utf-8 -*-
"""用户自选股 REST API。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field


class WatchlistStoreProtocol(Protocol):
    def list_items(self, user_id: str = "public") -> list[dict]: ...
    def add_item(self, ticker: str, note: str = "", user_id: str = "public") -> tuple[dict, bool]: ...
    def remove_item(self, ticker: str, user_id: str = "public") -> bool: ...


@dataclass(frozen=True)
class WatchlistRouterDeps:
    get_store: Callable[[], WatchlistStoreProtocol]


class AddWatchlistRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    note: str = Field(default="", max_length=500)


def create_watchlist_router(deps: WatchlistRouterDeps) -> APIRouter:
    router = APIRouter(prefix="/api/watchlist", tags=["Watchlist"])

    @router.get("")
    async def get_watchlist(request: Request):
        user_id = getattr(request.state, "user_id", "public")
        return {"items": deps.get_store().list_items(user_id=user_id)}

    @router.post("")
    async def add_watchlist_item(
        payload: AddWatchlistRequest,
        request: Request,
        response: Response,
    ):
        user_id = getattr(request.state, "user_id", "public")
        try:
            item, created = deps.get_store().add_item(
                payload.ticker,
                payload.note,
                user_id=user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return {"item": item}

    @router.delete("/{ticker}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_watchlist_item(ticker: str, request: Request) -> Response:
        user_id = getattr(request.state, "user_id", "public")
        try:
            deps.get_store().remove_item(ticker, user_id=user_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


__all__ = ["WatchlistRouterDeps", "create_watchlist_router"]
