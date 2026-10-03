"""不依赖 SPA/Service Worker 的页面修复入口，不读取用户或凭据。"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/api/client-recovery", response_class=HTMLResponse, include_in_schema=False)
def client_recovery():
    return HTMLResponse(
        Path(__file__).with_name("client_recovery.html").read_text(encoding="utf-8"),
        headers={"Cache-Control":"no-cache, no-store, must-revalidate", "X-Content-Type-Options":"nosniff",
                 "Content-Security-Policy":"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
                 "Referrer-Policy":"no-referrer"},
    )
