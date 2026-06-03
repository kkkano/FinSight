from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from backend.services.subscription_service import get_subscription_service

logger = logging.getLogger(__name__)

# 对外统一通用错误消息——内部异常细节只记日志，绝不回传公网。
_GENERIC_ERROR = "处理失败，请稍后重试"


def create_alerts_router() -> APIRouter:
    router = APIRouter(tags=["Alerts"])

    @router.get("/api/alerts/feed")
    async def get_alert_feed(
        email: str = Query(..., min_length=3, description="Subscriber email"),
        limit: int = Query(30, ge=1, le=200, description="Max events"),
        since: str | None = Query(None, description="ISO datetime lower bound"),
    ):
        try:
            service = get_subscription_service()

            normalized_email = (email or "").strip()
            if not service.is_valid_email(normalized_email):
                raise HTTPException(status_code=400, detail="Invalid email")

            # 关键防护（防 IDOR）：只有该邮箱**真实拥有订阅**时，才允许读其提醒历史。
            # 提醒历史只对已订阅用户产生，因此「无订阅的邮箱」既无合法数据、也不应
            # 被用来枚举/探测他人邮箱——直接拒绝（404，不暴露邮箱是否存在的差异）。
            owned = service.get_subscriptions(email=normalized_email, include_all=False)
            if not owned:
                raise HTTPException(status_code=404, detail="No alerts for this subscriber")

            events = service.list_alert_events(normalized_email, limit=limit, since=since)
            return {
                "success": True,
                "email": normalized_email,
                "events": events,
                "count": len(events),
            }
        except HTTPException:
            raise
        except Exception as exc:
            # 内部异常只进日志，对外返回通用消息。
            logger.error("[Alerts] get_alert_feed 失败: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=_GENERIC_ERROR) from exc

    return router
