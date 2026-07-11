from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.backtest_prefill import build_backtest_prefill
from backend.api.schemas import BacktestPrefillRequest, BacktestRequest
from backend.services.backtest_engine import BacktestEngine
from backend.services.report_index import get_report_index_store


backtest_router = APIRouter(tags=["Backtest"])


@backtest_router.get("/api/backtest/strategies")
def list_backtest_strategies():
    return {
        "success": True,
        "strategies": BacktestEngine.list_strategies(),
    }


@backtest_router.post("/api/backtest/run")
def run_backtest(payload: BacktestRequest):
    engine = BacktestEngine()
    result = engine.run(
        ticker=payload.ticker,
        strategy=payload.strategy,
        params=payload.params,
        start_date=payload.start_date,
        end_date=payload.end_date,
        initial_cash=payload.initial_cash,
        fee_bps=payload.fee_bps,
        slippage_bps=payload.slippage_bps,
        t_plus_one=payload.t_plus_one,
        market=payload.market,
    )
    return result


@backtest_router.post("/api/backtest/prefill-from-report")
def prefill_backtest_from_report(payload: BacktestPrefillRequest):
    report = get_report_index_store().get_report_by_id(report_id=payload.report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    try:
        return build_backtest_prefill(report)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = ["backtest_router"]
