#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Health probe for data sources.

- Pings selected tickers with force_refresh to update source stats.
- Uses ToolOrchestrator (global instance) and prints a lightweight summary.
"""

from __future__ import annotations

import os
from typing import Iterable, List

from backend.orchestration.tools_bridge import get_global_orchestrator


def _parse_tickers(env_value: str | None) -> List[str]:
    if not env_value:
        return ["AAPL", "MSFT", "^GSPC"]
    return [t.strip() for t in env_value.split(",") if t.strip()]


def run_health_probe_cycle(tickers: Iterable[str] | None = None) -> None:
    tickers = list(tickers) if tickers is not None else _parse_tickers(os.getenv("HEALTH_PROBE_TICKERS"))
    orchestrator = get_global_orchestrator()

    results = []
    for t in tickers:
        try:
            import time
            res = orchestrator.fetch("price", t, force_refresh=True)
            results.append((t, res.success, res.source, res.error))
        except Exception as e:  # pragma: no cover - diagnostic only
            results.append((t, False, "exception", str(e)))

    ok = sum(1 for r in results if r[1])
    fail = len(results) - ok
    print(f"[HealthProbe] run completed: total={len(results)} ok={ok} fail={fail}")
    for t, success, source, err in results:
        if success:
            print(f"[HealthProbe] {t}: ok via {source}")
        else:
            print(f"[HealthProbe] {t}: fail via {source} error={err}")
