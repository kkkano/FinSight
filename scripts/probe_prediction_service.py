#!/usr/bin/env python3
"""在显式授权的数据库中执行真实 Prediction 生成闭环探针。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.prediction_service import (  # noqa: E402
    PredictionRun,
    get_prediction_service,
)


TERMINAL_STATUSES = {"succeeded", "unavailable", "failed", "cancelled"}


def _public_run(run: PredictionRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "symbol": run.symbol,
        "status": run.status,
        "failure_code": run.failure_code,
        "market_provider": run.market_provider,
        "market_as_of": run.market_as_of,
        "llm_provider": run.llm_provider,
        "llm_model": run.llm_model,
        "prediction_id": run.prediction_id,
        "provider_attempts": run.provider_attempts,
        "total_tokens": run.total_tokens,
        "latency_ms": run.latency_ms,
    }


def _database_counts(service: Any, *, user_id: str) -> dict[str, int]:
    statements = {
        "prediction_runs": "SELECT count(*) FROM prediction_runs WHERE user_id=:user_id",
        "agent_predictions": "SELECT count(*) FROM agent_predictions WHERE user_id=:user_id",
        "agent_run_archive": "SELECT count(*) FROM agent_run_archive WHERE user_id=:user_id",
        "llm_usage": "SELECT count(*) FROM llm_usage WHERE user_id=:user_id",
    }
    with service.store._engine.connect() as conn:
        return {
            table: int(conn.execute(text(statement), {"user_id": user_id}).scalar_one())
            for table, statement in statements.items()
        }


async def _run(args: argparse.Namespace) -> int:
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if not args.allow_write:
        raise SystemExit("该探针会写数据库，必须显式传入 --allow-write")
    if not symbols:
        raise SystemExit("symbols must be non-empty")
    user_id = str(args.user_id or "").strip()
    if not user_id or user_id == "public":
        raise SystemExit("user-id 必须是隔离的已认证 canary 身份")

    service = get_prediction_service()
    started = monotonic()
    runs: dict[str, PredictionRun] = {}
    created: dict[str, bool] = {}

    async def generate_and_wait(symbol: str) -> tuple[PredictionRun, bool]:
        async with concurrency:
            run, was_created = await service.generate(user_id=user_id, symbol=symbol)
            deadline = monotonic() + max(10.0, float(args.timeout_seconds))
            while run.status not in TERMINAL_STATUSES and monotonic() < deadline:
                await asyncio.sleep(max(0.1, float(args.poll_seconds)))
                current = await service.get_run(run.id, user_id=user_id)
                if current is not None:
                    run = current
            current = await service.get_run(run.id, user_id=user_id)
            return (current or run), was_created

    concurrency = asyncio.Semaphore(max(1, min(16, int(args.max_concurrent))))
    try:
        results = await asyncio.gather(*(generate_and_wait(symbol) for symbol in symbols))
        for run, was_created in results:
            runs[run.id] = run
            created[run.id] = was_created

        succeeded = sum(run.status == "succeeded" for run in runs.values())
        success_rate = succeeded / len(symbols)
        counts = await asyncio.to_thread(_database_counts, service, user_id=user_id)
        report = {
            "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "symbols": symbols,
            "duration_seconds": round(monotonic() - started, 3),
            "successes": succeeded,
            "success_rate": round(success_rate, 4),
            "minimum_success_rate": float(args.minimum_success_rate),
            "runs": [
                {**_public_run(run), "created": created.get(run.id, False)}
                for run in sorted(runs.values(), key=lambda item: symbols.index(item.symbol))
            ],
            "database_counts": counts,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str))

        core_rows_present = (
            counts["prediction_runs"] >= len(symbols)
            and counts["agent_predictions"] >= succeeded
            and counts["agent_run_archive"] >= succeeded
            and counts["llm_usage"] >= succeeded
        )
        return 0 if success_rate >= float(args.minimum_success_rate) and core_rows_present else 1
    finally:
        await service.stop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="AAPL,MSFT,NVDA,AMZN,TSLA")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--max-concurrent", type=int, default=1)
    parser.add_argument("--minimum-success-rate", type=float, default=0.95)
    parser.add_argument("--allow-write", action="store_true")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
