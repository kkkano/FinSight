# -*- coding: utf-8 -*-
"""
Optional Prometheus metrics helpers.
"""

from __future__ import annotations

from typing import Tuple

try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

    METRICS_ENABLED = True

    ORCH_LATENCY = Histogram(
        "finsight_orchestrator_latency_seconds",
        "Tool orchestrator latency",
        ["data_type"],
    )
    ORCH_CACHE_HIT = Counter(
        "finsight_orchestrator_cache_hits_total",
        "Tool orchestrator cache hits",
        ["data_type"],
    )
    ORCH_FALLBACK = Counter(
        "finsight_orchestrator_fallback_total",
        "Tool orchestrator fallback usage",
        ["data_type"],
    )
    ORCH_FAILURE = Counter(
        "finsight_orchestrator_failures_total",
        "Tool orchestrator failures",
        ["data_type", "source"],
    )
    REPORT_QUALITY_STATE = Counter(
        "finsight_report_quality_state_total",
        "Report quality state totals",
        ["state", "source"],
    )
    REPORT_QUALITY_REASON = Counter(
        "finsight_report_quality_reason_total",
        "Report quality reason totals",
        ["code", "severity", "source"],
    )
    REPORT_QUALITY_GROUNDING = Histogram(
        "finsight_report_quality_grounding_rate",
        "Grounding rate observed in report quality evaluation",
        ["source"],
    )
except Exception:  # pragma: no cover - optional dependency
    METRICS_ENABLED = False

    class _Noop:
        def labels(self, *args, **kwargs):  # noqa: D401
            return self

        def inc(self, *args, **kwargs):
            return None

        def observe(self, *args, **kwargs):
            return None

    ORCH_LATENCY = _Noop()
    ORCH_CACHE_HIT = _Noop()
    ORCH_FALLBACK = _Noop()
    ORCH_FAILURE = _Noop()
    REPORT_QUALITY_STATE = _Noop()
    REPORT_QUALITY_REASON = _Noop()
    REPORT_QUALITY_GROUNDING = _Noop()
    CONTENT_TYPE_LATEST = "text/plain"

    def generate_latest():  # type: ignore[override]
        return b""


def observe_orch_latency(data_type: str, duration_ms: float) -> None:
    if not METRICS_ENABLED:
        return
    ORCH_LATENCY.labels(data_type=data_type).observe(duration_ms / 1000.0)


def increment_cache_hit(data_type: str) -> None:
    ORCH_CACHE_HIT.labels(data_type=data_type).inc()


def increment_fallback(data_type: str) -> None:
    ORCH_FALLBACK.labels(data_type=data_type).inc()


def increment_failure(data_type: str, source: str) -> None:
    ORCH_FAILURE.labels(data_type=data_type, source=source).inc()


def increment_report_quality_state(*, state: str, source: str) -> None:
    REPORT_QUALITY_STATE.labels(state=state, source=source).inc()


def increment_report_quality_reason(*, code: str, severity: str, source: str) -> None:
    REPORT_QUALITY_REASON.labels(code=code, severity=severity, source=source).inc()


def observe_report_quality_grounding_rate(*, grounding_rate: float, source: str) -> None:
    if grounding_rate < 0:
        return
    REPORT_QUALITY_GROUNDING.labels(source=source).observe(grounding_rate)


def metrics_payload() -> Tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
