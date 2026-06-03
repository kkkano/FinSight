from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException

# 防御性校验: report_id 仅允许安全字符
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")
# 价差接口的 ticker 校验：字母数字 + 常见交易代码符号（^ . - =）
_SAFE_TICKER_PATTERN = re.compile(r"^[A-Za-z0-9.\-=^]{1,24}$")


def _validate_report_id(report_id: str) -> str:
    """校验 report_id 格式，防止注入或路径穿越。"""
    if not report_id or not _SAFE_ID_PATTERN.fullmatch(report_id):
        raise HTTPException(status_code=422, detail="report_id format invalid")
    return report_id


def _parse_report_generated_at(value: Optional[str]) -> Optional[datetime]:
    """解析报告生成时间戳，支持 ISO8601（含 Z 后缀），失败时返回 None（诚实降级）。"""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # 兼容末尾 Z（UTC）写法
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # 无时区信息时按 UTC 处理，保证后续做差不抛 naive/aware 混用错误
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _compute_report_age_hours(generated_at: Optional[datetime]) -> Optional[float]:
    """计算报告距今的小时数，时间无法解析时返回 None。"""
    if generated_at is None:
        return None
    now = datetime.now(timezone.utc)
    delta = now - generated_at
    return round(delta.total_seconds() / 3600.0, 2)


def _get_drift_threshold_pct() -> float:
    """读取价差显著阈值（百分比），环境变量缺失或非法时回退 2.0。"""
    raw = os.environ.get("REPORT_PRICE_DRIFT_THRESHOLD_PCT", "2.0")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 2.0
    # 阈值必须为正数，否则视为配置异常回退默认
    return value if value > 0 else 2.0


@dataclass(frozen=True)
class ReportRouterDeps:
    resolve_thread_id: Callable[[Optional[str]], str]
    get_report_index_store: Callable[[], Any]
    # 价格快照获取器（注入式，便于测试 mock）；返回对象需带 .price 属性或为 None
    fetch_price_snapshot: Optional[Callable[[str], Any]] = None


