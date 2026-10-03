"""公开基准结果，不暴露提示词、凭据或私人身份。"""
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from backend.services.prediction_runner import enabled
from backend.services.prediction_store import get_prediction_store

router = APIRouter(prefix="/api/benchmarks", tags=["Public benchmarks"])


@router.get("/us20-v1/track-record")
def track_record(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ticker: Annotated[str | None, Query(max_length=16, pattern=r"^[A-Za-z][A-Za-z0-9.-]*$")] = None,
    status: Literal["queued", "running", "pending", "settled", "awaiting_data", "failed", "missed", "abstained", "interrupted", "invalid"] | None = None,
    prediction_type: Literal["direction", "drawdown"] | None = None,
):
    return get_prediction_store().public_report(
        enabled=enabled(), limit=limit, offset=offset,
        ticker=ticker.upper() if ticker else None, status=status, prediction_type=prediction_type,
    )
