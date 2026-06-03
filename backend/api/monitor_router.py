# -*- coding: utf-8 -*-
"""
工作台 Phase 1：盯盘 API（Finding + MonitorTarget + 手动扫描）。

数据落独立 ``monitor.db``，规则扫描复用 monitor_engine（零 LLM 成本）。
所有接口走 session_id 隔离，模式与 portfolio_router 一致。
"""

from __future__ import annotations

import logging
import os
import re
import time as _time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.monitor_engine import run_l1_scan
from backend.services.monitor_store import get_monitor_store
from backend.services.portfolio_store import get_positions
from backend.tools import get_event_calendar

logger = logging.getLogger(__name__)

monitor_router = APIRouter(tags=["Monitor"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── config 校验 ───────────────────────────────────────────────

# 已知 config key -> (最小值, 最大值)，超范围或未知 key 一律 422
_CONFIG_RANGES: dict[str, tuple[float, float]] = {
    "price_move_pct": (0.1, 100.0),
    "concentration_pct": (1.0, 100.0),
    "sentiment_abs_threshold": (0.05, 1.0),
    "earnings_near_days": (1, 30),
    "macro_event_days": (1, 30),
}


def _validate_config(config: dict[str, Any]) -> None:
    """校验 target.config：未知 key 拒绝、已知 key 值需在范围内。

    违规抛 HTTPException(422, 中文错误信息)，供创建/更新端点直接复用。
    """
    if not isinstance(config, dict):
        raise HTTPException(status_code=422, detail="config 必须是对象")

    for key, value in config.items():
        if key not in _CONFIG_RANGES:
            raise HTTPException(
                status_code=422, detail=f"未知的配置项「{key}」，已拒绝"
            )
        lo, hi = _CONFIG_RANGES[key]
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail=f"配置项「{key}」必须是数字"
            ) from None
        if num < lo or num > hi:
            raise HTTPException(
                status_code=422,
                detail=f"配置项「{key}」超出允许范围（{lo:g}-{hi:g}），当前 {num:g}",
            )


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _smtp_configured() -> bool:
    """SMTP 是否已配置：SMTP_USER 和 SMTP_PASSWORD 环境变量都非空。"""
    return bool(os.getenv("SMTP_USER")) and bool(os.getenv("SMTP_PASSWORD"))


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


class UpsertSettingsRequest(BaseModel):
    session_id: str
    notify_email: str | None = None
    notify_enabled: bool = False


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
async def scan_endpoint(session_id: str, enable_l2: bool = True):
    """手动触发该 session 的 L1 规则扫描，返回本次新产生的 findings。

    enable_l2 默认 True：手动扫描时附带 L2 agent 深析（受同样的成本护栏限制）。
    """
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    try:
        findings = await run_l1_scan(session_id, enable_l2=enable_l2)
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

    _validate_config(request.config)

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

    if request.config is not None:
        _validate_config(request.config)

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


# ── 宏观日历聚合 ──────────────────────────────────────────────

# 模块级缓存：(session_id, days_ahead) -> (单调时间戳, events 列表)
_MACRO_CACHE: dict[tuple[str, int], tuple[float, list[dict[str, Any]]]] = {}
_MACRO_CACHE_TTL_SECONDS = 3600.0  # 缓存 1 小时，避免每次刷新都打外部 API


def _days_until(date_str: str) -> int | None:
    """计算 ISO 日期距今天的天数（>0 未来，0 今天，<0 已过）；解析失败返回 None。"""
    try:
        target = datetime.fromisoformat(str(date_str).strip()[:10]).date()
    except (TypeError, ValueError):
        return None
    today = datetime.now(timezone.utc).date()
    return (target - today).days


def _build_macro_calendar(session_id: str, days_ahead: int) -> list[dict[str, Any]]:
    """聚合该 session 持仓 ticker 的财报事件 + 一次宏观事件，按 days_until 升序。

    - 财报：逐持仓 ticker 调 get_event_calendar 取 earnings_events（kind=earnings，带 ticker）
    - 宏观：只取一次（第一个持仓 ticker 或 'SPY' 做 probe），kind=macro，ticker=null
    - date=None 占位符过滤掉；days_until 超 [0, days_ahead] 的过滤掉
    - 外部 API 单点失败逐 ticker 捕获，不影响其他；全挂返回空列表
    诚实原则：没有确定日期的事件不展示。
    """
    try:
        positions = get_positions(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[MonitorRouter] macro-calendar get_positions failed: %s", exc)
        positions = []

    tickers = [
        str(p.get("ticker", "")).strip().upper()
        for p in positions
        if p.get("ticker")
    ]

    events: list[dict[str, Any]] = []

    # 财报事件：逐持仓 ticker（持仓为空则跳过财报部分）
    for ticker in tickers:
        try:
            calendar = get_event_calendar(ticker, days_ahead=max(7, days_ahead))
            if not isinstance(calendar, dict):
                continue
            for ev in calendar.get("earnings_events") or []:
                if not isinstance(ev, dict):
                    continue
                ev_date = ev.get("date")
                if not ev_date:  # 过滤无日期占位
                    continue
                days = _days_until(ev_date)
                if days is None or days < 0 or days > days_ahead:
                    continue
                events.append(
                    {
                        "date": str(ev_date)[:10],
                        "title": f"{ticker} 财报发布",
                        "days_until": days,
                        "kind": "earnings",
                        "ticker": ticker,
                        "source": str(ev.get("source") or "yfinance"),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - 单 ticker 失败不影响其他
            logger.warning(
                "[MonitorRouter] macro-calendar earnings fetch failed for %s: %s",
                ticker,
                exc,
            )

    # 宏观事件：只取一次（第一个持仓 ticker 或 'SPY' probe）
    probe_ticker = tickers[0] if tickers else "SPY"
    try:
        calendar = get_event_calendar(probe_ticker, days_ahead=max(7, days_ahead))
        if isinstance(calendar, dict):
            for ev in calendar.get("macro_events") or []:
                if not isinstance(ev, dict):
                    continue
                ev_date = ev.get("date")
                if not ev_date:  # 过滤 date=None 占位符
                    continue
                days = _days_until(ev_date)
                if days is None or days < 0 or days > days_ahead:
                    continue
                events.append(
                    {
                        "date": str(ev_date)[:10],
                        "title": str(ev.get("title") or "宏观事件")[:160],
                        "days_until": days,
                        "kind": "macro",
                        "ticker": None,
                        "source": str(ev.get("source") or "search"),
                    }
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[MonitorRouter] macro-calendar macro fetch failed for %s: %s",
            probe_ticker,
            exc,
        )

    events.sort(key=lambda e: e["days_until"])
    return events


@monitor_router.get("/api/monitor/macro-calendar")
async def macro_calendar_endpoint(session_id: str, days_ahead: int = 14):
    """聚合该 session 的财报 + 宏观事件日历（缓存 1 小时，外部 API 全挂返回空列表）。"""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    days_ahead = max(1, min(int(days_ahead or 14), 120))
    cache_key = (session_id, days_ahead)

    now = _time.monotonic()
    cached = _MACRO_CACHE.get(cache_key)
    if cached is not None and (now - cached[0]) < _MACRO_CACHE_TTL_SECONDS:
        events = cached[1]
    else:
        events = _build_macro_calendar(session_id, days_ahead)
        _MACRO_CACHE[cache_key] = (now, events)

    return {
        "success": True,
        "events": events,
        "as_of": _now_iso(),
    }


# ── 通知设置 ──────────────────────────────────────────────────


@monitor_router.get("/api/monitor/settings")
async def get_settings_endpoint(session_id: str):
    """返回 session 的通知设置 + SMTP 是否已配置。"""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    settings = get_monitor_store().get_settings(session_id)
    return {
        "success": True,
        "notify_email": settings.get("notify_email"),
        "notify_enabled": bool(settings.get("notify_enabled")),
        "smtp_configured": _smtp_configured(),
    }


@monitor_router.put("/api/monitor/settings")
async def upsert_settings_endpoint(request: UpsertSettingsRequest):
    """更新 session 的通知设置（邮箱格式校验 + SMTP 未配置时禁止启用通知）。"""
    if not request.session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    email = (request.notify_email or "").strip() or None
    if email is not None and not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="邮箱格式不正确")

    if request.notify_enabled:
        if not email:
            raise HTTPException(status_code=422, detail="启用通知需先填写邮箱")
        if not _smtp_configured():
            raise HTTPException(
                status_code=422, detail="服务器未配置 SMTP，无法启用邮件通知"
            )

    get_monitor_store().upsert_settings(request.session_id, email, request.notify_enabled)
    return {"success": True}


__all__ = ["monitor_router"]
