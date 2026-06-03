from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    SubscriptionListResponse,
    SubscriptionRequest,
    SubscriptionResponse,
    ToggleSubscriptionRequest,
    UnsubscribeRequest,
)

logger = logging.getLogger(__name__)

# 对外统一的通用错误消息——内部异常细节只记日志，绝不回传公网（防泄露路径/堆栈）。
_GENERIC_ERROR = "处理失败，请稍后重试"


def create_subscription_router() -> APIRouter:
    router = APIRouter(tags=["Subscription"])

    @router.post("/api/subscribe")
    async def subscribe_email(request: SubscriptionRequest):
        try:
            from backend.services.subscription_service import get_subscription_service

            subscription_service = get_subscription_service()
            if not subscription_service.is_valid_email(request.email):
                raise HTTPException(status_code=400, detail="Invalid email")

            success = subscription_service.subscribe(
                email=request.email,
                ticker=request.ticker,
                alert_types=request.alert_types,
                price_threshold=request.price_threshold,
                alert_mode=request.alert_mode,
                price_target=request.price_target,
                direction=request.direction,
                risk_threshold=request.risk_threshold,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Subscribed to {request.ticker}",
                    "email": request.email,
                    "ticker": request.ticker,
                }
            raise HTTPException(status_code=500, detail="Subscribe failed")
        except HTTPException:
            raise
        except Exception as exc:
            # 内部异常只进日志，对外返回通用消息。
            logger.error("[Subscription] subscribe 失败: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=_GENERIC_ERROR) from exc

    @router.post("/api/unsubscribe")
    async def unsubscribe_email(request: UnsubscribeRequest):
        try:
            from backend.services.subscription_service import get_subscription_service

            subscription_service = get_subscription_service()
            if not request.email:
                raise HTTPException(status_code=400, detail="email is required")

            success = subscription_service.unsubscribe(
                email=request.email,
                ticker=request.ticker,
            )

            if success:
                return {
                    "success": True,
                    "message": "Unsubscribed",
                    "email": request.email,
                    "ticker": request.ticker or "all",
                }
            raise HTTPException(status_code=404, detail="Subscription not found")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("[Subscription] unsubscribe 失败: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=_GENERIC_ERROR) from exc

    @router.get("/api/subscriptions", response_model=SubscriptionListResponse)
    async def get_subscriptions(email: str | None = None):
        try:
            from backend.services.subscription_service import get_subscription_service

            subscription_service = get_subscription_service()

            # 关键防护（防全站 PII dump）：email 必填且必须是合法邮箱。
            # email=None/空 时绝不返回全量订阅（旧逻辑会 dump 全站邮箱+持仓），直接 400。
            normalized_email = (email or "").strip()
            if not normalized_email:
                raise HTTPException(status_code=400, detail="email is required")
            if not subscription_service.is_valid_email(normalized_email):
                raise HTTPException(status_code=400, detail="Invalid email")

            # 所有权语义：按邮箱精确匹配，只返回该邮箱自己的订阅。
            # 显式传 include_all=False 作为纵深防御，杜绝走到全量分支。
            subscriptions = subscription_service.get_subscriptions(
                email=normalized_email,
                include_all=False,
            )
            return {
                "success": True,
                "subscriptions": subscriptions,
                "count": len(subscriptions),
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("[Subscription] get_subscriptions 失败: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=_GENERIC_ERROR) from exc

    @router.post("/api/subscription/toggle", response_model=SubscriptionResponse)
    async def toggle_subscription(request: ToggleSubscriptionRequest):
        try:
            from backend.services.subscription_service import get_subscription_service

            subscription_service = get_subscription_service()
            success = subscription_service.toggle_subscription(
                email=request.email,
                ticker=request.ticker,
                enabled=request.enabled,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Subscription {'enabled' if request.enabled else 'disabled'}",
                    "email": request.email,
                    "ticker": request.ticker,
                }
            raise HTTPException(status_code=404, detail="Subscription not found")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("[Subscription] toggle_subscription 失败: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=_GENERIC_ERROR) from exc

    return router
