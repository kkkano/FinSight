"""Public benchmark results. No raw prompts, credentials or private identities."""
from fastapi import APIRouter, Query

from backend.services.prediction_runner import enabled
from backend.services.prediction_store import get_prediction_store

router = APIRouter(prefix="/api/benchmarks", tags=["Public benchmarks"])


@router.get("/us20-v1/track-record")
def track_record(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    return get_prediction_store().public_report(enabled=enabled(), limit=limit, offset=offset)
