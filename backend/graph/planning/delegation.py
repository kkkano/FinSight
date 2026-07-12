# -*- coding: utf-8 -*-
"""Agent 动态委托的白名单目录与硬上限。"""
from __future__ import annotations

from typing import Any, Callable


def _ticker(step: dict[str, Any]) -> str:
    inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
    return str(inputs.get("ticker") or inputs.get("symbol") or "").strip().upper()


def _peer_tickers(step: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    ticker = _ticker(step)
    return {
        "kind": "tool",
        "name": "search",
        "inputs": {"query": f"{ticker} publicly traded competitors peer tickers".strip()},
    }


def _event_context(step: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    ticker = _ticker(step)
    return {
        "kind": "tool",
        "name": "search",
        "inputs": {"query": f"{ticker} latest price move catalyst event news".strip()},
    }


def _macro_snapshot(step: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "tool", "name": "get_economic_events", "inputs": {}}


DELEGATION_CATALOG: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "peer_tickers": _peer_tickers,
    "event_context": _event_context,
    "macro_snapshot": _macro_snapshot,
}

LIMITS = {"max_dynamic_steps_per_run": 2}

__all__ = ["DELEGATION_CATALOG", "LIMITS"]
