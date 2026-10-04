# -*- coding: utf-8 -*-
"""
Unified report quality engine.

This module centralizes:
- runtime quality reason generation
- quality payload merge/dedupe/sort
- report quality annotation + publishability gate
- quality metrics emission
"""

from __future__ import annotations

from backend.utils.env import env_float as _env_float
from backend.utils.env import env_int as _env_int

from dataclasses import dataclass
from typing import Any, Iterable

from backend.contracts import REPORT_QUALITY_REASON_CODES
from backend.metrics import (
    increment_report_quality_reason,
    increment_report_quality_state,
    observe_report_quality_grounding_rate,
)
from backend.report.evidence_policy import (
    QUALITY_SCHEMA_VERSION,
    extract_report_quality,
    merge_quality_states,
    normalize_quality_reason,
    normalize_quality_reasons,
    normalize_quality_state,
)


@dataclass(frozen=True)
class RuntimeQualityThresholds:
    grounding_block: float = 0.6
    grounding_warn: float = 0.75
    verifier_block_count: int = 3
    verifier_warn_count: int = 1


def load_runtime_quality_thresholds() -> RuntimeQualityThresholds:
    block = max(0.0, min(1.0, _env_float("REPORT_QUALITY_GROUNDING_BLOCK", 0.6)))
    warn = max(0.0, min(1.0, _env_float("REPORT_QUALITY_GROUNDING_WARN", 0.75)))
    if warn < block:
        warn = block
    verifier_block = max(1, _env_int("REPORT_QUALITY_VERIFIER_BLOCK_COUNT", 3))
    verifier_warn = max(1, _env_int("REPORT_QUALITY_VERIFIER_WARN_COUNT", 1))
    return RuntimeQualityThresholds(
        grounding_block=block,
        grounding_warn=warn,
        verifier_block_count=verifier_block,
        verifier_warn_count=verifier_warn,
    )


def _quality_reason(
    *,
    code: str,
    severity: str,
    metric: str,
    actual: Any,
    threshold: Any,
    message: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "metric": metric,
        "actual": actual,
        "threshold": threshold,
        "message": message,
    }


