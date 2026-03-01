from __future__ import annotations

from fastapi import APIRouter, Query

from backend.tools.cn_market_board import fetch_lhb, fetch_limit_board
from backend.tools.cn_market_flow import fetch_fund_flow, fetch_northbound
from backend.tools.concept_map import fetch_concept_map


cn_market_router = APIRouter(tags=["CN Market"])


@cn_market_router.get("/api/cn/market/fund-flow")
def cn_market_fund_flow(limit: int = Query(default=20, ge=1, le=200)):
    return fetch_fund_flow(limit=limit)


@cn_market_router.get("/api/cn/market/northbound")
def cn_market_northbound(limit: int = Query(default=20, ge=1, le=200)):
    return fetch_northbound(limit=limit)


@cn_market_router.get("/api/cn/market/limit-board")
def cn_market_limit_board(limit: int = Query(default=20, ge=1, le=200)):
    return fetch_limit_board(limit=limit)


@cn_market_router.get("/api/cn/market/lhb")
def cn_market_lhb(limit: int = Query(default=20, ge=1, le=100)):
    return fetch_lhb(limit=limit)


@cn_market_router.get("/api/cn/market/concept")
def cn_market_concept(
    keyword: str = Query(default="", description="概念关键字过滤"),
    limit: int = Query(default=20, ge=1, le=200),
):
    return fetch_concept_map(keyword=keyword, limit=limit)


__all__ = ["cn_market_router"]
