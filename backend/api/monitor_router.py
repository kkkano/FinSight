# -*- coding: utf-8 -*-
"""
工作台 Phase 1：盯盘 API（Finding + MonitorTarget + 手动扫描）。

数据落独立 ``monitor.db``，规则扫描复用 monitor_engine（零 LLM 成本）。
所有接口走 session_id 隔离，模式与 portfolio_router 一致。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.monitor_engine import run_l1_scan
from backend.services.monitor_store import get_monitor_store

logger = logging.getLogger(__name__)

monitor_router = APIRouter(tags=["Monitor"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 请求模型 ──────────────────────────────────────────────────


class UpdateFindingRequest(BaseModel):
    status: str = Field(..., pattern="^(new|viewed|acted)$")


class CreateTargetRequest(BaseModel):
    session_id: str
    type: str = Field(default="custom")
    ticker: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class PatchTargetRequest(BaseModel):
    config: dict[str, Any] | None = None
    enabled: bool | None = None


# ── Findings ──────────────────────────────────────────────────


@monitor_router.get("/api/monitor/findings")
async def list_findings_endpoint(session_id: str, status: str | None = None, limit: int = 50):
    """返回 session 的盯盘发现（按时间倒序，可按状态过滤）。"""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    findings = get_monitor_store().list_findings(session_id, status=status, limit=limit)
    return {"findings": findings, "count": len(findings)}


@monitor_router.patch("/api/monitor/findings/{finding_id}")
async def update_finding_endpoint(finding_id: str, session_id: str, request: UpdateFindingRequest):
    """更新某条 finding 的状态（new/viewed/acted）。"""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    ok = get_monitor_store().update_finding_status(session_id, finding_id, request.status)
    if not ok:
        raise HTTPException(status_code=404, detail="finding not found")
    return {"success": True, "finding_id": finding_id, "status": request.status}


@monitor_router.post("/api/monitor/scan")
async def scan_endpoint(session_id: str):
    """手动触发该 session 的 L1 规则扫描，返回本次新产生的 findings。"""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    try:
        findings = await run_l1_scan(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[MonitorRouter] manual scan failed for %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail="scan failed") from exc
    return {"findings": findings, "count": len(findings)}


# ── Targets ───────────────────────────────────────────────────


@monitor_router.get("/api/monitor/targets")
async def list_targets_endpoint(session_id: str):
    """返回 session 的盯盘标的列表。"""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    targets = get_monitor_store().list_targets(session_id)
    return {"targets": targets, "count": len(targets)}


@monitor_router.post("/api/monitor/targets")
async def create_target_endpoint(request: CreateTargetRequest):
    """新建盯盘标的（id / created_at 由服务端生成）。"""
    if not request.session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    target = {
        "id": uuid.uuid4().hex,
        "session_id": request.session_id,
        "type": request.type,
        "ticker": request.ticker.strip().upper() if request.ticker else None,
        "config": request.config,
        "enabled": request.enabled,
        "created_at": _now_iso(),
    }
    get_monitor_store().upsert_target(target)
    return {"success": True, "target": target}


@monitor_router.patch("/api/monitor/targets/{target_id}")
async def patch_target_endpoint(target_id: str, session_id: str, request: PatchTargetRequest):
    """更新盯盘标的的 config / enabled（部分字段）。"""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    store = get_monitor_store()
    existing = next((t for t in store.list_targets(session_id) if t["id"] == target_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="target not found")

    updated = {
        **existing,
        "config": request.config if request.config is not None else existing["config"],
        "enabled": request.enabled if request.enabled is not None else existing["enabled"],
    }
    store.upsert_target(updated)
    return {"success": True, "target": updated}


@monitor_router.delete("/api/monitor/targets/{target_id}")
async def delete_target_endpoint(target_id: str, session_id: str):
    """删除盯盘标的（session 隔离）。"""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    ok = get_monitor_store().delete_target(session_id, target_id)
    if not ok:
        raise HTTPException(status_code=404, detail="target not found")
    return {"success": True, "removed_target_id": target_id}


__all__ = ["monitor_router"]
