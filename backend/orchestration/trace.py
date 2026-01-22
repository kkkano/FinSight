# -*- coding: utf-8 -*-
"""
Trace normalization utilities.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


def normalize_trace(raw: Any, agent_name: str = "") -> List[Dict[str, Any]]:
    if not raw:
        return []
    items: List[Any]
    if isinstance(raw, dict):
        items = raw.get("events") or raw.get("trace") or [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        items = [raw]

    normalized: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            item = {"message": str(item)}
        event_type = (
            item.get("event")
            or item.get("event_type")
            or item.get("stage")
            or item.get("type")
            or "trace"
        )
        timestamp = item.get("timestamp") or item.get("time") or item.get("ts")
        duration = item.get("duration_ms") or item.get("duration")
        metadata = {
            k: v
            for k, v in item.items()
            if k not in {"event", "event_type", "stage", "type", "timestamp", "time", "ts", "duration_ms", "duration"}
        }
        if agent_name and "agent" not in metadata:
            metadata["agent"] = agent_name
        normalized.append(
            {
                "event_type": event_type,
                "timestamp": timestamp or datetime.now().isoformat(),
                "duration_ms": duration,
                "metadata": metadata,
            }
        )
    return normalized
