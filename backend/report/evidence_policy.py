# -*- coding: utf-8 -*-
"""
Evidence policy and canonical report quality helpers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, TypedDict

from backend.report.ir import ReportContent, ReportIR, ReportSection


QualityState = Literal["pass", "warn", "block"]
QualitySeverity = Literal["warn", "block"]
QUALITY_SCHEMA_VERSION = "report.quality.v1"
QUALITY_STATE_ORDER: dict[QualityState, int] = {"pass": 0, "warn": 1, "block": 2}


KEY_SECTION_KEYWORDS = (
    "summary",
    "executive",
    "conclusion",
    "recommendation",
    "risk",
    "结论",
    "摘要",
    "建议",
    "风险",
    "投资策略",
)


class QualityReason(TypedDict):
    code: str
    severity: QualitySeverity
    metric: str
    actual: Any
    threshold: Any
    message: str


@dataclass
class EvidencePolicyResult:
    coverage: float
    total_blocks: int
    covered_blocks: int
    unique_sources: int
    invalid_refs: list[str]
    key_section_issues: list[str]
    meets_coverage: bool
    meets_min_sources: bool
    state: QualityState
    reasons: list[QualityReason]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


def normalize_quality_state(value: Any) -> QualityState:
    text = str(value or "").strip().lower()
    if text == "block":
        return "block"
    if text in {"warn", "warning"}:
        return "warn"
    return "pass"


def merge_quality_states(*states: Any) -> QualityState:
    highest: QualityState = "pass"
    for item in states:
        candidate = normalize_quality_state(item)
        if QUALITY_STATE_ORDER[candidate] > QUALITY_STATE_ORDER[highest]:
            highest = candidate
    return highest


def normalize_quality_reason(item: Any) -> QualityReason | None:
    if not isinstance(item, dict):
        return None
    code = str(item.get("code") or "").strip()
    severity = str(item.get("severity") or "").strip().lower()
    metric = str(item.get("metric") or "").strip()
    message = str(item.get("message") or "").strip()
    if not code:
        return None
    if severity not in {"warn", "block"}:
        severity = "warn"
    return {
        "code": code,
        "severity": severity,
        "metric": metric,
        "actual": item.get("actual"),
        "threshold": item.get("threshold"),
        "message": message or code,
    }


def normalize_quality_reasons(items: Any) -> list[QualityReason]:
    if not isinstance(items, list):
        return []
    output: list[QualityReason] = []
    for item in items:
        reason = normalize_quality_reason(item)
        if reason is not None:
            output.append(reason)
    return output


def extract_report_quality(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {"state": "pass", "reasons": [], "schema_version": QUALITY_SCHEMA_VERSION}

    direct = report.get("report_quality")
    if isinstance(direct, dict):
        quality = dict(direct)
    else:
        meta = report.get("meta")
        quality = dict(meta.get("report_quality") or {}) if isinstance(meta, dict) else {}

    state = normalize_quality_state(quality.get("state"))
    reasons = normalize_quality_reasons(quality.get("reasons"))
    if not reasons and state != "pass":
        reasons = [
            {
                "code": "QUALITY_STATE_ONLY",
                "severity": "warn" if state == "warn" else "block",
                "metric": "state",
                "actual": state,
                "threshold": "pass",
                "message": "quality state provided without explicit reasons",
            }
        ]
    quality["state"] = state
    quality["reasons"] = reasons
    quality.setdefault("schema_version", QUALITY_SCHEMA_VERSION)
    return quality


def is_report_quality_blocked(report: Any) -> bool:
    quality = extract_report_quality(report)
    return normalize_quality_state(quality.get("state")) == "block"


class EvidencePolicy:
    DEFAULT_MIN_COVERAGE = max(0.0, min(1.0, _env_float("REPORT_QUALITY_MIN_COVERAGE", 0.8)))
    DEFAULT_MIN_SOURCES = max(1, _env_int("REPORT_QUALITY_MIN_SOURCES", 2))
    DEFAULT_MIN_KEY_SECTION_SOURCES = max(1, _env_int("REPORT_QUALITY_MIN_KEY_SECTION_SOURCES", 2))

    @staticmethod
    def _iter_sections(sections: Iterable[ReportSection]) -> Iterable[ReportSection]:
        for section in sections:
            yield section
            if section.subsections:
                for sub in EvidencePolicy._iter_sections(section.subsections):
                    yield sub

    @staticmethod
    def _iter_contents(sections: Iterable[ReportSection]) -> Iterable[ReportContent]:
        for section in EvidencePolicy._iter_sections(sections):
            for content in section.contents:
                yield content

    @staticmethod
    def _is_key_section(title: str) -> bool:
        lower = title.lower()
        return any(keyword in lower for keyword in KEY_SECTION_KEYWORDS)

    @staticmethod
    def apply(
        report: ReportIR,
        min_coverage: float = DEFAULT_MIN_COVERAGE,
        min_sources: int = DEFAULT_MIN_SOURCES,
        min_key_section_sources: int = DEFAULT_MIN_KEY_SECTION_SOURCES,
    ) -> EvidencePolicyResult:
        if not isinstance(report.meta, dict):
            report.meta = {}

        valid_ids: set[str] = set()
        for citation in report.citations or []:
            if citation.source_id:
                valid_ids.add(citation.source_id)

        total_blocks = 0
        covered_blocks = 0
        invalid_refs: list[str] = []
        used_refs: set[str] = set()

        for content in EvidencePolicy._iter_contents(report.sections):
            total_blocks += 1
            refs = content.citation_refs or []
            if refs:
                valid_refs = [ref for ref in refs if ref in valid_ids]
                invalid_refs.extend([ref for ref in refs if ref not in valid_ids])
                content.citation_refs = valid_refs
                if valid_refs:
                    covered_blocks += 1
                    used_refs.update(valid_refs)
            else:
                content.citation_refs = []

        coverage = covered_blocks / total_blocks if total_blocks > 0 else 0.0

        key_section_issues: list[str] = []
        key_section_ref_counts: list[int] = []
        for section in EvidencePolicy._iter_sections(report.sections):
            if not EvidencePolicy._is_key_section(section.title):
                continue
            section_refs: set[str] = set()
            for content in section.contents:
                section_refs.update(content.citation_refs or [])
            key_section_ref_counts.append(len(section_refs))
            if len(section_refs) < min_key_section_sources:
                key_section_issues.append(
                    f"{section.title} refs<{min_key_section_sources}",
                )

        unique_sources = len(used_refs)
        meets_coverage = coverage >= min_coverage
        meets_min_sources = unique_sources >= min_sources

        reasons: list[QualityReason] = []
        if not meets_coverage:
            reasons.append(
                {
                    "code": "EVIDENCE_COVERAGE_BELOW_MIN",
                    "severity": "block",
                    "metric": "coverage",
                    "actual": round(coverage, 4),
                    "threshold": min_coverage,
                    "message": "evidence coverage is below minimum threshold",
                }
            )
        if not meets_min_sources:
            reasons.append(
                {
                    "code": "EVIDENCE_SOURCES_BELOW_MIN",
                    "severity": "block",
                    "metric": "unique_sources",
                    "actual": unique_sources,
                    "threshold": min_sources,
                    "message": "unique evidence source count is below minimum threshold",
                }
            )
        if key_section_issues:
            reasons.append(
                {
                    "code": "KEY_SECTION_SOURCES_BELOW_MIN",
                    "severity": "block",
                    "metric": "key_section_unique_sources",
                    "actual": min(key_section_ref_counts) if key_section_ref_counts else 0,
                    "threshold": min_key_section_sources,
                    "message": "key sections do not meet minimum source requirement",
                }
            )
        if invalid_refs:
            reasons.append(
                {
                    "code": "INVALID_CITATION_REFS_REMOVED",
                    "severity": "warn",
                    "metric": "invalid_refs_count",
                    "actual": len(set(invalid_refs)),
                    "threshold": 0,
                    "message": "invalid citation refs were removed during validation",
                }
            )

        state = merge_quality_states(*(reason["severity"] for reason in reasons))

        quality_payload = {
            "schema_version": QUALITY_SCHEMA_VERSION,
            "state": state,
            "evaluated_at": _now_iso(),
            "reasons": reasons,
            "metrics": {
                "coverage": round(coverage, 4),
                "covered_blocks": covered_blocks,
                "total_blocks": total_blocks,
                "unique_sources": unique_sources,
                "invalid_refs_count": len(set(invalid_refs)),
                "key_section_issues_count": len(key_section_issues),
            },
            "thresholds": {
                "min_coverage": min_coverage,
                "min_sources": min_sources,
                "min_key_section_sources": min_key_section_sources,
            },
            "details": {
                "invalid_refs": sorted(set(invalid_refs)),
                "key_section_issues": key_section_issues,
                "meets_coverage": meets_coverage,
                "meets_min_sources": meets_min_sources,
            },
        }
        report.meta["report_quality"] = quality_payload
        report.meta["evidence_policy"] = {
            "status": (
                "warning"
                if state == "warn"
                else state
            ),
            "coverage": round(coverage, 4),
            "covered_blocks": covered_blocks,
            "total_blocks": total_blocks,
            "unique_sources": unique_sources,
            "min_coverage": min_coverage,
            "min_sources": min_sources,
            "min_key_section_sources": min_key_section_sources,
            "invalid_refs": sorted(set(invalid_refs)),
            "key_section_issues": key_section_issues,
            "meets_coverage": meets_coverage,
            "meets_min_sources": meets_min_sources,
            "quality_state": state,
            "quality_reasons": reasons,
        }

        if state != "pass":
            risk_message = "证据覆盖率或引用来源不足，结论可信度下降，请谨慎参考。"
            if risk_message not in report.risks:
                report.risks.append(risk_message)

        return EvidencePolicyResult(
            coverage=coverage,
            total_blocks=total_blocks,
            covered_blocks=covered_blocks,
            unique_sources=unique_sources,
            invalid_refs=sorted(set(invalid_refs)),
            key_section_issues=key_section_issues,
            meets_coverage=meets_coverage,
            meets_min_sources=meets_min_sources,
            state=state,
            reasons=reasons,
        )
