from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.services.subscription_service import get_subscription_service


def create_alerts_router() -> APIRouter:
    router = APIRouter(tags=["Alerts"])

    @router.get("/api/alerts/feed")
    async def get_alert_feed(
        email: str = Query(..., min_length=3, description="Subscriber email"),
        limit: int = Query(30, ge=1, le=200, description="Max events"),
        since: str | None = Query(None, description="ISO datetime lower bound"),
    ):
        service = get_subscription_service()
        if not service.is_valid_email(email):
            raise HTTPException(status_code=400, detail="Invalid email")

        events = service.list_alert_events(email, limit=limit, since=since)
        return {
            "success": True,
            "email": email,
            "events": events,
            "count": len(events),
        }

    return router
