from __future__ import annotations

import traceback

from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    SubscriptionListResponse,
    SubscriptionRequest,
    SubscriptionResponse,
    ToggleSubscriptionRequest,
    UnsubscribeRequest,
)


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
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/subscriptions", response_model=SubscriptionListResponse)
    async def get_subscriptions(email: str = None):
        try:
            from backend.services.subscription_service import get_subscription_service

            subscription_service = get_subscription_service()
            subscriptions = subscription_service.get_subscriptions(email=email)
            return {
                "success": True,
                "subscriptions": subscriptions,
                "count": len(subscriptions),
            }
        except Exception as exc:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
