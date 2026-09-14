#!/usr/bin/env python3
"""Probe the real K-line gateway without accepting synthetic market data."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.market_data_gateway import (  # noqa: E402
    MARKET_DATA_UNAVAILABLE,
    get_market_data_gateway,
    validate_kline_bars,
)


FORBIDDEN_MARKERS = ("synthetic", "price_fallback", "mock_ohlc", "mock_kline")


def _contains_forbidden_marker(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            any(marker in str(key).lower() for marker in FORBIDDEN_MARKERS)
            or _contains_forbidden_marker(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_marker(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return any(marker in lowered for marker in FORBIDDEN_MARKERS)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--symbols", default="AAPL,MSFT,NVDA,AMZN,TSLA")
    parser.add_argument("--period", default="1mo")
    parser.add_argument("--interval", default="1d")
    parser.add_argument("--require-live", action="store_true")
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if args.iterations <= 0 or not symbols:
        raise SystemExit("iterations and symbols must be non-empty")

    gateway = get_market_data_gateway()
    providers: Counter[str] = Counter()
    qualities: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    violations: list[dict[str, Any]] = []
    successes = 0

    for index in range(args.iterations):
        symbol = symbols[index % len(symbols)]
        result = gateway.get_kline(symbol, period=args.period, interval=args.interval)
        error_code = result.get("error_code")
        if error_code not in (None, MARKET_DATA_UNAVAILABLE):
            violations.append({"index": index, "symbol": symbol, "reason": "unstable_error_code"})
        if _contains_forbidden_marker(result):
            violations.append({"index": index, "symbol": symbol, "reason": "forbidden_marker"})
        if args.require_live and result.get("cached"):
            violations.append({"index": index, "symbol": symbol, "reason": "cache_hit"})

        providers[str(result.get("provider") or "unavailable")] += 1
        qualities[str(result.get("quality") or "unknown")] += 1
        if error_code:
            errors[str(error_code)] += 1
            continue
        try:
            validate_kline_bars(result.get("kline_data"))
        except Exception as exc:
            violations.append(
                {"index": index, "symbol": symbol, "reason": f"invalid_kline:{type(exc).__name__}"}
            )
            continue
        successes += 1

    report = {
        "iterations": args.iterations,
        "symbols": symbols,
        "successes": successes,
        "providers": dict(providers),
        "qualities": dict(qualities),
        "errors": dict(errors),
        "health": gateway.health_snapshot(),
        "violations": violations,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