def create_report_router(deps: ReportRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Reports"])

    @router.get("/api/reports/index")
    async def list_report_index(
        session_id: str,
        ticker: Optional[str] = None,
        query: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        tag: Optional[str] = None,
        source_type: Optional[str] = None,
        favorite_only: bool = False,
        include_blocked: bool = False,
        limit: int = 50,
    ):
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        store = deps.get_report_index_store()
        rows = store.list_reports(
            session_id=normalized_session,
            ticker=ticker,
            query=query,
            date_from=date_from,
            date_to=date_to,
            tag=tag,
            source_type=source_type,
            favorite_only=bool(favorite_only),
            include_blocked=bool(include_blocked),
            limit=limit,
        )
        return {"success": True, "session_id": normalized_session, "items": rows, "count": len(rows)}

    @router.get("/api/reports/replay/{report_id}")
    async def get_report_replay(report_id: str, session_id: str, include_blocked: bool = False):
        report_id = _validate_report_id(report_id)
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        store = deps.get_report_index_store()
        replay = store.get_report_replay(
            session_id=normalized_session,
            report_id=report_id,
            include_blocked=bool(include_blocked),
        )
        if not replay:
            raise HTTPException(status_code=404, detail="report not found")
        return {"success": True, "session_id": normalized_session, **replay}

    @router.get("/api/reports/citations")
    async def list_report_citations(
        session_id: str,
        report_id: Optional[str] = None,
        query: Optional[str] = None,
        source_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 100,
    ):
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        store = deps.get_report_index_store()
        rows = store.list_citations(
            session_id=normalized_session,
            report_id=report_id,
            query=query,
            source_id=source_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        return {
            "success": True,
            "session_id": normalized_session,
            "items": rows,
            "count": len(rows),
        }

    @router.post("/api/reports/{report_id}/favorite")
    async def set_report_favorite(report_id: str, request: dict):
        report_id = _validate_report_id(report_id)
        session_id = request.get("session_id")
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        is_favorite = bool(request.get("is_favorite", True))
        store = deps.get_report_index_store()
        ok = store.set_favorite(
            session_id=normalized_session,
            report_id=report_id,
            is_favorite=is_favorite,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="report not found")

        return {
            "success": True,
            "session_id": normalized_session,
            "report_id": report_id,
            "is_favorite": is_favorite,
        }

    # ------------------------------------------------------------------
    # GET /api/reports/compare — structural diff between two reports
    # ------------------------------------------------------------------

    @router.get("/api/reports/compare")
    async def compare_reports(
        session_id: str,
        id1: str,
        id2: str,
        include_blocked: bool = False,
    ):
        """Compare two reports and return structured differences."""
        id1 = _validate_report_id(id1)
        id2 = _validate_report_id(id2)
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        store = deps.get_report_index_store()
        report_a = store.get_report_replay(
            session_id=normalized_session,
            report_id=id1,
            include_blocked=bool(include_blocked),
        )
        report_b = store.get_report_replay(
            session_id=normalized_session,
            report_id=id2,
            include_blocked=bool(include_blocked),
        )
        if not report_a:
            raise HTTPException(status_code=404, detail=f"report {id1} not found")
        if not report_b:
            raise HTTPException(status_code=404, detail=f"report {id2} not found")

        # Build structured diff
        def _safe_get(d: dict, *keys: str, default: Any = None) -> Any:
            current = d
            for key in keys:
                if not isinstance(current, dict):
                    return default
                current = current.get(key, default)
            return current

        ra = report_a.get("report", {}) if isinstance(report_a.get("report"), dict) else {}
        rb = report_b.get("report", {}) if isinstance(report_b.get("report"), dict) else {}

        # Score changes
        score_a = _safe_get(ra, "confidence_score")
        score_b = _safe_get(rb, "confidence_score")
        score_delta = None
        if isinstance(score_a, (int, float)) and isinstance(score_b, (int, float)):
            score_delta = round(score_b - score_a, 4)

        # Sentiment changes
        sentiment_a = _safe_get(ra, "sentiment") or _safe_get(ra, "recommendation")
        sentiment_b = _safe_get(rb, "sentiment") or _safe_get(rb, "recommendation")

        # Risk changes
        risks_a = _safe_get(ra, "risks", default=[]) or []
        risks_b = _safe_get(rb, "risks", default=[]) or []
        risks_a_set = {str(r) for r in risks_a} if isinstance(risks_a, list) else set()
        risks_b_set = {str(r) for r in risks_b} if isinstance(risks_b, list) else set()

        # Summary / key metric changes
        summary_a = _safe_get(ra, "summary", default="")
        summary_b = _safe_get(rb, "summary", default="")

        return {
            "success": True,
            "session_id": normalized_session,
            "report_a": {"report_id": id1, "title": _safe_get(ra, "title"), "generated_at": _safe_get(ra, "generated_at")},
            "report_b": {"report_id": id2, "title": _safe_get(rb, "title"), "generated_at": _safe_get(rb, "generated_at")},
            "diff": {
                "confidence_score": {"a": score_a, "b": score_b, "delta": score_delta},
                "sentiment": {"a": sentiment_a, "b": sentiment_b, "changed": sentiment_a != sentiment_b},
                "risks": {
                    "added": sorted(risks_b_set - risks_a_set),
                    "removed": sorted(risks_a_set - risks_b_set),
                    "unchanged_count": len(risks_a_set & risks_b_set),
                },
                "summary": {"a": summary_a, "b": summary_b},
            },
        }

    # ------------------------------------------------------------------
    # GET /api/reports/price-drift — 报告价格与实时价差提示
    # ------------------------------------------------------------------

    @router.get("/api/reports/price-drift")
    async def check_price_drift(
        ticker: str,
        report_price: Optional[float] = None,
        report_generated_at: Optional[str] = None,
    ):
        """
        轻量价差检查：拉取实时价，与报告生成时刻的价格对比，提示用户结论是否需要重新评估。

        诚实原则：
        - 实时价拿不到 → current_price=null + significant=false，不报错、不编造。
        - report_price 缺失 → 只做「报告时效」提示（report_age_hours >= 24 触发）。

        significant 判定（任一成立即为真）：
        - abs(drift_pct) >= REPORT_PRICE_DRIFT_THRESHOLD_PCT（默认 2.0）
        - report_age_hours >= 24
        """
        ticker_clean = (ticker or "").strip()
        if not ticker_clean or not _SAFE_TICKER_PATTERN.fullmatch(ticker_clean):
            raise HTTPException(status_code=422, detail="ticker format invalid")

        # 报告时效（与价格无关，时间能解析就算）
        generated_at = _parse_report_generated_at(report_generated_at)
        report_age_hours = _compute_report_age_hours(generated_at)

        # 拉取实时价（注入器缺失或抛错时诚实降级为 None）
        current_price: Optional[float] = None
        fetcher = deps.fetch_price_snapshot
        if fetcher is not None:
            try:
                snapshot = fetcher(ticker_clean)
            except Exception:
                snapshot = None
            if snapshot is not None:
                raw_price = getattr(snapshot, "price", None)
                if isinstance(raw_price, (int, float)) and raw_price > 0:
                    current_price = float(raw_price)

        # 价差百分比：仅在报告价 + 实时价都有效时计算
        drift_pct: Optional[float] = None
        if (
            isinstance(report_price, (int, float))
            and report_price > 0
            and current_price is not None
        ):
            drift_pct = round((current_price - report_price) / report_price * 100.0, 2)

        # significant 判定
        threshold = _get_drift_threshold_pct()
        price_significant = drift_pct is not None and abs(drift_pct) >= threshold
        age_significant = report_age_hours is not None and report_age_hours >= 24.0
        significant = bool(price_significant or age_significant)

        return {
            "ticker": ticker_clean,
            "report_price": report_price,
            "current_price": current_price,
            "drift_pct": drift_pct,
            "report_age_hours": report_age_hours,
            "threshold_pct": threshold,
            "significant": significant,
        }

    return router