def dedupe_quality_reasons(reasons: Iterable[Any]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for raw in reasons:
        item = normalize_quality_reason(raw)
        if item is None:
            continue
        key = (
            str(item.get("code") or ""),
            str(item.get("severity") or ""),
            str(item.get("metric") or ""),
            str(item.get("actual")),
            str(item.get("threshold")),
            str(item.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def sort_quality_reasons(reasons: Iterable[Any]) -> list[dict[str, Any]]:
    normalized = dedupe_quality_reasons(reasons)
    normalized.sort(
        key=lambda item: (
            0 if str(item.get("severity")) == "block" else 1,
            str(item.get("code") or ""),
            str(item.get("metric") or ""),
            str(item.get("threshold")),
            str(item.get("actual")),
        )
    )
    return normalized


def build_runtime_quality_reasons(
    *,
    quality_hints: dict[str, Any] | None,
    grounding_stats: dict[str, Any] | None,
    verifier_claims: list[dict[str, Any]] | None,
    thresholds: RuntimeQualityThresholds | None = None,
) -> list[dict[str, Any]]:
    threshold_cfg = thresholds or load_runtime_quality_thresholds()
    reasons: list[dict[str, Any]] = []

    hints = quality_hints if isinstance(quality_hints, dict) else {}
    missing_counts = hints.get("missing_counts") if isinstance(hints.get("missing_counts"), dict) else {}
    deep_required = hints.get("deep_report_required") is True
    critical_missing = int(missing_counts.get("critical") or 0)
    important_missing = int(missing_counts.get("important") or 0)
    minor_missing = int(missing_counts.get("minor") or 0)
    missing_items = hints.get("missing_requirements") if isinstance(hints.get("missing_requirements"), list) else []

    if deep_required and critical_missing > 0:
        reasons.append(
            _quality_reason(
                code="QUALITY_PROFILE_CRITICAL_MISSING",
                severity="warn",
                metric="critical_missing_requirements",
                actual=critical_missing,
                threshold=0,
                message="deep report has critical missing evidence requirements",
            )
        )
    if deep_required and important_missing > 0:
        reasons.append(
            _quality_reason(
                code="QUALITY_PROFILE_IMPORTANT_MISSING",
                severity="warn",
                metric="important_missing_requirements",
                actual=important_missing,
                threshold=0,
                message="deep report has important missing evidence requirements",
            )
        )
    if deep_required and minor_missing > 0:
        reasons.append(
            _quality_reason(
                code="QUALITY_PROFILE_MINOR_MISSING",
                severity="warn",
                metric="minor_missing_requirements",
                actual=minor_missing,
                threshold=0,
                message="deep report has minor missing evidence requirements",
            )
        )

    grounding_rate = None
    if isinstance(grounding_stats, dict):
        rate = grounding_stats.get("grounding_rate")
        if isinstance(rate, (int, float)):
            grounding_rate = float(rate)

    if grounding_rate is not None:
        if grounding_rate < threshold_cfg.grounding_block:
            reasons.append(
                _quality_reason(
                    code="GROUNDING_RATE_BELOW_MIN",
                    severity="block",
                    metric="grounding_rate",
                    actual=round(grounding_rate, 4),
                    threshold=threshold_cfg.grounding_block,
                    message="grounding rate is below hard threshold",
                )
            )
        elif grounding_rate < threshold_cfg.grounding_warn:
            reasons.append(
                _quality_reason(
                    code="GROUNDING_RATE_WARN",
                    severity="warn",
                    metric="grounding_rate",
                    actual=round(grounding_rate, 4),
                    threshold=threshold_cfg.grounding_warn,
                    message="grounding rate is below warning threshold",
                )
            )

    unsupported_count = len(verifier_claims or [])
    if unsupported_count >= threshold_cfg.verifier_block_count:
        reasons.append(
            _quality_reason(
                code="VERIFIER_UNSUPPORTED_CLAIMS_BLOCK",
                severity="block",
                metric="verifier_unsupported_claims",
                actual=unsupported_count,
                threshold=threshold_cfg.verifier_block_count,
                message="fact verifier found too many unsupported claims",
            )
        )
    elif unsupported_count >= threshold_cfg.verifier_warn_count:
        reasons.append(
            _quality_reason(
                code="VERIFIER_UNSUPPORTED_CLAIMS_WARN",
                severity="warn",
                metric="verifier_unsupported_claims",
                actual=unsupported_count,
                threshold=threshold_cfg.verifier_warn_count,
                message="fact verifier found unsupported claims",
            )
        )

    if deep_required and missing_items:
        reasons.append(
            _quality_reason(
                code="QUALITY_PROFILE_MISSING_LIST",
                severity="warn",
                metric="missing_requirements_count",
                actual=len(missing_items),
                threshold=0,
                message="quality profile has missing requirement details",
            )
        )

    return sort_quality_reasons(reasons)


def merge_report_quality_payload(
    *,
    existing_quality: dict[str, Any] | None,
    reason_groups: Iterable[Iterable[Any]] | None = None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = dict(existing_quality or {})
    current_state = normalize_quality_state(current.get("state"))
    current_reasons = normalize_quality_reasons(current.get("reasons"))

    merged_reasons: list[Any] = list(current_reasons)
    for group in reason_groups or []:
        merged_reasons.extend(list(group))
    merged_reasons = sort_quality_reasons(merged_reasons)
    merged_state = merge_quality_states(
        current_state,
        *(item.get("severity") for item in merged_reasons),
    )

    payload = dict(current)
    payload["schema_version"] = QUALITY_SCHEMA_VERSION
    payload["state"] = merged_state
    payload["reasons"] = merged_reasons
    if inputs is not None:
        payload["inputs"] = inputs
    return payload


def evaluate_runtime_report_quality(
    *,
    existing_quality: dict[str, Any] | None,
    quality_hints: dict[str, Any] | None,
    grounding_stats: dict[str, Any] | None,
    verifier_claims: list[dict[str, Any]] | None,
    thresholds: RuntimeQualityThresholds | None = None,
) -> dict[str, Any]:
    threshold_cfg = thresholds or load_runtime_quality_thresholds()
    runtime_reasons = build_runtime_quality_reasons(
        quality_hints=quality_hints,
        grounding_stats=grounding_stats,
        verifier_claims=verifier_claims,
        thresholds=threshold_cfg,
    )
    return merge_report_quality_payload(
        existing_quality=existing_quality,
        reason_groups=[runtime_reasons],
        inputs={
            "quality_hints": quality_hints if isinstance(quality_hints, dict) else {},
            "grounding": grounding_stats if isinstance(grounding_stats, dict) else {},
            "verifier_unsupported_claims": len(verifier_claims or []),
            "thresholds": {
                "grounding_block": threshold_cfg.grounding_block,
                "grounding_warn": threshold_cfg.grounding_warn,
                "verifier_block_count": threshold_cfg.verifier_block_count,
                "verifier_warn_count": threshold_cfg.verifier_warn_count,
            },
        },
    )


def apply_quality_to_report(report: Any) -> tuple[dict[str, Any], bool]:
    quality = extract_report_quality(report if isinstance(report, dict) else {})
    blocked = normalize_quality_state(quality.get("state")) == "block"
    if isinstance(report, dict):
        report["report_quality"] = quality
        meta = report.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        meta["report_quality"] = quality
        report["meta"] = meta
    return quality, blocked


def evaluate_result_quality(*, state: dict[str, Any], report: dict[str, Any] | None = None) -> dict[str, Any]:
    """聊天、报告和终态服务共用裁决；已有阻断不得被后续成功覆盖。"""
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    quality = extract_report_quality(report)
    sources = [
        artifacts.get("result_quality"), artifacts.get("research_synthesis_gate"),
        artifacts.get("research_result_quality"),
    ]
    for source in sources:
        if isinstance(source, dict):
            quality = merge_report_quality_payload(
                existing_quality={**quality, "state": merge_quality_states(quality.get("state"), source.get("state"))},
                reason_groups=[normalize_quality_reasons(source.get("reasons"))],
            )

    result = artifacts.get("research_result")
    if not isinstance(result, dict):
        result = artifacts.get("research_synthesis") if isinstance(artifacts.get("research_synthesis"), dict) else {}
    tasks = result.get("task_results")
    if not isinstance(tasks, list):
        tasks = artifacts.get("task_outcomes") if isinstance(artifacts.get("task_outcomes"), list) else []
    tasks = [task for task in tasks if isinstance(task, dict)]
    claims = result.get("claim_index") if isinstance(result.get("claim_index"), dict) else {}
    evidence = result.get("evidence_index") if isinstance(result.get("evidence_index"), dict) else {}
    if not evidence:
        normalization = artifacts.get("task_evidence_normalization") or {}
        evidence = normalization.get("evidence_index") if isinstance(normalization, dict) else {}
        evidence = evidence if isinstance(evidence, dict) else {}
    supported_facts = [item for item in evidence.values() if isinstance(item, dict) and item.get("usage") == "fact"]
    supported = bool(claims or supported_facts)
    reasons: list[dict[str, Any]] = []

    def reason(code: str, severity: str, message: str) -> None:
        reasons.append(_quality_reason(code=code, severity=severity, metric="answer", actual=False, threshold=True, message=message))

    if artifacts.get("quality_blocked"):
        reason(str(artifacts.get("error_code") or "RESULT_QUALITY_BLOCKED"), "block", "研究结果未通过质量检查。")
    structural = artifacts.get("task_structural_block_reasons") or artifacts.get("research_structural_block_reasons") or []
    for code in structural if isinstance(structural, list) else []:
        reason(str(code), "block", "任务或引用结构不一致。")
    report_mode = str(state.get("output_mode") or "") == "investment_report"
    trace = state.get("trace") if isinstance(state.get("trace"), dict) else {}
    coverage = trace.get("coverage_validator") if isinstance(trace.get("coverage_validator"), dict) else {}
    missing_requirements = list(coverage.get("missing_requirements") or [])
    for task in tasks:
        for missing in task.get("missing_requirements") or []:
            if isinstance(missing, dict) and missing not in missing_requirements:
                missing_requirements.append(missing)
    for missing in missing_requirements:
        if isinstance(missing, dict):
            reasons.append(_quality_reason(
                code="REQUIRED_EVIDENCE_MISSING", severity="block" if report_mode or not supported else "warn",
                metric="task_evidence", actual=missing, threshold="verified_evidence",
                message="请求中的主体或证据维度尚未满足。",
            ))
    if tasks and not supported:
        reason("NO_SUPPORTED_CONTENT", "block", "本轮没有可展示的已验证事实或论据。")
    if any(task.get("status") != "answered" or task.get("missing_evidence") for task in tasks):
        missing_required = any(task.get("missing_evidence") for task in tasks)
        reason("TASK_PARTIALLY_ANSWERED", "block" if not supported or report_mode and missing_required else "warn", "部分请求维度仍缺少证据。")
    if report_mode and result and not claims:
        reason("NO_SUPPORTED_REPORT_CLAIMS", "block", "报告缺少受支持的研究论据，不能发布或归档。")
    if isinstance(report, dict) and isinstance(report.get("meta"), dict) and report["meta"].get("builder_fallback"):
        reason("REPORT_BUILD_FAILED", "block", "报告构建失败，当前内容仅为错误说明。")
    if any(item.get("kind") == "price_snapshot" and not item.get("as_of") for item in supported_facts):
        reason("PRICE_TIME_MISSING", "warn", "报价缺少源数据时间，不能确认其时效。")
    quality = merge_report_quality_payload(existing_quality=quality, reason_groups=[reasons])
    blocked = quality["state"] == "block"
    answer_status = "blocked" if blocked else "partial" if quality["state"] == "warn" else "answered"
    if tasks and not supported and not any(task.get("status") == "blocked" for task in tasks):
        answer_status = "unavailable"
    quality.update({
        "answer_status": answer_status,
        "has_supported_content": supported if tasks else bool(str(artifacts.get("draft_markdown") or "").strip()),
        "publishable": not blocked,
        "missing_requirements": missing_requirements,
    })
    return quality


def is_quality_blocked(payload: Any) -> bool:
    if isinstance(payload, dict) and ("state" in payload or "reasons" in payload):
        return normalize_quality_state(payload.get("state")) == "block"
    quality = extract_report_quality(payload)
    return normalize_quality_state(quality.get("state")) == "block"


def should_publish_report(report: Any) -> bool:
    return not is_quality_blocked(report)


def record_quality_metrics(quality: dict[str, Any], *, source: str) -> None:
    known_codes = set(REPORT_QUALITY_REASON_CODES)
    state = normalize_quality_state(quality.get("state"))
    increment_report_quality_state(state=state, source=source)
    for reason in normalize_quality_reasons(quality.get("reasons")):
        code = str(reason.get("code") or "UNKNOWN")
        if code not in known_codes:
            code = "UNKNOWN"
        increment_report_quality_reason(
            code=code,
            severity=str(reason.get("severity") or "warn"),
            source=source,
        )

    grounding_rate = None
    inputs = quality.get("inputs")
    if isinstance(inputs, dict):
        grounding = inputs.get("grounding")
        if isinstance(grounding, dict):
            raw = grounding.get("grounding_rate")
            if isinstance(raw, (int, float)):
                grounding_rate = float(raw)
    if grounding_rate is None:
        metrics = quality.get("metrics")
        if isinstance(metrics, dict):
            raw = metrics.get("grounding_rate")
            if isinstance(raw, (int, float)):
                grounding_rate = float(raw)
    if grounding_rate is not None:
        observe_report_quality_grounding_rate(grounding_rate=grounding_rate, source=source)


__all__ = [
    "RuntimeQualityThresholds",
    "apply_quality_to_report",
    "build_runtime_quality_reasons",
    "dedupe_quality_reasons",
    "evaluate_runtime_report_quality",
    "evaluate_result_quality",
    "is_quality_blocked",
    "load_runtime_quality_thresholds",
    "merge_report_quality_payload",
    "record_quality_metrics",
    "should_publish_report",
    "sort_quality_reasons",
]
