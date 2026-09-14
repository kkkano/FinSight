from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request


def create_user_router() -> APIRouter:
    """只暴露当前认证用户的只读资料，不维护第二套 JSON 用户画像。"""
    router = APIRouter(tags=["User"])

    @router.get("/api/user/profile")
    async def get_user_profile(request: Request):
        user_id = str(getattr(request.state, "user_id", "public") or "public").strip()
        if not user_id or user_id == "public":
            raise HTTPException(
                status_code=401,
                detail={"code": "auth_required", "message": "登录后才能读取账户资料"},
            )
        return {
            "user": {
                "id": user_id,
                "email": str(getattr(request.state, "user_email", "") or "").strip() or None,
            }
        }

    return router
