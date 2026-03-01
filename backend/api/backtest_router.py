from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import BacktestRequest
from backend.services.backtest_engine import BacktestEngine


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


__all__ = ["backtest_router"]
